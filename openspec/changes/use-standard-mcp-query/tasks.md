## 1. Implementation

- [x] 1.1 Simplify the `query_codebase` MCP input schema to require only `question`.
- [x] 1.2 Route `GraphCodeMCPContext.query_codebase` directly through the standard
      agent search/answer flow.
- [x] 1.3 Remove strategy-specific fields from the MCP response schema and dispatch.
- [x] 1.4 Update MCP documentation for the standard-only query contract.

## 2. Verification

- [x] 2.1 Add MCP tests for the simplified input/output schema.
- [x] 2.2 Add a regression test proving MCP query dispatch reaches the standard
      context method without semantic-seed arguments.
- [x] 2.3 Run focused MCP tests, Ruff, and type checks.
