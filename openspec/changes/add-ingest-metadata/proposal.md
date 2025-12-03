## Why
Agents have no visibility into when the graph was last ingested or how many files changed since then, making it hard to decide if a refresh is needed. Storing ingest metadata in the repo and exposing it via MCP lets tools warn when the graph is stale.

## What Changes
- Persist last successful ingest timestamp (and repo fingerprint) in a repo-local metadata file.
- Add logic to compute file changes since the last ingest and expose this data through an MCP tool so agents can decide to re-ingest.
- Document the new behavior and MCP tool usage.

## Impact
- Affected specs: `mcp-server-integration`
- Affected code: ingest pipeline, metadata persistence helper, MCP server/tool definitions, docs/tests.
