from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from codebase_rag.runtime import initialize_services_and_agent


@pytest.fixture
def mock_factories(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Patch all tool factories and the orchestrator factory.

    Returns a list recording the factory names that were called.
    """
    called: list[str] = []

    def _record(name: str):
        def factory(*args, **kwargs):
            called.append(name)
            return MagicMock()

        return factory

    monkeypatch.setattr("codebase_rag.runtime.CypherGenerator", MagicMock)
    mock_provider = MagicMock()
    monkeypatch.setattr(
        "codebase_rag.providers.base.get_provider",
        lambda *a, **kw: mock_provider,
    )
    for name in [
        "create_query_tool",
        "create_code_retrieval_tool",
        "create_file_reader_tool",
        "create_file_writer_tool",
        "create_file_editor_tool",
        "create_shell_command_tool",
        "create_directory_lister_tool",
        "create_document_analyzer_tool",
        "create_semantic_search_tool",
        "create_enhanced_semantic_search_tool",
        "create_get_source_tool",
    ]:
        monkeypatch.setattr(f"codebase_rag.runtime.{name}", _record(name))

    captured: dict[str, object] = {}

    def fake_orchestrator(tools: list[object], system_prompt: str | None = None):
        captured["tools"] = tools
        captured["system_prompt"] = system_prompt
        return MagicMock()

    monkeypatch.setattr(
        "codebase_rag.runtime.create_rag_orchestrator", fake_orchestrator
    )

    mock_settings = MagicMock()
    mock_settings.active_orchestrator_config = MagicMock(
        provider="ollama", api_key="x", endpoint="http://localhost:11434"
    )
    mock_settings.active_cypher_config = MagicMock(
        provider="ollama", api_key="x", endpoint="http://localhost:11434"
    )
    mock_settings.SHELL_COMMAND_TIMEOUT = 30
    monkeypatch.setattr("codebase_rag.runtime.settings", mock_settings)

    mock_factories.called = called  # type: ignore[attr-defined]
    mock_factories.captured = captured  # type: ignore[attr-defined]
    return mock_factories  # type: ignore[return-value]


def test_read_only_agent_excludes_mutation_tools(
    mock_factories: pytest.FixtureRequest,
) -> None:
    ingestor = MagicMock()
    initialize_services_and_agent("/tmp/repo", ingestor, read_only=True)

    called = mock_factories.called  # type: ignore[attr-defined]
    assert "create_file_writer_tool" not in called
    assert "create_file_editor_tool" not in called
    assert "create_shell_command_tool" not in called

    tools = mock_factories.captured["tools"]  # type: ignore[attr-defined]
    assert len(tools) == 8
    assert "READ-ONLY" in str(
        mock_factories.captured["system_prompt"]  # type: ignore[attr-defined]
    )


def test_full_agent_includes_mutation_tools(
    mock_factories: pytest.FixtureRequest,
) -> None:
    ingestor = MagicMock()
    initialize_services_and_agent("/tmp/repo", ingestor, read_only=False)

    called = mock_factories.called  # type: ignore[attr-defined]
    assert "create_file_writer_tool" in called
    assert "create_file_editor_tool" in called
    assert "create_shell_command_tool" in called

    tools = mock_factories.captured["tools"]  # type: ignore[attr-defined]
    assert len(tools) == 11
