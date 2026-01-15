"""Enhanced semantic search tool that combines Qdrant vector search with graph context."""

from typing import Any
from loguru import logger
from pydantic_ai import Tool
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ..config import settings
from ..utils.dependencies import has_semantic_dependencies
from .semantic_search import semantic_code_search


def create_enhanced_semantic_search_tool(repo_path: str | None = None, console: Console | None = None) -> Tool:
    """
    Factory function to create an enhanced semantic search tool that combines
    Qdrant vector search with graph context.
    Stores repo_path in module context for use in nested functions.
    """
    # Store repo_path in semantic_search module context
    from .semantic_search import _repo_path_context as _
    from . import semantic_search as ss_module
    ss_module._repo_path_context = ss_module._normalize_repo_path(repo_path)
    
    if console is None:
        console = Console(width=None, force_terminal=True)

    async def enhanced_semantic_search(query: str, top_k: int = 10) -> str:
        """
        Search the codebase using natural language descriptions, powered by semantic embeddings.
        
        This tool combines:
        1. Qdrant vector database for semantic similarity of code embeddings
        2. Memgraph for detailed node information and relationships
        
        Examples:
        - "Find functions that handle authentication"
        - "Show me error handling code"
        - "Where is configuration loading implemented"
        - "Find functions related to database operations"
        
        Args:
            query: Natural language description of what you're looking for
            top_k: Maximum number of results to return (1-20, default: 10)
            
        Returns:
            Formatted string with semantic search results including node details
        """
        logger.info(f"[Tool:EnhancedSemanticSearch] Searching for: '{query}' (top_k={top_k})")
        
        if not has_semantic_dependencies():
            return (
                "❌ Semantic search is not available.\n\n"
                "This requires:\n"
                "1. External embedder configured (EMBED_ENDPOINT, EMBED_MODEL, EMBED_API_KEY in .env), OR\n"
                "2. Local embedder: pip install '.[semantic]' (requires torch, transformers, qdrant-client)\n\n"
                "To enable:\n"
                "- Update your .env file with embedding API credentials\n"
                "- Run: graph-code start --repo-path /path/to/repo --update-graph\n"
                "  (This will generate embeddings for all functions/methods)"
            )
        
        try:
            # Use async version since we're in an async context
            from .semantic_search import semantic_code_search_async
            results = await semantic_code_search_async(query, top_k)
            
            if not results:
                return (
                    f"❌ No semantic matches found for: '{query}'\n\n"
                    "This could mean:\n"
                    "1. No functions match this description in the codebase\n"
                    "2. Embeddings haven't been generated yet\n\n"
                    "Solution: Run `graph-code start --repo-path /path/to/repo --update-graph` "
                    "to generate embeddings during ingestion."
                )
            
            # Create rich table for display
            table = Table(
                show_header=True,
                header_style="bold cyan",
                title=f"Semantic Search Results for: '{query}'",
            )
            table.add_column("#", style="dim", width=3)
            table.add_column("Qualified Name", style="bold green")
            table.add_column("Type", style="cyan")
            table.add_column("Score", justify="right", style="yellow")
            
            response_lines = [f"Found {len(results)} semantic matches:\n"]
            
            for i, result in enumerate(results, 1):
                table.add_row(
                    str(i),
                    result["qualified_name"],
                    result["type"],
                    f"{result['score']:.3f}"
                )
                response_lines.append(
                    f"{i}. {result['qualified_name']} ({result['type']}) - Score: {result['score']:.3f}"
                )
            
            # Display the table in console
            console.print(Panel(table, border_style="cyan"))
            
            # Return text version for LLM
            response = "\n".join(response_lines)
            response += (
                "\n\nYou can:\n"
                "- Use 'get_source_by_id' with the node ID to view the source code\n"
                "- Use 'query_codebase_knowledge_graph' to find related functions/classes\n"
                "- Ask follow-up questions about these items"
            )
            
            logger.info(f"Found {len(results)} semantic matches")
            return response
            
        except Exception as e:
            logger.error(f"Semantic search failed: {e}")
            return f"❌ Semantic search failed: {str(e)}"
    
    return Tool(
        enhanced_semantic_search,
        name="semantic_search_by_intent",
        description="Search for code by natural language intent using semantic embeddings from Qdrant"
    )
