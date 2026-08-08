## Why

The MCP `query_codebase` tool currently defaults to the semantic-seed strategy,
which is less reliable than the standard agent search/answer flow for the target
repositories. MCP clients need one predictable query path that uses the same
general retrieval behavior as the usual interactive question flow.

## What Changes

- Make MCP `query_codebase` execute the standard agent search/answer flow directly.
- Remove the `strategy` and `max_retries` inputs from the public MCP tool schema.
- Remove semantic-seed-specific dispatch from the MCP server while retaining the
  semantic-seed implementation for non-MCP callers.
- Return `question` and `response` from `query_codebase` without a strategy field.
- Update MCP documentation and tests for the simplified contract.

## Impact

- Affected specs: `mcp-query-interface`
- Affected code: `codebase_rag/mcp/server.py`,
  `codebase_rag/tests/test_mcp_server.py`, `docs/mcp-tools.md`
- Breaking change: MCP clients that pass `strategy` or consume the returned
  `strategy` field must remove that usage.
