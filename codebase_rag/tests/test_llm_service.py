from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from codebase_rag.services.llm import (
    LLMGenerationError,
    _clean_cypher_response,
    create_context_synthesizer,
    create_rag_orchestrator,
)


class TestCleanCypherResponse:
    def test_removes_markdown_fence(self) -> None:
        result = _clean_cypher_response("```cypher\nMATCH (n) RETURN n\n```")
        assert result == "MATCH (n) RETURN n"

    def test_removes_markdown_without_language(self) -> None:
        result = _clean_cypher_response("```\nMATCH (n) RETURN n\n```")
        assert result == "MATCH (n) RETURN n"

    def test_removes_trailing_semicolon(self) -> None:
        result = _clean_cypher_response("MATCH (n) RETURN n;")
        assert result == "MATCH (n) RETURN n"

    def test_removes_multiple_semicolons(self) -> None:
        result = _clean_cypher_response("MATCH (n) RETURN n;;")
        assert result == "MATCH (n) RETURN n"

    def test_removes_cypher_keyword_prefix(self) -> None:
        result = _clean_cypher_response("cypher MATCH (n) RETURN n")
        assert result == "MATCH (n) RETURN n"

    def test_removes_backticks(self) -> None:
        result = _clean_cypher_response("`MATCH (n) RETURN n`")
        assert result == "MATCH (n) RETURN n"

    def test_strips_whitespace(self) -> None:
        result = _clean_cypher_response("  \n  MATCH (n) RETURN n  \n  ")
        assert result == "MATCH (n) RETURN n"

    def test_handles_empty_string(self) -> None:
        result = _clean_cypher_response("")
        assert result == ""


class TestLLMGenerationError:
    def test_can_be_raised_and_caught(self) -> None:
        with pytest.raises(LLMGenerationError, match="test error"):
            raise LLMGenerationError("test error")


class TestCreateRagOrchestrator:
    @pytest.mark.skip(reason="requires active Memgraph + LLM")
    def test_integration_creates_agent(self) -> None:
        from pydantic_ai import Tool

        def dummy_tool() -> str:
            return "ok"

        agent = create_rag_orchestrator([Tool(dummy_tool)])
        assert agent is not None


class TestCreateContextSynthesizer:
    def test_returns_agent_on_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from codebase_rag.config import AppConfig, ModelConfig

        mock_config = AppConfig(_env_file=None)
        mock_config._active_orchestrator = ModelConfig(
            provider="ollama",
            model_id="llama3.2",
            api_key="ollama",
            endpoint="http://localhost:11434/v1",
        )

        monkeypatch.setattr("codebase_rag.services.llm.settings", mock_config)

        mock_provider = MagicMock()
        mock_provider.create_model.return_value = "fake-llm-model"

        monkeypatch.setattr(
            "codebase_rag.services.llm.get_provider",
            lambda *args, **kwargs: mock_provider,
        )

        monkeypatch.setattr(
            "pydantic_ai.Agent.__init__",
            lambda self, model, system_prompt, output_type=None, tools=None, **kw: None,
        )

        agent = create_context_synthesizer()
        assert agent is not None
