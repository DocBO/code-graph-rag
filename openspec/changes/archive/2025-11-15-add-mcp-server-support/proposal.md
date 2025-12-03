## Why
External MCP-compatible agents (Codex CLI, Claude Code, etc.) cannot call Graph-Code operations today, forcing users to rely on the Typer CLI manually. An MCP server would let any compliant agent connect, list tools, and invoke graph ingestion/query/optimization flows programmatically.

## What Changes
- Add an MCP server entrypoint that exposes the existing Graph-Code capabilities (ingest/query/optimize/config queries) as MCP tools with schema definitions.
- Wire configuration so the MCP server shares orchestrator/cypher settings, Memgraph hosts, and repo targets with the current CLI.
- Document how to start the MCP server and connect MCP clients; add automated coverage (unit/integration) that exercises a basic MCP `list_tools` and sample tool invocation.

## Impact
- Affected specs: `mcp-server-integration`
- Affected code: new MCP server module (likely under `codebase_rag/mcp/`), configuration plumbing, CLI entrypoints/README docs, tests.
