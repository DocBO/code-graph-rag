## Context

Pass 4 currently queries graph symbols and asset files, extracts full source,
and writes chunks to Qdrant. Incremental updates use the same preparation path.
Memgraph is the authoritative structural graph and remains independent of this
selection policy.

## Goals / Non-Goals

- Goals: concise Python API vectors, chunked Markdown vectors, identical full
  and incremental behavior, and no change to Memgraph ingestion.
- Non-Goals: changing graph parsing, relationships, Qdrant transport, query
  embedding, or adding embeddings for other programming languages.

## Decisions

- Build Python symbol documents from the qualified/display name and docstring
  only. If no docstring exists, the symbol name remains embeddable.
- Select Markdown from files directly and use the existing size-bounded chunking
  helper. Its path is retained in the Qdrant payload for incremental deletion.
- Use deterministic, content-kind-specific Qdrant qualified names for Markdown
  chunks and Python symbols to prevent collisions.
- Apply this shared selection path to both full regeneration and changed-file
  updates; full regeneration clears the collection first.

## Risks / Trade-offs

- Body-text and non-Python semantic recall is intentionally removed. Users can
  retrieve those details through Memgraph/source tools after locating a symbol.
- Python docstrings must be extracted safely from source/AST metadata; malformed
  or unavailable docstrings must not prevent the symbol-name vector.

## Migration Plan

1. Deploy the new selection policy.
2. Run the existing embedding-only regeneration action (or a full update) for
   each repository to replace old vectors.
3. Roll back by restoring the previous selection policy and regenerate again.
