## Why

Markdown chunks are stored with their source paths in Qdrant, but quick semantic
retrieval loses that metadata before it reaches the control-panel result card.
Markdown matches therefore show an unknown or empty file location despite the
correct chunk being retrieved.

## What Changes

- Preserve Qdrant `file_path` metadata in semantic-search match results.
- Use that stored path as the source-location fallback for quick semantic
  retrieval, including Markdown `File` nodes that do not have a Module-to-symbol
  relationship.
- Show the resulting source path in the control-panel expandable result header.

## Impact

- Affected specs: `semantic-result-sources` (new capability)
- Affected code: Qdrant result mapping, semantic-search result contract, MCP
  quick retrieval, and control-panel result display/tests
