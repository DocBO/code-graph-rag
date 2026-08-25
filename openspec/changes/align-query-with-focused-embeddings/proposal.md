## Why

The general query agent still describes semantic retrieval as broad code-intent
search even though Qdrant now indexes only Python API names/docstrings and
chunked Markdown. Its tool guidance must describe the current corpus so agents
choose the right retrieval path and do not mistake a semantic miss for absence
of implementation in other languages.

## What Changes

- Teach both normal and read-only query prompts that semantic retrieval covers
  Python API descriptions and Markdown documentation only.
- Direct agents to use Memgraph and source-reading tools for implementation
  bodies, non-Python code, and exact structural facts.
- Update semantic tool descriptions to describe the focused corpus.
- Add prompt/tool contract tests for the retrieval guidance.

## Impact

- Affected specs: `focused-semantic-query-guidance` (new capability)
- Affected code: RAG prompts, semantic-search tool descriptions, and tests
