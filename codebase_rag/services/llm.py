from loguru import logger
from pydantic_ai import Agent, Tool

from ..config import settings
from ..prompts import (
    CONTEXT_SYNTHESIS_PROMPT,
    CYPHER_SYSTEM_PROMPT,
    LOCAL_CYPHER_SYSTEM_PROMPT,
    RAG_ORCHESTRATOR_SYSTEM_PROMPT,
)
from ..providers.base import get_provider


class LLMGenerationError(Exception):
    """Custom exception for LLM generation failures."""

    pass


def _clean_cypher_response(response_text: str) -> str:
    """Utility to clean up common LLM formatting artifacts from a Cypher query.

    Handles:
    - Markdown code blocks (```cypher ... ```)
    - Extra whitespace and formatting
    - Trailing semicolons (removes them - Cypher doesn't use semicolons)
    """
    query = response_text.strip()

    # Remove markdown code blocks
    if query.startswith("```"):
        # Remove opening ```cypher or ```
        query = query[3:]
        if query.startswith("cypher"):
            query = query[6:]
        # Remove closing ```
        if query.endswith("```"):
            query = query[:-3]

    # Remove backticks
    query = query.strip().replace("`", "")

    # Remove 'cypher' keyword if it appears at the start
    if query.lower().startswith("cypher"):
        query = query[6:].strip()

    # IMPORTANT: Remove trailing semicolons - Cypher doesn't use them!
    # The LLM often adds them from SQL/SQL-like training data
    query = query.rstrip(";").strip()

    return query


class CypherGenerator:
    """Generates Cypher queries from natural language."""

    def __init__(self) -> None:
        try:
            # Get active cypher model configuration
            config = settings.active_cypher_config

            # Create provider instance
            provider = get_provider(
                config.provider,
                api_key=config.api_key,
                endpoint=config.endpoint,
                project_id=config.project_id,
                region=config.region,
                provider_type=config.provider_type,
                thinking_budget=config.thinking_budget,
                reasoning_effort=config.reasoning_effort,
            )

            # Create model using provider
            llm = provider.create_model(config.model_id)

            # Select system prompt based on provider
            system_prompt = (
                LOCAL_CYPHER_SYSTEM_PROMPT
                if config.provider == "ollama"
                else CYPHER_SYSTEM_PROMPT
            )

            self.agent = Agent(
                model=llm,
                system_prompt=system_prompt,
                output_type=str,
            )
        except Exception as e:
            raise LLMGenerationError(
                f"Failed to initialize CypherGenerator: {e}"
            ) from e

    async def generate(self, natural_language_query: str) -> str:
        logger.info(
            f"  [CypherGenerator] Generating query for: '{natural_language_query}'"
        )
        try:
            result = await self.agent.run(natural_language_query)
            if (
                not isinstance(result.output, str)
                or "MATCH" not in result.output.upper()
            ):
                raise LLMGenerationError(
                    f"LLM did not generate a valid query. Output: {result.output}"
                )

            query = _clean_cypher_response(result.output)

            # Validate the cleaned query
            query_upper = query.upper().strip()
            if not query_upper.startswith("MATCH"):
                raise LLMGenerationError(
                    f"Generated query doesn't start with MATCH clause: {query}"
                )

            # Warn about common Cypher syntax issues
            if ";" in query:
                logger.warning(
                    f"Query contains semicolons which aren't valid in Cypher. "
                    f"Removing them. Query: {query}"
                )
                query = query.replace(";", "")

            logger.info(f"  [CypherGenerator] Generated Cypher: {query}")
            return query
        except LLMGenerationError:
            raise
        except Exception as e:
            logger.error(f"  [CypherGenerator] Error: {e}")
            raise LLMGenerationError(f"Cypher generation failed: {e}") from e


def create_rag_orchestrator(
    tools: list[Tool], system_prompt: str | None = None
) -> Agent:
    """Factory function to create the main RAG orchestrator agent."""
    try:
        # Get active orchestrator model configuration
        config = settings.active_orchestrator_config

        # Create provider instance
        provider = get_provider(
            config.provider,
            api_key=config.api_key,
            endpoint=config.endpoint,
            project_id=config.project_id,
            region=config.region,
            provider_type=config.provider_type,
            thinking_budget=config.thinking_budget,
            reasoning_effort=config.reasoning_effort,
        )

        # Create model using provider
        llm = provider.create_model(config.model_id)

        return Agent(
            model=llm,
            system_prompt=system_prompt or RAG_ORCHESTRATOR_SYSTEM_PROMPT,
            tools=tools,
        )
    except Exception as e:
        raise LLMGenerationError(f"Failed to initialize RAG Orchestrator: {e}") from e


def create_context_synthesizer() -> Agent:
    """Factory function to create a context-only synthesis agent."""
    try:
        config = settings.active_orchestrator_config
        provider = get_provider(
            config.provider,
            api_key=config.api_key,
            endpoint=config.endpoint,
            project_id=config.project_id,
            region=config.region,
            provider_type=config.provider_type,
            thinking_budget=config.thinking_budget,
            reasoning_effort=config.reasoning_effort,
        )
        llm = provider.create_model(config.model_id)
        return Agent(
            model=llm,
            system_prompt=CONTEXT_SYNTHESIS_PROMPT,
            output_type=str,
        )
    except Exception as e:
        raise LLMGenerationError(
            f"Failed to initialize context synthesizer: {e}"
        ) from e
