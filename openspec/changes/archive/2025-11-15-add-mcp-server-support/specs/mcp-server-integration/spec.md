## ADDED Requirements

### Requirement: MCP Server Entrypoint
Graph-Code SHALL expose a CLI command that starts an MCP-compatible server over stdio, sharing the same configuration model used by existing Typer commands.

#### Scenario: Launch server with repo override
- **GIVEN** a user runs `python -m codebase_rag.main mcp --repo-path /tmp/repo`
- **AND** `.env` defines valid orchestrator/cypher providers
- **WHEN** an MCP client connects over stdio and issues `list_tools`
- **THEN** the server responds with a tool list that includes ingestion, query, optimization, and status tools referencing `/tmp/repo` as the default target.

### Requirement: Tool Coverage
The MCP server SHALL expose tools that wrap core Graph-Code operations so agents can ingest/update graphs, answer natural-language questions, optimize code, and retrieve status/configuration metadata.

#### Scenario: Invoke graph query tool
- **GIVEN** the MCP server is running and a client sends an `call_tool` request for `graph_query` with natural-language text
- **WHEN** the request is processed
- **THEN** the server uses the Cypher generator + query stack to return results (or errors) formatted per MCP spec.

#### Scenario: Invoke ingest tool
- **GIVEN** the MCP server is running with Memgraph reachable
- **WHEN** a client calls the ingestion tool with `update_graph=true`
- **THEN** the server runs the existing ingest pipeline and returns completion metadata (success, counts, or error message).

### Requirement: Automated Validation & Docs
Documentation and automated tests SHALL cover how to start the MCP server and prove at least one tool call works end-to-end.

#### Scenario: README instructions
- **GIVEN** a contributor reads the README
- **THEN** they find a section describing prerequisites, startup commands, and client connection steps for the MCP server.

#### Scenario: Automated list_tools test
- **GIVEN** the test suite runs `pytest`
- **THEN** there is a test that imports the MCP server module, triggers a `list_tools` and one tool invocation using the MCP SDK's in-process transport, and asserts non-error responses.
