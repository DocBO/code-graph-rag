## Why

Embedding complete source bodies creates a large, noisy Qdrant corpus even though
Memgraph already retains full structural and source-level information. Semantic
retrieval should prioritize concise Python API descriptions and documentation.

## What Changes

- Limit Python code embeddings to class, function, and method names, with their
  docstrings when present; do not embed Python implementation bodies.
- Embed Markdown files as normal size-bounded chunks and retain each chunk's
  path and searchable text in Qdrant.
- Exclude non-Python source and frontend asset contents from new Qdrant
  embeddings.
- Keep Memgraph ingestion, nodes, relationships, and source extraction behavior
  unchanged.
- Regenerate the repository Qdrant collection so vectors made under the old
  strategy cannot remain searchable.

## Impact

- Affected specs: `embedding-content-selection` (new capability)
- Affected code: semantic embedding generation, incremental embedding updates,
  Qdrant payload identity, and embedding tests
- **BREAKING**: semantic search will no longer retrieve arbitrary source-body
  text or non-Markdown non-Python assets from Qdrant.
