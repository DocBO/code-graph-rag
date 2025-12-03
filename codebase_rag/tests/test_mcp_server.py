from __future__ import annotations

import anyio
from mcp.client.session import ClientSession

from codebase_rag.mcp.server import GraphCodeMCPServer


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
        return {"language": language, "response": "Optimization response"}

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


def test_mcp_server_lists_tools_and_invokes_them() -> None:
    context = StubContext()
    server = GraphCodeMCPServer(context)
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
                    "graph_ingest",
                    "graph_query",
                    "optimize_code",
                    "get_status",
                    "ingest_status",
                }.issubset(tool_names)

                ingest_result = await session.call_tool(
                    "graph_ingest",
                    {"repo_path": "/tmp/repo", "clean": True, "batch_size": 5},
                )
                assert not ingest_result.isError
                assert ingest_result.structuredContent["repo_path"] == "/tmp/repo"

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

            tg.cancel_scope.cancel()

    anyio.run(_run, backend="asyncio")

    assert any(call[0] == "ingest" for call in context.calls)
    assert any(call[0] == "query" for call in context.calls)
    assert any(call[0] == "optimize" for call in context.calls)
