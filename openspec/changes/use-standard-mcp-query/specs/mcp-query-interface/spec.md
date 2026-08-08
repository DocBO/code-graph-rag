## ADDED Requirements

### Requirement: Standard MCP Codebase Query

The MCP server SHALL expose `query_codebase` as a natural-language question
tool that executes the standard agent search/answer flow without public
retrieval-strategy selection.

#### Scenario: Ask a codebase question

- **WHEN** an MCP client calls `query_codebase` with a non-empty `question`
- **THEN** the server runs the standard agent with that question
- **AND** returns the original `question` and synthesized `response`

#### Scenario: Discover query tool schema

- **WHEN** an MCP client lists available tools
- **THEN** the `query_codebase` input schema requires only `question`
- **AND** does not expose `strategy` or `max_retries`

#### Scenario: Reject removed strategy selection

- **WHEN** an MCP client calls `query_codebase` with a `strategy` argument
- **THEN** MCP schema validation rejects the unsupported argument
