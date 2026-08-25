## 1. Implementation

- [x] 1.1 Define the embeddable item selection and document construction for
  Python symbols and Markdown files.
- [x] 1.2 Apply the selection consistently to full Pass 4 generation and
  incremental changed-file updates without modifying Memgraph ingestion.
- [x] 1.3 Preserve file-path payloads and unique stable identities for Markdown
  chunks and Python symbols in Qdrant.
- [x] 1.4 Add focused tests for Python name/docstring documents, Markdown
  chunking, exclusion of other source types, and incremental replacement.
- [x] 1.5 Update `docs/CHANGELOG.md` after implementation with actual
  verification results.

## 2. Verification

- [x] 2.1 Run the focused embedding and semantic-search tests.
- [x] 2.2 Run the relevant lint/type checks.
- [ ] 2.3 Ask for end-to-end testing on a running localhost instance.
