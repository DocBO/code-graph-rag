1. [x] Design ingest metadata storage: file name/location, schema (timestamp, repo path, digest), and how to compute file change count since last ingest.
2. [x] Implement metadata writing on successful ingest and a helper to load/compare current repo state (file mtimes/hash) inside `codebase_rag`.
3. [x] Add an MCP tool that returns the last ingest timestamp and the number of file changes since then; wire it into the server and CLI docs.
4. [x] Add tests covering metadata write/read and the MCP tool response; update README/docs to describe the new capability.
