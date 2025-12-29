"""Model Context Protocol (MCP) server wiring for Graph-Code."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import anyio
from loguru import logger
from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import PlainTextResponse
from starlette.routing import Mount

from ..config import settings
from ..graph_updater import GraphUpdater
from ..ingest_metadata import summarize_ingest_status, write_ingest_metadata
from ..parser_loader import load_parsers
from ..runtime import initialize_services_and_agent
from ..services.graph_service import MemgraphIngestor
from ..services.llm import CypherGenerator


class TransportLoggingMiddleware:
    """Tiny middleware to log incoming HTTP requests to the MCP endpoint."""

    def __init__(self, app: Any):
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") == "http":
            logger.info("[MCP HTTP] %s %s", scope.get("method"), scope.get("path"))
        await self.app(scope, receive, send)


def _build_tool_schema(name: str) -> dict[str, Any]:
    """Return JSON schema definitions for supported tools."""

    match name:
        case "graph_ingest":
            return {
                "type": "object",
                "properties": {
                    "repo_path": {
                        "type": "string",
                        "description": "Optional override for the repository path to ingest.",
                    },
                    "clean": {
                        "type": "boolean",
                        "description": "Drop existing nodes and relationships before ingesting.",
                        "default": False,
                    },
                    "batch_size": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "Override Memgraph batch size for this operation.",
                    },
                },
                "additionalProperties": False,
            }
        case "graph_query":
            return {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "Natural language question to transform into a Cypher query.",
                    }
                },
                "required": ["question"],
                "additionalProperties": False,
            }
        case "optimize_code":
            return {
                "type": "object",
                "properties": {
                    "language": {
                        "type": "string",
                        "description": "Language focus for the optimization prompt (e.g., python, java).",
                    },
                    "instruction": {
                        "type": "string",
                        "description": "Optional custom instruction prompt sent to the RAG optimizer.",
                    },
                    "reference_document": {
                        "type": "string",
                        "description": "Optional path to a reference document for best practices.",
                    },
                },
                "required": ["language"],
                "additionalProperties": False,
            }
        case "get_status":
            return {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            }
        case "ingest_status":
            return {
                "type": "object",
                "properties": {
                    "repo_path": {
                        "type": "string",
                        "description": "Optional override for the repository path to check status for.",
                    },
                },
                "additionalProperties": False,
            }
        case "query_codebase":
            return {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "Natural language question about the codebase.",
                    },
                    "strategy": {
                        "type": "string",
                        "description": "RAG strategy. Defaults to semantic-seed-strategy.",
                    },
                },
                "required": ["question"],
                "additionalProperties": False,
            }
        case _:
            return {"type": "object", "properties": {}, "additionalProperties": True}


class GraphCodeMCPContext:
    """State holder for MCP tool implementations."""

    def __init__(self, repo_path: str, batch_size: int) -> None:
        self.default_repo = Path(repo_path).resolve()
        self.batch_size = batch_size
        self._parsers: dict[str, Any] | None = None
        self._queries: dict[str, Any] | None = None
        self._cypher_generator: CypherGenerator | None = None

    def _resolve_repo(self, override: str | None) -> Path:
        return Path(override).expanduser().resolve() if override else self.default_repo

    def _ensure_parsers(self) -> tuple[dict[str, Any], dict[str, Any]]:
        if self._parsers is None or self._queries is None:
            logger.info("Loading Tree-sitter parsers for MCP ingest tool")
            self._parsers, self._queries = load_parsers()
        return self._parsers, self._queries

    def _ensure_cypher_generator(self) -> CypherGenerator:
        if self._cypher_generator is None:
            self._cypher_generator = CypherGenerator()
        return self._cypher_generator

    def _resolve_batch_size(self, override: int | None) -> int:
        if override is not None and override >= 1:
            return override
        return self.batch_size

    async def run_ingest(
        self,
        repo_path: str | None = None,
        clean: bool = False,
        batch_size: int | None = None,
    ) -> dict[str, Any]:
        """Update the knowledge graph for the requested repository."""

        target_repo = self._resolve_repo(repo_path)
        effective_batch = self._resolve_batch_size(batch_size)
        parsers, queries = self._ensure_parsers()

        def _task() -> dict[str, Any]:
            start = time.perf_counter()
            with MemgraphIngestor(
                host=settings.MEMGRAPH_HOST,
                port=settings.MEMGRAPH_PORT,
                batch_size=effective_batch,
            ) as ingestor:
                ingestor.ensure_constraints()
                if clean:
                    ingestor.clean_database()

                updater = GraphUpdater(ingestor, target_repo, parsers, queries)
                updater.run()
                # Persist ingest metadata when successful
                write_ingest_metadata(target_repo)

            duration_ms = (time.perf_counter() - start) * 1000
            return {
                "repo_path": str(target_repo),
                "cleaned": clean,
                "batch_size": effective_batch,
                "duration_ms": duration_ms,
            }

        return await anyio.to_thread.run_sync(_task)

    async def run_query(self, question: str) -> dict[str, Any]:
        """Translate NL question into Cypher and fetch results."""

        if not question.strip():
            raise ValueError("question must not be empty")

        generator = self._ensure_cypher_generator()
        cypher_query = await generator.generate(question)

        def _task() -> list[dict[str, Any]]:
            with MemgraphIngestor(
                host=settings.MEMGRAPH_HOST,
                port=settings.MEMGRAPH_PORT,
                batch_size=self.batch_size,
            ) as ingestor:
                return ingestor.fetch_all(cypher_query)

        rows = await anyio.to_thread.run_sync(_task)
        return {"question": question, "cypher": cypher_query, "results": rows}

    async def optimize_code(
        self,
        language: str,
        instruction: str | None = None,
        reference_document: str | None = None,
    ) -> dict[str, Any]:
        """Run a single optimization prompt through the RAG orchestrator."""

        if not language.strip():
            raise ValueError("language must not be empty")

        prompt = instruction or self._default_optimization_prompt(
            language, reference_document
        )

        with MemgraphIngestor(
            host=settings.MEMGRAPH_HOST,
            port=settings.MEMGRAPH_PORT,
            batch_size=self.batch_size,
        ) as ingestor:
            rag_agent = initialize_services_and_agent(str(self.default_repo), ingestor)
            response = await rag_agent.run(prompt)

        return {"language": language, "response": response.output}

    async def get_status(self) -> dict[str, Any]:
        """Return current configuration snapshot."""

        orch = settings.active_orchestrator_config
        cypher_conf = settings.active_cypher_config
        return {
            "repo_path": str(self.default_repo),
            "batch_size": self.batch_size,
            "memgraph": {
                "host": settings.MEMGRAPH_HOST,
                "port": settings.MEMGRAPH_PORT,
            },
            "orchestrator": {
                "provider": orch.provider,
                "model": orch.model_id,
            },
            "cypher": {
                "provider": cypher_conf.provider,
                "model": cypher_conf.model_id,
            },
        }

    async def get_ingest_status(self, repo_path: str | None = None) -> dict[str, Any]:
        """Return last ingest timestamp and change counts since then."""

        target_repo = self._resolve_repo(repo_path)
        last_ingest, changes, metadata_path = summarize_ingest_status(target_repo)
        return {
            "repo_path": str(target_repo),
            "last_ingest": last_ingest,
            "changes": changes,
            "metadata_path": str(metadata_path),
        }

    async def query_codebase(
        self,
        question: str,
        strategy: str = "semantic-seed-strategy",
    ) -> dict[str, Any]:
        """Query the codebase using RAG with the specified strategy."""

        if not question.strip():
            raise ValueError("question must not be empty")

        prompt = f"/{strategy} {question}"

        with MemgraphIngestor(
            host=settings.MEMGRAPH_HOST,
            port=settings.MEMGRAPH_PORT,
            batch_size=self.batch_size,
        ) as ingestor:
            rag_agent = initialize_services_and_agent(str(self.default_repo), ingestor)
            response = await rag_agent.run(prompt)

        return {
            "question": question,
            "strategy": strategy,
            "response": response.output,
        }

    def _default_optimization_prompt(
        self, language: str, reference_document: str | None
    ) -> str:
        document_line = (
            f"Reference insights from {reference_document} where applicable."
            if reference_document
            else ""
        )
        return (
            "You are an optimization agent for the Graph-Code project. "
            f"Analyze the {language} portions of the repository and propose clear, actionable improvements. "
            "List concrete files, functions, or classes that should change, explain why, and outline the exact edits. "
            "Return a concise markdown summary with headers. "
            f"{document_line}"
        ).strip()


@dataclass
class GraphCodeMCPServer:
    """Wraps the MCP server wiring and tool dispatch."""

    context: GraphCodeMCPContext
    name: str = "graph-code-mcp"

    def __post_init__(self) -> None:
        self._tools = self._build_tool_definitions()
        self.server = Server(
            name=self.name,
            instructions=(
                "Expose Graph-Code ingestion, query, optimization, and status tools over MCP."
            ),
        )
        self.server.list_tools()(self._list_tools)
        self.server.call_tool()(self._call_tool)

    def _build_tool_definitions(self) -> list[types.Tool]:
        return [
            types.Tool(
                name="graph_ingest",
                title="Update Knowledge Graph",
                description="Parse a repository with Tree-sitter and refresh the Memgraph knowledge graph.",
                inputSchema=_build_tool_schema("graph_ingest"),
                outputSchema={
                    "type": "object",
                    "properties": {
                        "repo_path": {"type": "string"},
                        "cleaned": {"type": "boolean"},
                        "batch_size": {"type": "integer"},
                        "duration_ms": {"type": "number"},
                    },
                    "required": ["repo_path", "cleaned", "batch_size", "duration_ms"],
                },
            ),
            types.Tool(
                name="graph_query",
                title="Query Knowledge Graph",
                description="Translate natural-language questions into Cypher and return query results.",
                inputSchema=_build_tool_schema("graph_query"),
                outputSchema={
                    "type": "object",
                    "properties": {
                        "question": {"type": "string"},
                        "cypher": {"type": "string"},
                        "results": {"type": "array"},
                    },
                    "required": ["question", "cypher", "results"],
                },
            ),
            types.Tool(
                name="optimize_code",
                title="Request Optimization Suggestions",
                description="Kick off an optimization prompt targeting a specific language and optional reference doc.",
                inputSchema=_build_tool_schema("optimize_code"),
                outputSchema={
                    "type": "object",
                    "properties": {
                        "language": {"type": "string"},
                        "response": {"type": "string"},
                    },
                    "required": ["language", "response"],
                },
            ),
            types.Tool(
                name="get_status",
                title="Get Server Status",
                description="Return current Graph-Code MCP configuration (repo path, providers, Memgraph host).",
                inputSchema=_build_tool_schema("get_status"),
                outputSchema={
                    "type": "object",
                    "properties": {
                        "repo_path": {"type": "string"},
                        "batch_size": {"type": "integer"},
                        "memgraph": {"type": "object"},
                        "orchestrator": {"type": "object"},
                        "cypher": {"type": "object"},
                    },
                    "required": [
                        "repo_path",
                        "batch_size",
                        "memgraph",
                        "orchestrator",
                        "cypher",
                    ],
                },
            ),
            types.Tool(
                name="ingest_status",
                title="Ingest Status",
                description="Summarize the last ingest timestamp and file changes since then.",
                inputSchema=_build_tool_schema("ingest_status"),
                outputSchema={
                    "type": "object",
                    "properties": {
                        "repo_path": {"type": "string"},
                        "last_ingest": {"type": ["string", "null"]},
                        "changes": {
                            "type": "object",
                            "properties": {
                                "added": {"type": "integer"},
                                "deleted": {"type": "integer"},
                                "modified": {"type": "integer"},
                                "total": {"type": "integer"},
                            },
                        },
                        "metadata_path": {"type": "string"},
                    },
                    "required": [
                        "repo_path",
                        "last_ingest",
                        "changes",
                        "metadata_path",
                    ],
                },
            ),
            types.Tool(
                name="query_codebase",
                title="Query Codebase (RAG)",
                description="Query the codebase using natural language questions with configurable RAG strategy. semantic-seed-strategy is the standard default.",
                inputSchema=_build_tool_schema("query_codebase"),
                outputSchema={
                    "type": "object",
                    "properties": {
                        "question": {"type": "string"},
                        "strategy": {"type": "string"},
                        "response": {"type": "string"},
                    },
                    "required": ["question", "strategy", "response"],
                },
            ),
        ]

    async def _list_tools(
        self, _: types.ListToolsRequest | None = None
    ) -> list[types.Tool]:
        return self._tools

    async def _call_tool(
        self, tool_name: str, arguments: dict[str, Any] | None
    ) -> tuple[list[types.TextContent], dict[str, Any]]:
        args = arguments or {}

        try:
            if tool_name == "graph_ingest":
                result = await self.context.run_ingest(
                    repo_path=args.get("repo_path"),
                    clean=bool(args.get("clean", False)),
                    batch_size=args.get("batch_size"),
                )
                return self._format_response(
                    result,
                    f"Updated graph for {result['repo_path']} (clean={result['cleaned']}).",
                )
            if tool_name == "graph_query":
                question = args.get("question", "")
                result = await self.context.run_query(question)
                summary = f"Executed Cypher query: {result['cypher']}"
                return self._format_response(result, summary)
            if tool_name == "optimize_code":
                result = await self.context.optimize_code(
                    language=args.get("language", ""),
                    instruction=args.get("instruction"),
                    reference_document=args.get("reference_document"),
                )
                return self._format_response(result, result["response"])
            if tool_name == "get_status":
                result = await self.context.get_status()
                return self._format_response(result, json.dumps(result, indent=2))
            if tool_name == "ingest_status":
                result = await self.context.get_ingest_status(
                    repo_path=args.get("repo_path")
                )
                if not result.get("repo_path"):
                    result["repo_path"] = str(self.context.default_repo)
                if "changes" not in result:
                    result["changes"] = {
                        "added": 0,
                        "deleted": 0,
                        "modified": 0,
                        "total": 0,
                    }
                if "metadata_path" not in result:
                    result["metadata_path"] = str(
                        Path(self.context.default_repo) / ".graphcode_ingest.json"
                    )
                message = (
                    f"Last ingest: {result['last_ingest']} | changes: {result['changes']['total']}"
                    if result.get("last_ingest")
                    else f"No ingest metadata found; {result['changes']['total']} files present"
                )
                return self._format_response(result, message)

            if tool_name == "query_codebase":
                result = await self.context.query_codebase(
                    question=args.get("question", ""),
                    strategy=args.get("strategy", "semantic-seed-strategy")
                )
                return self._format_response(result, result["response"])

            raise ValueError(f"Unsupported tool: {tool_name}")
        except Exception as exc:  # pragma: no cover - error path tested separately
            logger.error("MCP tool '%s' failed: %s", tool_name, exc, exc_info=True)
            error_content = types.TextContent(
                type="text",
                text=f"Error running {tool_name}: {exc}",
            )
            return [error_content], {"error": str(exc)}

    @staticmethod
    def _format_response(
        structured: dict[str, Any],
        message: str,
    ) -> tuple[list[types.TextContent], dict[str, Any]]:
        return ([types.TextContent(type="text", text=message)], structured)

    async def serve(self) -> None:
        """Start the MCP server over stdio."""

        init_options = self.server.create_initialization_options()
        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                init_options,
            )


async def serve_mcp_stdio(
    repo_path: str,
    batch_size: int,
    *,
    server_name: str = "graph-code-mcp",
) -> None:
    """Start the MCP server over stdio."""

    context = GraphCodeMCPContext(repo_path=repo_path, batch_size=batch_size)
    server = GraphCodeMCPServer(context=context, name=server_name)
    await server.serve()


async def serve_mcp_http(
    repo_path: str,
    batch_size: int,
    *,
    server_name: str = "graph-code-mcp",
    host: str = "127.0.0.1",
    port: int = 8765,
    path: str = "/mcp",
    stateless: bool = False,
) -> None:
    """Start the MCP server over Streamable HTTP (SSE/JSON)."""

    context = GraphCodeMCPContext(repo_path=repo_path, batch_size=batch_size)
    mcp_server = GraphCodeMCPServer(context=context, name=server_name)
    session_manager = StreamableHTTPSessionManager(
        mcp_server.server, stateless=True if stateless is None else stateless
    )

    async def lifespan(app: Starlette):
        async with session_manager.run():
            yield

    async def mcp_asgi(scope, receive, send):  # ASGI callable
        if scope.get("type") != "http":
            await PlainTextResponse("Not Found", status_code=404)(scope, receive, send)
            return
        await session_manager.handle_request(scope, receive, send)

    routes = [Mount(path, app=mcp_asgi)]
    if path != "/":
        routes.append(Mount("/", app=mcp_asgi))

    app = Starlette(
        routes=routes,
        lifespan=lifespan,
        middleware=[Middleware(TransportLoggingMiddleware)],
    )

    import uvicorn

    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()
