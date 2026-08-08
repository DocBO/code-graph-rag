from __future__ import annotations

from pathlib import Path
from typing import cast

import anyio
import pytest
from mcp.client.session import ClientSession

from codebase_rag.mcp.server import GraphCodeMCPContext, GraphCodeMCPServer


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

    async def run_query(self, question: str) -> dict[str, object]:
        self.calls.append(("query", {"question": question}))
        return {
            "repo_path": "/workspace",
            "question": question,
            "cypher": "MATCH (n) RETURN n",
            "results": [{"name": "Example"}],
        }

    async def optimize_code(
        self,
        language: str,
        instruction: str | None = None,
        reference_document: str | None = None,
    ) -> dict[str, object]:
        self.calls.append(
            (
                "optimize",
                {
                    "language": language,
                    "instruction": instruction,
                    "ref": reference_document,
                },
            )
        )
        return {
            "repo_path": "/workspace",
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

    async def query_codebase(self, question: str) -> dict[str, object]:
        self.calls.append(("query_codebase", {"question": question}))
        return {
            "repo_path": "/workspace",
            "question": question,
            "response": "Standard agent response",
        }

    async def quick_semantic_retrieval(
        self, search_phrase: str, top_n: int = 5
    ) -> dict[str, object]:
        self.calls.append(
            (
                "quick_semantic_retrieval",
                {"search_phrase": search_phrase, "top_n": top_n},
            )
        )
        return {
            "repo_path": "/workspace",
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
                    "quick_semantic_retrieval",
                }.issubset(tool_names)

                query_codebase_tool = next(
                    tool
                    for tool in tools_result.tools
                    if tool.name == "query_codebase"
                )
                assert query_codebase_tool.inputSchema["required"] == ["question"]
                assert set(query_codebase_tool.inputSchema["properties"]) == {
                    "question"
                }
                assert set(query_codebase_tool.outputSchema["properties"]) == {
                    "repo_path",
                    "question",
                    "response",
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

                codebase_result = await session.call_tool(
                    "query_codebase",
                    {"question": "How is the frontend rendered?"},
                )
                assert not codebase_result.isError
                assert codebase_result.structuredContent == {
                    "repo_path": "/workspace",
                    "question": "How is the frontend rendered?",
                    "response": "Standard agent response",
                }

                removed_strategy_result = await session.call_tool(
                    "query_codebase",
                    {
                        "question": "How is the frontend rendered?",
                        "strategy": "semantic-seed-strategy",
                    },
                )
                assert removed_strategy_result.isError

                quick_semantic_result = await session.call_tool(
                    "quick_semantic_retrieval",
                    {
                        "search_phrase": "login handler",
                        "top_n": 3,
                    },
                )
                assert not quick_semantic_result.isError
                assert quick_semantic_result.structuredContent["search_phrase"] == "login handler"
                assert quick_semantic_result.structuredContent["top_n"] == 3
                assert quick_semantic_result.structuredContent["repo_path"] == "/workspace"
                assert quick_semantic_result.structuredContent["matches"][0]["filename"] == "src/auth.py"

            tg.cancel_scope.cancel()

    anyio.run(_run, backend="asyncio")

    assert any(call[0] == "query" for call in context.calls)
    assert any(call[0] == "optimize" for call in context.calls)
    assert (
        "query_codebase",
        {"question": "How is the frontend rendered?"},
    ) in context.calls
    assert (
        "quick_semantic_retrieval",
        {"search_phrase": "login handler", "top_n": 3},
    ) in context.calls


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

            return Result()

    def fake_initialize(
        repo_path: str, ingestor: DummyIngestor
    ) -> DummyAgent:
        captured["repo_path"] = repo_path
        captured["ingestor"] = ingestor
        return DummyAgent()

    monkeypatch.setattr(
        "codebase_rag.mcp.server.MemgraphIngestor", DummyIngestor
    )
    monkeypatch.setattr(
        "codebase_rag.mcp.server.initialize_services_and_agent",
        fake_initialize,
    )

    context = GraphCodeMCPContext(str(tmp_path), batch_size=25)
    result = await context.query_codebase("Explain the checkout frontend")

    assert captured["prompt"] == "Explain the checkout frontend"
    assert captured["repo_path"] == str(tmp_path.resolve())
    assert result == {
        "repo_path": str(tmp_path.resolve()),
        "question": "Explain the checkout frontend",
        "response": "Standard answer",
    }


@pytest.mark.asyncio
async def test_mcp_context_quick_semantic_retrieval(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}

    class DummyIngestor:
        def __init__(self, **kwargs: object) -> None:
            captured["ingestor_kwargs"] = kwargs

        def __enter__(self) -> "DummyIngestor":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def fetch_all(self, query: str, params: dict[str, object]) -> list[dict[str, object]]:
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
        "codebase_rag.mcp.server.MemgraphIngestor", DummyIngestor
    )
    monkeypatch.setattr(
        "codebase_rag.mcp.server.semantic_code_search_async",
        fake_semantic_code_search_async,
    )
    monkeypatch.setattr(
        "codebase_rag.mcp.server.get_function_source_code",
        fake_get_function_source_code,
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
