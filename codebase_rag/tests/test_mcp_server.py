from __future__ import annotations

from pathlib import Path
from typing import cast

import anyio
import pytest
from mcp.client.session import ClientSession
from pydantic_ai.messages import ModelRequest, ToolCallPart, ToolReturnPart

from codebase_rag.mcp.server import (
    GraphCodeMCPContext,
    GraphCodeMCPServer,
    _extract_retrieval_metadata,
)
from codebase_rag.schemas import CodeSnippet, GraphData


class StubContext:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def run_ingest(
        self,
        repo_path: str | None = None,
        clean: bool = False,
        batch_size: int | None = None,
    ) -> dict[str, object]:
        payload = {
            "repo_path": repo_path or "/workspace",
            "clean": clean,
            "batch_size": batch_size or 1000,
        }
        self.calls.append(("ingest", payload))
        return {
            "repo_path": payload["repo_path"],
            "cleaned": clean,
            "batch_size": payload["batch_size"],
            "duration_ms": 5.0,
        }

    async def run_query(
        self, question: str, repo_path: str | None = None
    ) -> dict[str, object]:
        self.calls.append(("query", {"question": question, "repo_path": repo_path}))
        return {
            "repo_path": repo_path or "/workspace",
            "question": question,
            "cypher": "MATCH (n) RETURN n",
            "results": [{"name": "Example"}],
        }

    async def optimize_code(
        self,
        language: str,
        instruction: str | None = None,
        reference_document: str | None = None,
        repo_path: str | None = None,
    ) -> dict[str, object]:
        self.calls.append(
            (
                "optimize",
                {
                    "language": language,
                    "instruction": instruction,
                    "ref": reference_document,
                    "repo_path": repo_path,
                },
            )
        )
        return {
            "repo_path": repo_path or "/workspace",
            "language": language,
            "response": "Optimization response",
        }

    async def get_status(self) -> dict[str, object]:
        return {
            "repo_path": "/workspace",
            "batch_size": 1000,
            "memgraph": {"host": "localhost", "port": 7687},
            "orchestrator": {"provider": "ollama", "model": "llama3.2"},
            "cypher": {"provider": "ollama", "model": "codellama"},
        }

    async def get_ingest_status(
        self, repo_path: str | None = None
    ) -> dict[str, object]:
        return {
            "repo_path": repo_path or "/workspace",
            "last_ingest": "2025-11-15T12:00:00Z",
            "changes": {"added": 1, "deleted": 0, "modified": 0, "total": 1},
            "metadata_path": "/workspace/.graphcode_ingest.json",
        }

    async def start_updater(
        self,
        repo_path: str | None = None,
        force: bool = False,
    ) -> dict[str, object]:
        self.calls.append(("start_updater", {"repo_path": repo_path, "force": force}))
        return {
            "repo_path": repo_path or "/workspace",
            "started": True,
            "reason": "stale" if force else "index_fresh",
            "last_ingest": "2025-11-15T12:00:00Z",
            "changes": {"added": 1, "deleted": 0, "modified": 0, "total": 1},
            "metadata_path": "/workspace/.graphcode_ingest.json",
        }

    async def query_codebase(
        self,
        question: str,
        repo_path: str | None = None,
        search_depth: str = "normal",
    ) -> dict[str, object]:
        self.calls.append(
            (
                "query_codebase",
                {
                    "question": question,
                    "repo_path": repo_path,
                    "search_depth": search_depth,
                },
            )
        )
        return {
            "repo_path": repo_path or "/workspace",
            "question": question,
            "search_depth": search_depth,
            "response": "Standard agent response",
            "sources": [],
            "retrieval": {
                "used_graph": False,
                "used_semantic_search": False,
                "index_status": "fresh",
            },
        }

    async def quick_semantic_retrieval(
        self,
        search_phrase: str,
        top_n: int = 5,
        repo_path: str | None = None,
    ) -> dict[str, object]:
        self.calls.append(
            (
                "quick_semantic_retrieval",
                {
                    "search_phrase": search_phrase,
                    "top_n": top_n,
                    "repo_path": repo_path,
                },
            )
        )
        return {
            "repo_path": repo_path or "/workspace",
            "search_phrase": search_phrase,
            "top_n": top_n,
            "matches": [
                {
                    "qualified_name": "pkg.auth.login",
                    "type": "Function",
                    "score": 0.91,
                    "filename": "src/auth.py",
                    "start_line": 10,
                    "end_line": 22,
                    "snippet": "def login(user): ...",
                }
            ],
        }


def test_mcp_server_lists_tools_and_invokes_them() -> None:
    context = StubContext()
    server = GraphCodeMCPServer(
        cast(GraphCodeMCPContext, context), expose_internal_tools=True
    )
    init_options = server.server.create_initialization_options()

    async def _run() -> None:
        client_to_server_send, client_to_server_recv = (
            anyio.create_memory_object_stream(0)
        )
        server_to_client_send, server_to_client_recv = (
            anyio.create_memory_object_stream(0)
        )

        async with anyio.create_task_group() as tg:
            tg.start_soon(
                server.server.run,
                client_to_server_recv,
                server_to_client_send,
                init_options,
                True,
            )

            async with ClientSession(
                server_to_client_recv, client_to_server_send
            ) as session:
                await session.initialize()
                tools_result = await session.list_tools()
                tool_names = {tool.name for tool in tools_result.tools}
                assert {
                    "graph_query",
                    "optimize_code",
                    "get_status",
                    "ingest_status",
                    "query_codebase",
                    "query_codegraph",
                    "quick_semantic_retrieval",
                    "start_updater",
                }.issubset(tool_names)

                query_codebase_tool = next(
                    tool for tool in tools_result.tools if tool.name == "query_codebase"
                )
                assert query_codebase_tool.inputSchema["required"] == ["question"]
                assert set(query_codebase_tool.inputSchema["properties"]) == {
                    "question",
                    "search_depth",
                    "repo_path",
                }
                assert set(query_codebase_tool.outputSchema["properties"]) == {
                    "repo_path",
                    "question",
                    "search_depth",
                    "response",
                    "sources",
                    "retrieval",
                }

                quick_semantic_tool = next(
                    tool
                    for tool in tools_result.tools
                    if tool.name == "quick_semantic_retrieval"
                )
                assert quick_semantic_tool.inputSchema["required"] == ["search_phrase"]
                assert set(quick_semantic_tool.inputSchema["properties"]) == {
                    "search_phrase",
                    "top_n",
                    "repo_path",
                }

                start_updater_tool = next(
                    tool for tool in tools_result.tools if tool.name == "start_updater"
                )
                assert set(start_updater_tool.inputSchema["properties"]) == {
                    "repo_path",
                    "force",
                }
                assert set(start_updater_tool.outputSchema["properties"]) == {
                    "repo_path",
                    "started",
                    "reason",
                    "last_ingest",
                    "changes",
                    "metadata_path",
                }

                query_result = await session.call_tool(
                    "graph_query", {"question": "List modules"}
                )
                assert query_result.structuredContent["cypher"] == "MATCH (n) RETURN n"

                optimize_result = await session.call_tool(
                    "optimize_code", {"language": "python"}
                )
                assert optimize_result.structuredContent["language"] == "python"

                ingest_status_result = await session.call_tool("ingest_status", {})
                assert (
                    ingest_status_result.structuredContent["last_ingest"]
                    == "2025-11-15T12:00:00Z"
                )

                start_updater_result = await session.call_tool(
                    "start_updater", {"force": True}
                )
                assert not start_updater_result.isError
                assert start_updater_result.structuredContent["started"] is True
                assert start_updater_result.structuredContent["reason"] == "stale"

                codebase_result = await session.call_tool(
                    "query_codebase",
                    {"question": "How is the frontend rendered?"},
                )
                assert not codebase_result.isError
                assert codebase_result.structuredContent == {
                    "repo_path": "/workspace",
                    "question": "How is the frontend rendered?",
                    "search_depth": "normal",
                    "response": "Standard agent response",
                    "sources": [],
                    "retrieval": {
                        "used_graph": False,
                        "used_semantic_search": False,
                        "index_status": "fresh",
                    },
                }

                removed_strategy_result = await session.call_tool(
                    "query_codebase",
                    {
                        "question": "How is the frontend rendered?",
                        "strategy": "semantic-seed-strategy",
                    },
                )
                assert removed_strategy_result.isError

                deep_codebase_result = await session.call_tool(
                    "query_codebase",
                    {
                        "question": "Trace startup flow",
                        "search_depth": "deep",
                    },
                )
                assert not deep_codebase_result.isError
                assert deep_codebase_result.structuredContent["search_depth"] == "deep"

                alias_result = await session.call_tool(
                    "query_codegraph",
                    {
                        "question": "Trace startup flow",
                        "search_depth": "shallow",
                    },
                )
                assert not alias_result.isError
                assert alias_result.structuredContent["search_depth"] == "shallow"

                quick_semantic_result = await session.call_tool(
                    "quick_semantic_retrieval",
                    {
                        "search_phrase": "login handler",
                        "top_n": 3,
                    },
                )
                assert not quick_semantic_result.isError
                assert (
                    quick_semantic_result.structuredContent["search_phrase"]
                    == "login handler"
                )
                assert quick_semantic_result.structuredContent["top_n"] == 3
                assert (
                    quick_semantic_result.structuredContent["repo_path"] == "/workspace"
                )
                assert (
                    quick_semantic_result.structuredContent["matches"][0]["filename"]
                    == "src/auth.py"
                )

                quick_semantic_with_repo_result = await session.call_tool(
                    "quick_semantic_retrieval",
                    {
                        "search_phrase": "login handler",
                        "top_n": 2,
                        "repo_path": "/workspace/alt",
                    },
                )
                assert not quick_semantic_with_repo_result.isError
                assert (
                    quick_semantic_with_repo_result.structuredContent["repo_path"]
                    == "/workspace/alt"
                )

            tg.cancel_scope.cancel()

    anyio.run(_run, backend="asyncio")

    assert any(call[0] == "query" for call in context.calls)
    assert any(call[0] == "optimize" for call in context.calls)
    assert (
        "query_codebase",
        {
            "question": "How is the frontend rendered?",
            "repo_path": None,
            "search_depth": "normal",
        },
    ) in context.calls
    assert (
        "query_codebase",
        {
            "question": "Trace startup flow",
            "repo_path": None,
            "search_depth": "deep",
        },
    ) in context.calls
    assert (
        "quick_semantic_retrieval",
        {"search_phrase": "login handler", "top_n": 3, "repo_path": None},
    ) in context.calls
    assert (
        "quick_semantic_retrieval",
        {
            "search_phrase": "login handler",
            "top_n": 2,
            "repo_path": "/workspace/alt",
        },
    ) in context.calls
    assert ("start_updater", {"repo_path": None, "force": True}) in context.calls


@pytest.mark.asyncio
async def test_mcp_context_query_uses_standard_agent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}

    class DummyIngestor:
        def __init__(self, **kwargs: object) -> None:
            captured["ingestor_kwargs"] = kwargs

        def __enter__(self) -> DummyIngestor:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    class DummyAgent:
        async def run(self, prompt: str) -> object:
            captured["prompt"] = prompt

            class Result:
                output = "Standard answer"

                def all_messages(self) -> list[object]:
                    return []

            return Result()

    def fake_initialize(
        repo_path: str, ingestor: DummyIngestor, read_only: bool = False
    ) -> DummyAgent:
        captured["repo_path"] = repo_path
        captured["ingestor"] = ingestor
        captured["read_only"] = read_only
        return DummyAgent()

    monkeypatch.setattr("codebase_rag.mcp.server.MemgraphIngestor", DummyIngestor)
    monkeypatch.setattr(
        "codebase_rag.mcp.server.summarize_ingest_status",
        lambda repo: (
            "2025-11-15T12:00:00Z",
            {"added": 0, "deleted": 0, "modified": 0, "total": 0},
            None,
        ),
    )
    monkeypatch.setattr(
        "codebase_rag.mcp.server.initialize_services_and_agent",
        fake_initialize,
    )

    context = GraphCodeMCPContext(str(tmp_path), batch_size=25)
    result = await context.query_codebase(
        "Explain the checkout frontend", search_depth="deep"
    )

    assert "SEARCH DEPTH MODE: DEEP" in str(captured["prompt"])
    assert "Explain the checkout frontend" in str(captured["prompt"])
    assert captured["repo_path"] == str(tmp_path.resolve())
    assert captured["read_only"] is True
    assert result["repo_path"] == str(tmp_path.resolve())
    assert result["question"] == "Explain the checkout frontend"
    assert result["search_depth"] == "deep"
    assert result["response"] == "Standard answer"
    assert result["sources"] == []
    assert result["retrieval"] == {
        "used_graph": False,
        "used_semantic_search": False,
        "index_status": "fresh",
    }


@pytest.mark.asyncio
async def test_mcp_context_query_rejects_invalid_search_depth(
    tmp_path: Path,
) -> None:
    context = GraphCodeMCPContext(str(tmp_path), batch_size=25)

    with pytest.raises(ValueError, match="search_depth must be one of"):
        await context.query_codebase("Explain config loading", search_depth="ultra")


@pytest.mark.asyncio
async def test_mcp_context_quick_semantic_retrieval(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}

    def fake_execute_read_query(
        host: str, port: int, query: str, params: dict[str, object] | None = None
    ) -> list[dict[str, object]]:
        captured["location_host"] = host
        captured["location_port"] = port
        captured["location_query"] = query
        captured["location_params"] = params
        return [
            {
                "filename": "src/auth.py",
                "start_line": 10,
                "end_line": 22,
            }
        ]

    async def fake_semantic_code_search_async(
        query: str, top_k: int = 5, repo_path: str | None = None
    ) -> list[dict[str, object]]:
        captured["semantic_query"] = query
        captured["semantic_top_k"] = top_k
        captured["semantic_repo_path"] = repo_path
        return [
            {
                "node_id": 42,
                "qualified_name": "pkg.auth.login",
                "type": "Function",
                "score": 0.91,
                "matched_chunk_qualified_name": "pkg.auth.login_chunk_1",
                "chunk_text": "chunk-only snippet",
            }
        ]

    def fake_get_function_source_code(
        node_id: int, repo_path: str | None = None
    ) -> str:
        captured["source_node_id"] = node_id
        captured["source_repo_path"] = repo_path
        return "def login(user): ..."

    monkeypatch.setattr(
        "codebase_rag.mcp.server.semantic_code_search_async",
        fake_semantic_code_search_async,
    )
    monkeypatch.setattr(
        "codebase_rag.mcp.server.get_function_source_code",
        fake_get_function_source_code,
    )
    monkeypatch.setattr(
        "codebase_rag.services.graph_service.execute_read_query",
        fake_execute_read_query,
    )

    context = GraphCodeMCPContext(str(tmp_path), batch_size=25)
    result = await context.quick_semantic_retrieval("login handler", top_n=3)

    assert captured["semantic_query"] == "login handler"
    assert captured["semantic_top_k"] == 3
    assert captured["semantic_repo_path"] == str(tmp_path.resolve())
    assert result["search_phrase"] == "login handler"
    assert result["top_n"] == 3
    assert result["repo_path"] == str(tmp_path.resolve())
    assert len(result["matches"]) == 1
    assert result["matches"][0]["filename"] == "src/auth.py"
    assert result["matches"][0]["start_line"] == 10
    assert result["matches"][0]["snippet"] == "chunk-only snippet"
    assert "source_node_id" not in captured


@pytest.mark.asyncio
async def test_mcp_context_start_updater_skips_fresh_index(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}

    def fake_summarize_ingest_status(
        repo_path: Path,
    ) -> tuple[str | None, dict[str, int], Path]:
        captured["summary_repo"] = repo_path
        return (
            "2025-11-15T12:00:00Z",
            {"added": 0, "deleted": 0, "modified": 0, "total": 0},
            repo_path / ".graphcode_ingest.json",
        )

    monkeypatch.setattr(
        "codebase_rag.mcp.server.summarize_ingest_status",
        fake_summarize_ingest_status,
    )

    context = GraphCodeMCPContext(str(tmp_path), batch_size=25)
    result = await context.start_updater()

    assert result["started"] is False
    assert result["reason"] == "index_fresh"


@pytest.mark.asyncio
async def test_mcp_context_start_updater_runs_when_stale(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}

    def fake_summarize_ingest_status(
        repo_path: Path,
    ) -> tuple[str | None, dict[str, int], Path]:
        captured["summary_repo"] = repo_path
        return (
            "2025-11-15T12:00:00Z",
            {"added": 2, "deleted": 0, "modified": 1, "total": 3},
            repo_path / ".graphcode_ingest.json",
        )

    class DummyIngestor:
        def __init__(self, **kwargs: object) -> None:
            captured["ingestor_kwargs"] = kwargs

        def __enter__(self) -> DummyIngestor:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def ensure_constraints(self) -> None:
            captured["ensure_constraints"] = True

    class DummyUpdater:
        def __init__(self, *args: object, **kwargs: object) -> None:
            captured["updater_args"] = (args, kwargs)

        def run(self) -> None:
            captured["updater_run"] = True

    def fake_write_metadata(repo_path: Path) -> object:
        captured["metadata_repo"] = repo_path
        return object()

    monkeypatch.setattr(
        "codebase_rag.mcp.server.summarize_ingest_status",
        fake_summarize_ingest_status,
    )
    monkeypatch.setattr("codebase_rag.mcp.server.MemgraphIngestor", DummyIngestor)
    monkeypatch.setattr("codebase_rag.mcp.server.GraphUpdater", DummyUpdater)
    monkeypatch.setattr(
        "codebase_rag.mcp.server.write_ingest_metadata", fake_write_metadata
    )

    context = GraphCodeMCPContext(str(tmp_path), batch_size=25)
    result = await context.start_updater()

    assert result["started"] is True
    assert result["reason"] == "stale"
    assert captured["updater_run"] is True
    assert captured["metadata_repo"] == tmp_path.resolve()


def test_extract_retrieval_metadata_collects_usage_and_sources() -> None:
    request = ModelRequest(
        parts=[
            ToolCallPart(tool_name="query_codebase_knowledge_graph", args="x"),
            ToolReturnPart(
                tool_name="query_codebase_knowledge_graph",
                tool_call_id="1",
                content=GraphData(
                    query_used="MATCH (n) RETURN n",
                    results=[
                        {
                            "qualified_name": "pkg.auth.login",
                            "path": "src/auth.py",
                            "name": "login",
                        },
                        {
                            "qualified_name": "pkg.auth.login",
                            "path": "src/auth.py",
                            "name": "login",
                        },
                        {"name": "orphan", "path": "src/other.py"},
                    ],
                    summary="ok",
                ),
            ),
            ToolCallPart(tool_name="semantic_search_functions", args="y"),
            ToolReturnPart(
                tool_name="semantic_search_functions",
                tool_call_id="2",
                content="Found 1 semantic match",
            ),
            ToolCallPart(tool_name="get_code_snippet", args="z"),
            ToolReturnPart(
                tool_name="get_code_snippet",
                tool_call_id="3",
                content=CodeSnippet(
                    qualified_name="pkg.auth.logout",
                    source_code="def logout(): ...",
                    file_path="src/auth.py",
                    line_start=30,
                    line_end=41,
                ),
            ),
        ]
    )

    result = _extract_retrieval_metadata([request])

    assert result["used_graph"] is True
    assert result["used_semantic_search"] is True
    assert result["sources"] == [
        {
            "qualified_name": "pkg.auth.login",
            "filename": "src/auth.py",
            "start_line": None,
            "end_line": None,
        },
        {
            "qualified_name": "orphan",
            "filename": "src/other.py",
            "start_line": None,
            "end_line": None,
        },
        {
            "qualified_name": "pkg.auth.logout",
            "filename": "src/auth.py",
            "start_line": 30,
            "end_line": 41,
        },
    ]


def test_extract_retrieval_metadata_empty_messages() -> None:
    result = _extract_retrieval_metadata([])
    assert result == {
        "used_graph": False,
        "used_semantic_search": False,
        "sources": [],
    }

