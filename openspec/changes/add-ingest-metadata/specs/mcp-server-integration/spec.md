## MODIFIED Requirements

### Requirement: MCP Server Entrypoint
The MCP server SHALL expose a CLI command that starts an MCP-compatible server over stdio, sharing the same configuration model used by existing Typer commands.

#### Scenario: Launch server with repo override
- **GIVEN** a user runs `uv run python -m codebase_rag.main mcp --repo-path /tmp/repo`
- **AND** `.env` defines valid orchestrator/cypher providers
- **WHEN** an MCP client connects over stdio and issues `list_tools`
- **THEN** the server responds with a tool list that includes ingestion, query, optimization, status tools, **and an ingest status tool** referencing `/tmp/repo` as the default target.

### Requirement: Tool Coverage
The MCP server SHALL expose tools that wrap core Graph-Code operations so agents can ingest/update graphs, answer natural-language questions, optimize code, and retrieve status/configuration metadata.

#### Scenario: Invoke ingest status tool
- **GIVEN** the MCP server is running and the repository has a recorded last-ingest timestamp
- **WHEN** a client calls the ingest-status tool
- **THEN** it returns the last successful ingest timestamp and the current count of file changes since that ingest, or indicates that no ingest metadata exists.
