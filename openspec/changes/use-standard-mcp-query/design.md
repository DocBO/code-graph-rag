## Context

The MCP server currently exposes strategy selection and routes the default
request through `run_semantic_seed_strategy`. The normal agent path already
combines graph tools, semantic tools when useful, source retrieval, and answer
synthesis under the orchestrator's control.

## Goals / Non-Goals

- Goals:
  - Expose one reliable natural-language codebase query operation over MCP.
  - Keep MCP input and output schemas minimal and deterministic.
  - Reuse the established standard agent initialization and execution path.
- Non-Goals:
  - Delete semantic search or the semantic-seed slash command from the CLI.
  - Change graph ingestion or embedding generation.
  - Add a replacement MCP strategy-selection mechanism.

## Decisions

- Decision: `query_codebase(question)` will always run the standard RAG agent
  with the unmodified question.
- Decision: remove `strategy` and `max_retries` from the MCP schema instead of
  accepting and ignoring them, so unsupported behavior is explicit.
- Decision: return only `question` and `response` from the public result.

## Risks / Trade-offs

- Existing MCP callers using strategy arguments will receive schema validation
  errors. This is intentional because strategy selection is no longer supported.
- The standard agent may choose semantic tools internally, but MCP no longer
  forces the semantic-seed orchestration path.

## Migration Plan

1. Update MCP clients to call `query_codebase` with only `question`.
2. Deploy the updated server.
3. Verify tool discovery exposes the simplified schema and a representative
   frontend question reaches the standard agent.
