"""Model Context Protocol (MCP) server wiring for Graph-Code."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

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
from ..tools.semantic_search import get_function_source_code, semantic_code_search_async
from ..utils.chunking import chunk_boundaries


class TransportLoggingMiddleware:
    """Tiny middleware to log incoming HTTP requests to the MCP endpoint."""

    def __init__(self, app: Any):
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") == "http":
            method = scope.get("method", "UNKNOWN")
            path = scope.get("path", "UNKNOWN")
            query_string = scope.get("query_string", b"").decode("utf-8")
            full_path = f"{path}?{query_string}" if query_string else path

            # Log basic request info
            logger.info(f"[MCP HTTP] {method} {full_path}")

            # Log headers for debugging 400 errors
            headers = {
                k.decode("utf-8"): v.decode("utf-8")
                for k, v in scope.get("headers", [])
            }
            logger.debug(f"[MCP HTTP] Headers: {headers}")

        await self.app(scope, receive, send)


def _build_tool_schema(name: str) -> dict[str, Any]:
    """Return JSON schema definitions for supported tools."""

    match name:
        case "graph_query":
            return {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "Natural language question to transform into a Cypher query.",
                    },
                    "repo_path": {
                        "type": "string",
                        "description": "Optional repository path override. Defaults to the server's configured repository.",
                    },
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
                    "repo_path": {
                        "type": "string",
                        "description": "Optional repository path override. Defaults to the server's configured repository.",
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
                    "repo_path": {
                        "type": "string",
                        "description": "Optional repository path override. Defaults to the server's configured repository.",
                    },
                },
                "required": ["question"],
                "additionalProperties": False,
            }
        case "quick_semantic_retrieval":
            return {
                "type": "object",
                "properties": {
                    "search_phrase": {
                        "type": "string",
                        "description": "Semantic search phrase used to find relevant symbols.",
                    },
                    "top_n": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 50,
                        "description": "Maximum number of semantic matches to return (default: 5).",
                    },
                    "repo_path": {
                        "type": "string",
                        "description": "Optional repository path override. Defaults to the server's configured repository.",
                    },
                },
                "required": ["search_phrase"],
                "additionalProperties": False,
            }
        case "get_watched_repos":
            return {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            }
        case "start_updater":
            return {
                "type": "object",
                "properties": {
                    "repo_path": {
                        "type": "string",
                        "description": "Optional repository path override. Defaults to the server's configured repository.",
                    },
                    "force": {
                        "type": "boolean",
                        "description": "Run a full graph update even when the index is not stale (default: false).",
                    },
                },
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

    async def run_query(
        self, question: str, repo_path: str | None = None
    ) -> dict[str, Any]:
        """Translate NL question into Cypher and fetch results."""

        if not question.strip():
            raise ValueError("question must not be empty")

        target_repo = self._resolve_repo(repo_path)
        generator = self._ensure_cypher_generator()
        cypher_query = await generator.generate(question)

        def _task() -> list[dict[str, Any]]:
            if target_repo != self.default_repo:
                from ..services.graph_service import execute_read_query

                return cast(
                    list[dict[str, Any]],
                    execute_read_query(
                        host=settings.MEMGRAPH_HOST,
                        port=settings.MEMGRAPH_PORT,
                        query=cypher_query,
                        params={"repo_path": str(target_repo)},
                    ),
                )
            with MemgraphIngestor(
                host=settings.MEMGRAPH_HOST,
                port=settings.MEMGRAPH_PORT,
                batch_size=self.batch_size,
                repo_path=self.default_repo,
            ) as ingestor:
                return cast(list[dict[str, Any]], ingestor.fetch_all(cypher_query))

        rows = await anyio.to_thread.run_sync(_task)
        return {
            "repo_path": str(target_repo),
            "question": question,
            "cypher": cypher_query,
            "results": rows,
        }

    async def optimize_code(
        self,
        language: str,
        instruction: str | None = None,
        reference_document: str | None = None,
        repo_path: str | None = None,
    ) -> dict[str, Any]:
        """Run a single optimization prompt through the RAG orchestrator."""

        if not language.strip():
            raise ValueError("language must not be empty")

        target_repo = self._resolve_repo(repo_path)
        prompt = instruction or self._default_optimization_prompt(
            language, reference_document
        )

        with MemgraphIngestor(
            host=settings.MEMGRAPH_HOST,
            port=settings.MEMGRAPH_PORT,
            batch_size=self.batch_size,
            repo_path=target_repo,
        ) as ingestor:
            rag_agent = initialize_services_and_agent(str(target_repo), ingestor)
            response = await rag_agent.run(prompt)

        return {
            "repo_path": str(target_repo),
            "language": language,
            "response": response.output,
        }

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

    async def start_updater(
        self, repo_path: str | None = None, force: bool = False
    ) -> dict[str, Any]:
        """Run a one-shot full graph update for a repo.

        Skips the update (reporting ``started=False``) when the index is fresh
        and ``force`` is false, so agents can safely call this after detecting
        a stale index via ``ingest_status``.
        """

        target_repo = self._resolve_repo(repo_path)
        last_ingest, changes, metadata_path = summarize_ingest_status(target_repo)
        stale = changes.get("total", 0) > 0 or last_ingest is None

        if not stale and not force:
            return {
                "repo_path": str(target_repo),
                "started": False,
                "reason": "index_fresh",
                "last_ingest": last_ingest,
                "changes": changes,
                "metadata_path": str(metadata_path),
            }

        def _task() -> None:
            with MemgraphIngestor(
                host=settings.MEMGRAPH_HOST,
                port=settings.MEMGRAPH_PORT,
                batch_size=self.batch_size,
                repo_path=target_repo,
            ) as ingestor:
                ingestor.ensure_constraints()
                if force:
                    # A forced refill rebuilds the whole index, so purge stale
                    # embedding points from previous runs (e.g. different chunk
                    # sizes or naming schemes) before regenerating them.
                    from ..utils.dependencies import has_semantic_dependencies

                    if has_semantic_dependencies():
                        from ..vector_store import clean_collection

                        try:
                            clean_collection(target_repo)
                            logger.info(
                                "Cleaned Qdrant collection for forced refill: {}",
                                target_repo,
                            )
                        except Exception as exc:
                            logger.warning(
                                "Failed to clean Qdrant collection for forced refill: {}",
                                exc,
                            )
                parsers, queries = load_parsers()
                updater = GraphUpdater(ingestor, target_repo, parsers, queries)
                updater.run()
                write_ingest_metadata(target_repo)

        await anyio.to_thread.run_sync(_task)

        return {
            "repo_path": str(target_repo),
            "started": True,
            "reason": "stale" if stale else "forced",
            "last_ingest": last_ingest,
            "changes": changes,
            "metadata_path": str(metadata_path),
        }

    async def get_watched_repos(self) -> dict[str, Any]:
        """Return registered repositories and whether each is actively watched.

        Primary source is the control panel backend (``/api/status`` on
        ``CONTROL_PANEL_URL``). If the control panel is unreachable, fall back
        to scanning ``/proc`` for running ``realtime_updater.py`` processes so
        agents can still tell whether their repo is being watched.
        """

        control_url = settings.CONTROL_PANEL_URL.rstrip("/")
        try:
            from urllib.request import urlopen

            with urlopen(
                f"{control_url}/api/status",
                timeout=2.0,
            ) as resp:
                payload = json.loads(resp.read().decode())
            repos = payload.get("repos", [])
            watched = [
                r["path"]
                for r in repos
                if (r.get("watcher") or {}).get("state") in ("running", "starting")
            ]
            return {
                "source": "control_panel",
                "control_panel": {
                    "url": control_url,
                    "reachable": True,
                    "mcp": payload.get("mcp", {}),
                },
                "repos": [
                    {
                        "path": r["path"],
                        "name": r.get("name"),
                        "watcher_state": (r.get("watcher") or {}).get("state"),
                        "watcher_pid": (r.get("watcher") or {}).get("pid"),
                        "update_in_progress": (r.get("watcher") or {}).get(
                            "update_in_progress"
                        ),
                        "last_update_at": (r.get("watcher") or {}).get(
                            "last_update_at"
                        ),
                    }
                    for r in repos
                ],
                "watched_paths": watched,
            }
        except Exception as exc:
            logger.warning(
                "Control panel not reachable at %s (%s); falling back to /proc scan.",
                control_url,
                exc,
            )
            watched = self._scan_watched_processes()
            return {
                "source": "proc_scan",
                "control_panel": {
                    "url": control_url,
                    "reachable": False,
                    "error": str(exc),
                },
                "repos": [{"path": p, "watcher_state": "running"} for p in watched],
                "watched_paths": watched,
            }

    @staticmethod
    def _scan_watched_processes() -> list[str]:
        """Return repo paths with a live ``realtime_updater.py`` process."""
        watched: list[str] = []
        for proc_dir in Path("/proc").iterdir():
            if not proc_dir.name.isdigit():
                continue
            try:
                raw = (proc_dir / "cmdline").read_bytes()
            except OSError:
                continue
            args = [a.decode(errors="replace") for a in raw.split(b"\x00") if a]
            script_idx = next(
                (i for i, a in enumerate(args) if a.endswith("realtime_updater.py")),
                None,
            )
            if script_idx is not None and script_idx + 1 < len(args):
                repo = str(Path(args[script_idx + 1]).expanduser().resolve())
                if repo not in watched:
                    watched.append(repo)
        return watched

    async def query_codebase(
        self, question: str, repo_path: str | None = None
    ) -> dict[str, Any]:
        """Query the codebase using the standard agent search/answer flow."""

        if not question.strip():
            raise ValueError("question must not be empty")

        target_repo = self._resolve_repo(repo_path)
        with MemgraphIngestor(
            host=settings.MEMGRAPH_HOST,
            port=settings.MEMGRAPH_PORT,
            batch_size=self.batch_size,
            repo_path=target_repo,
        ) as ingestor:
            rag_agent = initialize_services_and_agent(str(target_repo), ingestor)
            response = await rag_agent.run(question)

        return {
            "repo_path": str(target_repo),
            "question": question,
            "response": response.output,
        }

    async def quick_semantic_retrieval(
        self,
        search_phrase: str,
        top_n: int = 5,
        repo_path: str | None = None,
    ) -> dict[str, Any]:
        """Return semantic-only snippet matches without agentic reasoning."""

        if not search_phrase.strip():
            raise ValueError("search_phrase must not be empty")

        try:
            safe_top_n = max(1, min(int(top_n), 50))
        except (TypeError, ValueError) as exc:
            raise ValueError("top_n must be an integer") from exc
        target_repo = self._resolve_repo(repo_path)
        repo_path_str = str(target_repo)
        semantic_matches = await semantic_code_search_async(
            search_phrase,
            safe_top_n,
            repo_path=repo_path_str,
        )

        formatted_matches: list[dict[str, Any]] = []
        for match in semantic_matches:
            node_id = match.get("node_id")
            if node_id is None:
                continue

            from ..services.graph_service import execute_read_query

            location_rows = cast(
                list[dict[str, Any]],
                execute_read_query(
                    host=settings.MEMGRAPH_HOST,
                    port=settings.MEMGRAPH_PORT,
                    query="""
                    MATCH (m:Module)-[:DEFINES|CONTAINS*..5]->(n)
                    WHERE id(n) = $node_id AND n._repo_path = $repo_path
                    RETURN m.path AS filename,
                           n.start_line AS start_line,
                           n.end_line AS end_line
                    LIMIT 1
                    """,
                    params={"node_id": node_id, "repo_path": repo_path_str},
                ),
            )

            location = location_rows[0] if location_rows else {}
            snippet = match.get("chunk_text")
            if not snippet:
                source_code = get_function_source_code(
                    int(node_id), repo_path=repo_path_str
                )
                if source_code:
                    document = (
                        f"Entity: {match.get('qualified_name') or f'node:{node_id}'}\n"
                        f"Type: {match.get('type') or 'Code'}\n"
                        f"File: {location.get('filename') or 'unknown'}\n\n"
                        f"{source_code}"
                    )
                    chunk_index = self._chunk_index_from_match(
                        match.get("matched_chunk_qualified_name")
                    )
                    snippet = self._slice_chunk(document, chunk_index)

            formatted_matches.append(
                {
                    "qualified_name": match.get("qualified_name"),
                    "type": match.get("type"),
                    "score": match.get("score"),
                    "filename": location.get("filename"),
                    "start_line": location.get("start_line"),
                    "end_line": location.get("end_line"),
                    "snippet": snippet,
                }
            )

        return {
            "repo_path": repo_path_str,
            "search_phrase": search_phrase,
            "top_n": safe_top_n,
            "matches": formatted_matches,
        }

    @staticmethod
    def _chunk_index_from_match(matched_chunk_qn: Any) -> int:
        if not isinstance(matched_chunk_qn, str):
            return 0
        marker = "_chunk_"
        if marker not in matched_chunk_qn:
            return 0
        suffix = matched_chunk_qn.rsplit(marker, 1)[-1]
        return int(suffix) if suffix.isdigit() else 0

    @staticmethod
    def _slice_chunk(document: str, chunk_index: int) -> str:
        max_size = settings.EMBED_MAX_CHUNK_SIZE
        safe_index = max(0, chunk_index)
        boundaries = chunk_boundaries(len(document), max_size)
        if not boundaries:
            return ""
        if safe_index >= len(boundaries):
            return document[:max_size]
        start, end = boundaries[safe_index]
        return document[start:end]

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
    expose_internal_tools: bool = False

    def __post_init__(self) -> None:
        self._all_tools = self._build_tool_definitions()
        self.public_tools = (
            [
                t
                for t in self._all_tools
                if t.name not in {"graph_query", "optimize_code"}
            ]
            if not self.expose_internal_tools
            else self._all_tools
        )
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
                name="graph_query",
                title="Query Knowledge Graph",
                description="Translate natural-language questions into Cypher and return query results.",
                inputSchema=_build_tool_schema("graph_query"),
                outputSchema={
                    "type": "object",
                    "properties": {
                        "repo_path": {"type": "string"},
                        "question": {"type": "string"},
                        "cypher": {"type": "string"},
                        "results": {"type": "array"},
                    },
                    "required": ["repo_path", "question", "cypher", "results"],
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
                        "repo_path": {"type": "string"},
                        "language": {"type": "string"},
                        "response": {"type": "string"},
                    },
                    "required": ["repo_path", "language", "response"],
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
                description="Query the codebase using the standard agent search and answer flow.",
                inputSchema=_build_tool_schema("query_codebase"),
                outputSchema={
                    "type": "object",
                    "properties": {
                        "repo_path": {"type": "string"},
                        "question": {"type": "string"},
                        "response": {"type": "string"},
                    },
                    "required": ["repo_path", "question", "response"],
                },
            ),
            types.Tool(
                name="quick_semantic_retrieval",
                title="Quick Semantic Retrieval",
                description="Return semantic-only code snippets with filename and line metadata.",
                inputSchema=_build_tool_schema("quick_semantic_retrieval"),
                outputSchema={
                    "type": "object",
                    "properties": {
                        "repo_path": {"type": "string"},
                        "search_phrase": {"type": "string"},
                        "top_n": {"type": "integer"},
                        "matches": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "qualified_name": {"type": ["string", "null"]},
                                    "type": {"type": ["string", "null"]},
                                    "score": {"type": ["number", "null"]},
                                    "filename": {"type": ["string", "null"]},
                                    "start_line": {"type": ["integer", "null"]},
                                    "end_line": {"type": ["integer", "null"]},
                                    "snippet": {"type": ["string", "null"]},
                                },
                                "required": [
                                    "qualified_name",
                                    "type",
                                    "score",
                                    "filename",
                                    "start_line",
                                    "end_line",
                                    "snippet",
                                ],
                            },
                        },
                    },
                    "required": ["repo_path", "search_phrase", "top_n", "matches"],
                },
            ),
            types.Tool(
                name="get_watched_repos",
                title="Get Watched Repositories",
                description=(
                    "Return which repositories are registered with the control panel and "
                    "whether each has an active real-time watcher running. Lets agents quickly "
                    "check if their repo is being ingested/watched or is stopped."
                ),
                inputSchema=_build_tool_schema("get_watched_repos"),
                outputSchema={
                    "type": "object",
                    "properties": {
                        "source": {"type": "string"},
                        "control_panel": {"type": "object"},
                        "repos": {
                            "type": "array",
                            "items": {"type": "object"},
                        },
                        "watched_paths": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["source", "control_panel", "repos", "watched_paths"],
                },
            ),
            types.Tool(
                name="start_updater",
                title="Start Updater",
                description=(
                    "Run a one-shot full graph update for a repo. Detects whether the "
                    "index is stale from ingest metadata and skips the update when it is "
                    "fresh unless 'force' is true. Use this after ingest_status reports "
                    "pending file changes so the knowledge graph reflects the current code."
                ),
                inputSchema=_build_tool_schema("start_updater"),
                outputSchema={
                    "type": "object",
                    "properties": {
                        "repo_path": {"type": "string"},
                        "started": {"type": "boolean"},
                        "reason": {"type": "string"},
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
                        "started",
                        "reason",
                        "last_ingest",
                        "changes",
                        "metadata_path",
                    ],
                },
            ),
        ]

    async def _list_tools(
        self, _: types.ListToolsRequest | None = None
    ) -> list[types.Tool]:
        return self.public_tools

    async def _call_tool(
        self, tool_name: str, arguments: dict[str, Any] | None
    ) -> tuple[list[types.TextContent], dict[str, Any]]:
        args = arguments or {}

        try:
            if tool_name == "graph_query":
                question = args.get("question", "")
                result = await self.context.run_query(
                    question, repo_path=args.get("repo_path")
                )
                summary = f"Executed Cypher query: {result['cypher']}"
                return self._format_response(result, summary)
            if tool_name == "optimize_code":
                result = await self.context.optimize_code(
                    language=args.get("language", ""),
                    instruction=args.get("instruction"),
                    reference_document=args.get("reference_document"),
                    repo_path=args.get("repo_path"),
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
                    repo_path=args.get("repo_path"),
                )
                return self._format_response(result, result["response"])

            if tool_name == "quick_semantic_retrieval":
                result = await self.context.quick_semantic_retrieval(
                    search_phrase=args.get("search_phrase", ""),
                    top_n=args.get("top_n", 5),
                    repo_path=args.get("repo_path"),
                )
                return self._format_response(
                    result,
                    f"Returned {len(result['matches'])} semantic snippet matches.",
                )

            if tool_name == "get_watched_repos":
                result = await self.context.get_watched_repos()
                watched = result.get("watched_paths", [])
                message = (
                    f"{len(watched)} repo(s) actively watched"
                    if watched
                    else "No repositories are currently being watched."
                )
                return self._format_response(result, message)

            if tool_name == "start_updater":
                result = await self.context.start_updater(
                    repo_path=args.get("repo_path"),
                    force=bool(args.get("force", False)),
                )
                if result.get("started"):
                    reason = result.get("reason")
                    message = (
                        f"Graph update started for {result['repo_path']} "
                        f"({result['changes']['total']} pending change(s), reason={reason})."
                    )
                else:
                    message = (
                        f"Index is fresh for {result['repo_path']}; no update started. "
                        f"Pending changes: {result['changes']['total']}."
                    )
                return self._format_response(result, message)

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

    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        async with session_manager.run():
            yield

    async def mcp_asgi(
        scope: dict[str, Any],
        receive: Callable[[], Awaitable[dict[str, Any]]],
        send: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:  # ASGI callable
        if scope.get("type") != "http":
            await PlainTextResponse("Not Found", status_code=404)(scope, receive, send)
            return

        async def wrapped_send(message: dict[str, Any]) -> None:
            if message.get("type") == "http.response.start":
                status = message.get("status")
                if isinstance(status, int) and status >= 400:
                    logger.warning(f"[MCP HTTP] Response Status: {status}")
            elif message.get("type") == "http.response.body":
                body = message.get("body", b"")
                if body:
                    try:
                        # Only log if it looks like an error message
                        body_text = body.decode("utf-8")
                        if "error" in body_text.lower() or len(body_text) < 200:
                            logger.debug(f"[MCP HTTP] Response Body: {body_text}")
                    except Exception:
                        pass
            await send(message)

        try:
            await session_manager.handle_request(scope, receive, wrapped_send)
        except Exception as e:
            logger.error(f"[MCP HTTP] Exception in handle_request: {e}", exc_info=True)
            await PlainTextResponse(f"Internal Error: {e}", status_code=500)(
                scope, receive, send
            )

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
