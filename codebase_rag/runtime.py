"""Shared runtime helpers for initializing Graph-Code services."""

from __future__ import annotations

from typing import Any

from rich.console import Console

from .config import settings
from .prompts import RAG_READ_ONLY_SYSTEM_PROMPT
from .services.graph_service import MemgraphIngestor
from .services.llm import CypherGenerator, create_rag_orchestrator
from .tools.code_retrieval import CodeRetriever, create_code_retrieval_tool
from .tools.codebase_query import create_query_tool
from .tools.directory_lister import DirectoryLister, create_directory_lister_tool
from .tools.document_analyzer import DocumentAnalyzer, create_document_analyzer_tool
from .tools.enhanced_semantic_search import create_enhanced_semantic_search_tool
from .tools.file_editor import FileEditor, create_file_editor_tool
from .tools.file_reader import FileReader, create_file_reader_tool
from .tools.file_writer import FileWriter, create_file_writer_tool
from .tools.semantic_search import (
    create_get_source_tool,
    create_semantic_search_tool,
)
from .tools.shell_command import ShellCommander, create_shell_command_tool


def initialize_services_and_agent(
    repo_path: str,
    ingestor: MemgraphIngestor,
    console: Console | None = None,
    read_only: bool = False,
) -> Any:
    """Initializes all services and creates the RAG agent.

    When ``read_only`` is True, mutation-capable tools (file writer, file
    editor, shell command) are excluded and a read-only system prompt is used.
    """

    from .providers.base import get_provider  # Local import to avoid circular deps

    def _validate_provider_config(role: str, config: Any) -> None:
        """Validate a single provider configuration."""

        provider = get_provider(
            config.provider,
            api_key=config.api_key,
            endpoint=config.endpoint,
            project_id=config.project_id,
            region=config.region,
            provider_type=config.provider_type,
            thinking_budget=config.thinking_budget,
            service_account_file=config.service_account_file,
        )
        provider.validate_config()

    _validate_provider_config("orchestrator", settings.active_orchestrator_config)
    _validate_provider_config("cypher", settings.active_cypher_config)

    cypher_generator = CypherGenerator()
    code_retriever = CodeRetriever(project_root=repo_path, ingestor=ingestor)
    file_reader = FileReader(project_root=repo_path)
    file_writer = FileWriter(project_root=repo_path)
    file_editor = FileEditor(project_root=repo_path)
    shell_commander = ShellCommander(
        project_root=repo_path, timeout=settings.SHELL_COMMAND_TIMEOUT
    )
    directory_lister = DirectoryLister(project_root=repo_path)
    document_analyzer = DocumentAnalyzer(project_root=repo_path)

    query_tool = create_query_tool(ingestor, cypher_generator, console)
    code_tool = create_code_retrieval_tool(code_retriever)
    file_reader_tool = create_file_reader_tool(file_reader)
    directory_lister_tool = create_directory_lister_tool(directory_lister)
    document_analyzer_tool = create_document_analyzer_tool(document_analyzer)
    semantic_search_tool = create_semantic_search_tool(repo_path=repo_path)
    enhanced_semantic_search_tool = create_enhanced_semantic_search_tool(repo_path=repo_path, console=console)
    get_source_tool = create_get_source_tool(repo_path=repo_path)

    if read_only:
        tools = [
            query_tool,
            code_tool,
            file_reader_tool,
            directory_lister_tool,
            document_analyzer_tool,
            semantic_search_tool,
            enhanced_semantic_search_tool,
            get_source_tool,
        ]
        rag_agent = create_rag_orchestrator(
            tools=tools, system_prompt=RAG_READ_ONLY_SYSTEM_PROMPT
        )
        return rag_agent

    file_writer_tool = create_file_writer_tool(file_writer)
    file_editor_tool = create_file_editor_tool(file_editor)
    shell_command_tool = create_shell_command_tool(shell_commander)

    rag_agent = create_rag_orchestrator(
        tools=[
            query_tool,
            code_tool,
            file_reader_tool,
            file_writer_tool,
            file_editor_tool,
            shell_command_tool,
            directory_lister_tool,
            document_analyzer_tool,
            semantic_search_tool,
            enhanced_semantic_search_tool,
            get_source_tool,
        ]
    )
    return rag_agent
