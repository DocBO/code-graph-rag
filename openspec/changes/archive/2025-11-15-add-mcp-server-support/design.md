## Overview
Expose Graph-Code functionality over the Model Context Protocol (MCP) so external agents can treat Graph-Code as a tool provider. The MCP server should wrap the existing Typer CLI/use-case functions without duplicating logic.

## Components
1. **Server Entrypoint**: New Typer command (e.g., `graph-code mcp`) that:
   - Loads `settings` (Memgraph, providers, repo path) just like `start`/`optimize`.
   - Instantiates core helpers (CodeRetriever, CypherGenerator, GraphUpdater) once and reuses them per request.
   - Uses the `mcp` Python SDK to expose tools and handle JSON-RPC transport (stdio by default).

2. **Tools** (JSON Schema inputs/outputs):
   - `graph_ingest`
     - **input**: `{ "repo_path"?: string, "clean"?: boolean, "batch_size"?: integer }`
     - **output**: `{ "repo_path": string, "cleaned": boolean, "duration_ms": number }`
     - Opens `MemgraphIngestor`, optionally cleans DB, loads `parsers/queries` once per server, runs `GraphUpdater.run()`.
   - `graph_query`
     - **input**: `{ "question": string }`
     - **output**: `{ "cypher": string, "results": list[dict] }`
     - Reuses a shared `CypherGenerator` instance, runs query via `MemgraphIngestor.fetch_all`.
   - `optimize_code`
     - **input**: `{ "language": string, "instruction"?: string, "reference_document"?: string }`
     - **output**: `{ "language": string, "response": string }`
     - Spins up a short-lived `MemgraphIngestor`, builds a RAG agent with `initialize_services_and_agent`, asks it an optimization prompt (either default instruction or provided text), returns markdown text.
   - `get_status`
     - **input**: `{}`
     - **output**: `{ "repo_path": string, "memgraph": {"host": str, "port": int}, "orchestrator": {...}, "cypher": {...} }`.

3. **Configuration Sharing**: CLI command accepts `--repo-path`, `--batch-size`, `--orchestrator`, `--cypher`, matching `start/optimize`. These call `_setup_common_initialization` (for directories/logging) and `_update_model_settings`. Default repo/path live in `settings` and can be overridden per-tool via payload.

4. **Error Handling**: Convert internal exceptions into MCP error responses; log with loguru.

## Testing Strategy
- Unit-test tool functions (ensure they call underlying services).
- Integration-test the MCP handler using the SDK's in-process transport to assert `list_tools` and sample invocations return expected payloads.
