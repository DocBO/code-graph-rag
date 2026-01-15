# Changelog

## 2026-01-14

### Iterative Retrieval & Deep Context Awareness 🧠
- **Implemented Iterative Semantic Seed Strategy** - Added an automated retry loop (up to 3 rounds) that uses the LLM to identify "Missing Concepts" when context is insufficient, triggering recursive searches to fill knowledge gaps.
- **Expanded Semantic Coverage to Classes** - Pass 4 ingestion now includes `Class` nodes in the vector database, allowing the RAG engine to find high-level architectural components via natural language.
- **Optimized Nested Symbol Resolution** - Integrated variable-length Cypher paths (`-[:DEFINES|CONTAINS*..5]->`) into retrieval queries to correctly locate source files for methods or classes nested deeply within modules.
- **Restored Search Visibility** - Re-introduced detailed telemetry for keyword-based seed discovery and graph expansion counts, providing clear logs for how the iterative rounds traverse the codebase.
- **Configurable Retrieval Depth** - Exposed `max_retries` as a parameter in the `query_codebase` MCP tool to allow users to control the trade-off between search depth and latency.

## 2026-01-09

### Type Inference Recursion & Phase 4 Optimization 🔧
- **Fixed Infinite Recursion in Type Inference** - Implemented a `visited` set guard in `TypeInferenceEngine` to prevent infinite loops during self-assignment analysis (e.g., `x = self.x()`).
- **Restored & Optimized Phase 4 (Semantic Embeddings)** - Re-enabled and optimized semantic embedding generation using batch processing for both Local and Cloud providers, significantly reducing ingestion time.
- **Enhanced Ingestion Memory Efficiency** - Introduced module-level instance variable caching and batch upserts to Qdrant to handle large repositories like `addibase` without OOM.
- **Cleaned Debug Instrumentation** - Removed verbose log statements and manual flushing added during the hang investigation for cleaner production output.
- **Strict Repository Isolation** - Standardized `repo_path` resolution using absolute paths with home expansion (`~`) and enforced `_repo_path` filtering across all Memgraph queries. Updated LLM prompts with mandatory isolation rules and automated parameter injection in the database driver.

### Connection & Hangs Fixed 🔧
- **Fixed cursor iteration hang** - Replaced `cursor.fetchall()` with `cursor.fetchone()` loop in all query execution methods (`_execute_query`, `_execute_batch_with_return`, `execute_read_query`) to prevent memory issues and timeouts with large result sets.
- **Fixed connection close hang** - Added 5-second timeout to `conn.close()` in `__exit__()` to prevent indefinite hangs when Memgraph is slow to finalize connections on large repositories.
- **Disabled batch embedding generation** - Batch embedding generation at ingestion time causes hangs on large repositories with thousands of functions. Embeddings are now generated on-demand during semantic search queries instead, improving initial ingestion performance.
- **Enhanced logging** - Added detailed logging throughout graph flushing, relationship processing, and embedding generation phases with stdout/stderr flushing to help identify bottlenecks.

## 2025-12-29

### Semantic Search & Qdrant Consistency Fix 🔍
- **Keyword Fallback for Semantic Seed Strategy** - Added a keyword-based seed discovery to `/semantic-seed-strategy`. If semantic search fails to find relevant nodes (e.g., due to stale embeddings), the strategy now looks for capitalized words in the question and finds matching nodes by name in Memgraph.
- **Fixed `/semantic-seed-strategy` inconsistency** - Resolved issues where semantic search would fail due to missing collections or path mismatches.
- **Automatic Collection Creation** - Qdrant collections are now automatically created on-demand during search if they don't exist.
- **Path Normalization** - Added `.expanduser()` to path resolution to handle `~` in repository paths consistently across ingestion and search.
- **Settings Synchronization** - The `settings.TARGET_REPO_PATH` is now explicitly updated during initialization to ensure all services use the same repository context.
- **Improved Error Resilience** - Added `_ensure_collection_exists()` helper to `vector_store.py` to prevent crashes when searching new repositories.

### Graph Ingestion & Relationship Fixes 🕸️
- **Expanded File Exclusion** - Added `.md` and `.txt` files to the global ignore list. These files are now skipped during both initial ingestion and real-time updates to focus exclusively on code structure.
- **Dotfile and Dotfolder Exclusion** - Updated `realtime_updater.py`, `graph_updater.py`, and `structure_processor.py` to ignore any files or directories starting with a dot (e.g., `.git`, `.vscode`, `.gitignore.swp`). This prevents noise from hidden files and temporary editor files from triggering unnecessary graph updates.
- **Real-time Semantic Updates** - `realtime_updater.py` now updates semantic embeddings in Qdrant for changed files, ensuring that `/semantic-seed-strategy` and other semantic tools stay in sync with code changes without requiring a full database refill.
- **Event Filtering in Real-time Updater** - `realtime_updater.py` now filters out non-modifying events like `closed_no_write` and ignores binary/media files (images, audio, etc.) as well as database journal files (`.db-journal`, `.sqlite-wal`, etc.) to reduce noise and redundant processing.
- **Configurable Debouncing** - Added `--debounce` CLI argument to `realtime_updater.py` to allow custom buffering delays (defaults to 20 seconds).
- **Fixed `realtime_updater.py` Debouncing** - Added 20-second buffering for file changes to prevent race conditions and redundant processing.
- **Improved Real-time Consistency** - `realtime_updater.py` now re-runs structure identification and definition processing before recalculating function calls, resolving "nodes may not exist" warnings for `CALLS` relationships.
- **Fixed CALLS relationship failures** - Resolved "nodes may not exist" warnings during ingestion by ensuring consistent repository isolation.
- **Fixed Unique Constraint Violations** - Resolved `mgclient.DatabaseError: Unable to commit due to unique constraint violation on :Project(name)` in `realtime_updater.py` and MCP server.
- **Absolute Path Normalization** - Standardized `MemgraphIngestor` to always resolve `repo_path` to an absolute path, ensuring consistent repository isolation.
- **Repo-Aware Real-time Updater** - Updated `realtime_updater.py` to use repository-specific filters for all deletion and re-calculation queries.
- **Repo-Aware Database Operations** - Updated `clean_database` and `export_graph_to_dict` in `graph_service.py` to respect repository isolation.
- **Built-in Node Creation** - Added automatic creation of nodes for built-in functions (e.g., `setTimeout`) when they are called.

### MCP Server Improvements 🔌
- **Improved Edit Confirmation Prompt** - The post-edit confirmation prompt now explicitly lists the files that were modified, created, or updated, providing better context for the user's decision.
- **Refined Edit Detection** - Updated `is_edit_operation_request` to use word boundaries, preventing false positives from class names like `ListEditor`.
- **Fixed `query_codebase` default strategy** - The `query_codebase` MCP tool now correctly uses `semantic-seed-strategy` by default.
- **Direct Strategy Execution** - Updated MCP server to call `run_semantic_seed_strategy` directly instead of passing slash commands to the agent.
- **Improved MCP Schema** - Added explicit default value for `strategy` in the MCP tool definition.

## 2025-11-30

### Connection Pool & Hang Fix - Read-Only Query Helper 🔌
- **Fixed 16-second hang after semantic search** - Eliminated connection pool exhaustion
  - Previous issue: semantic_search created its own MemgraphIngestor with `with` context
  - When context exited, connection closed, leaving main ingestor in broken state
  - Next query would hang trying to use dead connection
  
- **Added `execute_read_query()` helper** for lightweight read-only operations
  - Simple function in `graph_service.py` for queries that don't need ingestion machinery
  - Creates temporary connection, executes query immediately, closes cleanly
  - No buffering, no context managers, no side effects
  - Includes proper error handling and logging for Cypher syntax errors
  
- **Refactored semantic_search.py**
  - `semantic_code_search()` now uses `execute_read_query()` instead of MemgraphIngestor
  - `semantic_code_search_async()` now uses `execute_read_query()` instead of MemgraphIngestor
  - `get_function_source_code()` now uses `execute_read_query()` instead of MemgraphIngestor
  - All functions maintain repo_path filtering and parameter passing
  
- **Result**: No more connection conflicts, queries execute immediately without hanging

### Changes
- Modified `codebase_rag/services/graph_service.py`
  - Added `execute_read_query()` function for simple read-only Cypher queries
  - Returns list of result dictionaries (same format as MemgraphIngestor)
  - Includes error detection for Cypher syntax issues
  
- Rewrote `codebase_rag/tools/semantic_search.py`
  - Removed all `with MemgraphIngestor(...)` context managers
  - Updated both sync and async versions to use `execute_read_query()`
  - Simplified code and eliminated connection management complexity

### Robust Cypher Query Generation & Error Handling 🛡️
- **Fixed LLM-Generated Query Syntax Errors** - Made system resilient to LLM producing invalid Cypher
  - Fixed critical bug: `_clean_cypher_response()` was **adding** semicolons (Cypher doesn't support them!)
  - Now properly **removes** trailing semicolons from LLM output (common SQL carryover from training data)
  - Validates cleaned queries start with MATCH clause
  - Additional semicolon removal as safety net during validation
  
- **Improved Error Messages**
  - `_execute_query()` detects syntax errors and provides helpful hints
  - Query tool returns user-friendly error messages suggesting rephrasing
  - Logs helpful guidance about Cypher syntax when errors occur
  
- **Enhanced System Prompts**
  - Explicitly states "**NO SEMICOLONS**" at the top of both prompts
  - All code examples show queries without semicolons
  - Emphasizes Cypher syntax differences from SQL
  - Critical rules moved to the beginning
  
- **Edge Case Handling**
  - Handles markdown code blocks (``​` cypher ... ``​`)
  - Strips 'cypher' keyword if present
  - Removes backticks and other formatting artifacts
  - Graceful degradation when LLM generates slightly malformed queries

### Changes
- Modified `codebase_rag/services/llm.py`
  - Rewrote `_clean_cypher_response()` to remove (not add) semicolons
  - Enhanced `CypherGenerator.generate()` with validation and error handling
  
- Modified `codebase_rag/services/graph_service.py`
  - Updated `_execute_query()` to detect and explain Cypher syntax errors
  
- Modified `codebase_rag/tools/codebase_query.py`
  - Enhanced error handling with helpful messages for users
  
- Modified `codebase_rag/prompts.py`
  - Updated both CYPHER_SYSTEM_PROMPT and LOCAL_CYPHER_SYSTEM_PROMPT
  - Added explicit "NO SEMICOLONS" warning
  - Updated all examples to be semicolon-free

### Relative Path Resolution in Source Extraction 📂
- **Fixed Embedding Generation Failures** - Resolved relative paths during source code extraction
  - `extract_source_lines()` now accepts optional `repo_path` parameter
  - Automatically resolves relative paths (e.g., "arc_agi/io.py") to absolute using repo root
  - `extract_source_with_fallback()` propagates repo_path through to line-based extraction
  - `validate_source_location()` also supports path resolution
  - Updated `_extract_source_code()` in graph_updater to pass repo_path
  - Updated semantic_search tools to pass repo_path when extracting sources

- Fixes "Source file not found" warnings that occurred during embedding generation
- Enables successful completion of Pass 4 (embedding generation) for all functions

### Changes
- Modified `codebase_rag/utils/source_extraction.py`
  - Added `repo_path` parameter to `extract_source_lines()`
  - Added `repo_path` parameter to `extract_source_with_fallback()`
  - Added `repo_path` parameter to `validate_source_location()`
  - Implemented logic: `if not file_path.is_absolute() and repo_path: resolved_path = Path(repo_path) / file_path`

- Modified `codebase_rag/graph_updater.py`
  - Updated `_extract_source_code()` call to `extract_source_with_fallback()` with `repo_path=self.repo_path`

- Modified `codebase_rag/tools/semantic_search.py`
  - Updated `get_function_source_code()` to pass `repo_path=effective_repo_path` to both functions

## 2025-11-20

### Stable Point IDs in Qdrant (qualified_name based) 🎯
- **Synchronized Qdrant & Memgraph Identity** - Both databases now use qualified_name as primary identity
  - Qdrant point IDs generated from `hash(qualified_name)` instead of `hash(qualified_name + line_numbers)`
  - Function moves update existing vector (upsert replaces) instead of creating new one
  - Function renames create new vector with different ID (fresh embedding needed)
  - Memgraph's unique constraint on `qualified_name` perfectly aligned with Qdrant's point ID strategy
  - Eliminates orphaned vectors when functions change location

### Changes
- Added `get_stable_point_id(qualified_name)` function to `codebase_rag/vector_store.py`
  - Uses MD5 hash of qualified_name only (no line numbers)
  - Returns 31-bit integer for Qdrant point ID
  - Consistent across re-ingestions as long as qualified_name unchanged

- Updated `store_embedding()` in both local and HTTP implementations
  - Changed from `id=node_id` to `id=get_stable_point_id(qualified_name)`
  - Still stores `node_id` in payload for Memgraph cross-reference
  - Updated docstrings explaining the new strategy

### Migration Note
- Requires `--clean` flag on first ingestion with new code due to ID change
- After cleaning, vectors will be re-embedded with new IDs
- No data migration needed, old vectors will be orphaned but ignored

### Unified Clean Flag for Memgraph & Qdrant 🧹
- **Consistent Database Cleanup** - `--clean` flag now cleans both Memgraph and Qdrant
  - `--clean` deletes all nodes from Memgraph AND all vectors from Qdrant collection
  - Ensures both databases start fresh when re-ingesting a repository
  - Per-repository isolation: only cleans the specific repo's Qdrant collection
  - Gracefully handles cases where Qdrant is not available

### Changes
- Added `clean_collection(repo_path)` function to `codebase_rag/vector_store.py`
  - Works with both local Qdrant client and HTTP-based remote Qdrant
  - Supports per-repository collection cleaning via repo_path parameter
  - Logs success/failure of cleanup operations
  - Stub implementation for when Qdrant is not installed

- Updated `codebase_rag/main.py`
  - `--clean` flag now also calls `clean_collection(repo_path=target_repo_path)`
  - Shows "Cleaning databases..." message to indicate both are being cleaned
  - Gracefully handles cleanup errors without blocking the update process

### Tool Initialization with Repo Path Context ⚙️
- **Proper Repo Path Precedence in Semantic Tools** - Tools now correctly respect injected `repo_path` instead of hardcoding environment variable
  - Module-level `_repo_path_context` pattern for storing repo_path in tool creators
  - Tool creators accept `repo_path` parameter and set context for nested functions
  - Fallback chain in all functions: `provided_param > _repo_path_context > None`
  - `runtime.py` passes `repo_path` to all semantic tool creators
  - Ensures CLI `--repo-path` and MCP injection take precedence over `TARGET_REPO_PATH`

### Changes
- Updated `codebase_rag/tools/semantic_search.py`
  - Added module-level `_repo_path_context: str | None = None` storage
  - `semantic_code_search()` now accepts `repo_path` parameter
  - `semantic_code_search_async()` now accepts `repo_path` parameter
  - `get_function_source_code()` now accepts `repo_path` parameter
  - `create_semantic_search_tool()` now accepts `repo_path` and sets module context
  - `create_get_function_source_tool()` now accepts `repo_path` and sets module context
  - All functions use fallback chain with effective_repo_path variable

- Updated `codebase_rag/tools/enhanced_semantic_search.py`
  - `create_enhanced_semantic_search_tool()` now accepts `repo_path` parameter
  - Sets module context in semantic_search module for nested async calls

- Updated `codebase_rag/runtime.py`
  - `create_semantic_search_tool(repo_path=repo_path)` - passes repo_path from context
  - `create_enhanced_semantic_search_tool(repo_path=repo_path, console=console)` - order updated
  - `create_get_function_source_tool(repo_path=repo_path)` - passes repo_path from context

### Memgraph Repository-Specific Node Tagging 🏷️
- **Full Repo Isolation in Memgraph** - Both vector store AND graph database now support multi-repo isolation
  - All nodes automatically tagged with `_repo_path` property during ingestion
  - All graph queries automatically filtered by `_repo_path` to ensure isolation
  - Semantic search results validated to belong to current repo
  - Backward compatible: Default `repo_path="."` skips filtering for single-repo setups

### Changes
- Updated `codebase_rag/services/graph_service.py`
  - Added `repo_path` parameter to `MemgraphIngestor.__init__()`
  - Modified `ensure_node_batch()` to automatically add `_repo_path` to all node properties
  - Added `_get_repo_filter(node_var)` helper method to generate repo WHERE clause fragments
  - Normalizes repo_path to absolute path for consistency

- Updated `codebase_rag/main.py`
  - All `MemgraphIngestor` instantiations now pass `repo_path` parameter
  - Updated in: `main_async()`, `start()`, `export()`, `optimize()` commands

- Updated `codebase_rag/tools/semantic_search.py`
  - Both `semantic_code_search()` and `semantic_code_search_async()` pass `repo_path` to `MemgraphIngestor`
  - Cypher queries now include repo filter: `WHERE id(n) IN [...] AND n._repo_path = $repo_path`
  - Results are verified to belong to current repo before returning

- Created `utils/test_memgraph_repo_tagging.py` - Tests repo path normalization and filter generation

### Repository-Specific Vector Collections 🔧
- **Multi-Repository Support** - Each repository now has its own Qdrant collection
  - Collections named as `code_embeddings_{repo_path_hash}` (e.g., `code_embeddings_8e336968`)
  - Allows multiple repositories to share the same Qdrant instance without conflicts
  - Hash-based naming ensures deterministic, unique collection names
  - Seamlessly integrates with existing ingestion pipeline

### Changes
- Updated `codebase_rag/vector_store.py`
  - Added `get_collection_name(repo_path)` function for deterministic collection naming
  - Fixed Qdrant HTTP API endpoint for collection creation (PUT `/collections/{name}`)
  - Updated `store_embedding()` to accept optional `repo_path` parameter
  - Updated `search_embeddings()` to accept optional `repo_path` parameter
  - Both functions now use repo-specific collections automatically

- Updated `codebase_rag/tools/semantic_search.py`
  - Both `semantic_code_search()` and `semantic_code_search_async()` now pass `repo_path` to `search_embeddings()`
  - Uses `settings.TARGET_REPO_PATH` for collection lookup

- Updated `codebase_rag/graph_updater.py`
  - `store_embedding()` calls now include `repo_path=self.repo_path`
  - Ensures embeddings are stored in correct repo-specific collection during ingest

- Created `utils/test_collection_naming.py` - Validates deterministic collection naming
- Created `utils/test_repo_specific_collections.py` - End-to-end test of repo-specific storage and search

### Major Feature: Qdrant Semantic Search in CLI Query Mode 🎉
- **Semantic Search Integration** - CLI query mode now uses Qdrant vector database
  - Search for code by natural language intent (e.g., "find authentication functions")
  - Complements existing Memgraph graph queries
  - New tool: `semantic_search_by_intent` for intent-based code search
  - Hybrid search: Combine semantic (Qdrant) + structural (Memgraph) queries

- **Async/Await Support for Embeddings** ✅ (Fixed asyncio.run() error)
  - Added `embed_code_async()` for use in async contexts
  - Added `embed_code_batch_async()` for batch processing in async contexts
  - Added `semantic_code_search_async()` for async semantic search
  - Fixes: "asyncio.run() cannot be called from a running event loop" error
  - Works seamlessly with pydantic_ai tools and event loops

- **Enhanced Semantic Search Tool** - New `enhanced_semantic_search.py` with:
  - Better error messaging and configuration feedback
  - Rich console output for results
  - Integration with Memgraph for detailed node information
  - Support for external embedders (no local dependencies needed)

## 2025-11-18

### Features
- **Batch Embedding Processing**: Implemented batch API calls for 3.7x faster embeddings
  - Processes up to 100 embeddings per API call instead of one at a time
  - Reduces latency significantly (from 1.8/sec to ~6-7/sec)
  - Expected to reduce 909-function ingest time from ~500s to ~130s

- **Semantic Embedding Progress Logging**: Added real-time metrics during embedding generation
  - Shows processing rate (embeddings/second)
  - Displays count of embedded, failed, and skipped functions
  - Reports total time taken
  - Logs progress at regular intervals

### Fixes
- **Embedder Integration**: Fixed OpenRouter API endpoint construction to append `/embeddings`
- **External Embedder Support**: Updated dependency checks to recognize external embedder configuration
- **Vector Store HTTP Support**: Added HTTP-based Qdrant access for remote instances without Python client
- **Dynamic Vector Dimensions**: Made embedding dimensions configurable via `EMBED_DIMENSION` env variable

### Configuration
- Updated `EMBED_MODEL` to `google/gemini-embedding-001` (3072 dimensions)
- Updated `EMBED_DIMENSION=3072`
- Embeddings now work with external APIs without requiring torch/transformers

### Testing
- Created `utils/test_embedder_smoke.py` - Tests embedder with OpenRouter API
- Created `utils/test_vector_store_smoke.py` - Tests Qdrant connectivity
- Created `utils/test_semantic_search_smoke.py` - Tests full semantic search pipeline
- Created `utils/test_batch_embedding.py` - Verifies batch embeddings are 3.7x faster

## 2025-11-18

### Features
- **Batch Embedding Processing**: Implemented batch API calls for 3.7x faster embeddings
  - Processes up to 100 embeddings per API call instead of one at a time
  - Reduces latency significantly (from 1.8/sec to ~6-7/sec)
  - Expected to reduce 909-function ingest time from ~500s to ~130s

- **Semantic Embedding Progress Logging**: Added real-time metrics during embedding generation
  - Shows processing rate (embeddings/second)
  - Displays count of embedded, failed, and skipped functions
  - Reports total time taken
  - Logs progress at regular intervals

### Fixes
- **Embedder Integration**: Fixed OpenRouter API endpoint construction to append `/embeddings`
- **External Embedder Support**: Updated dependency checks to recognize external embedder configuration
- **Vector Store HTTP Support**: Added HTTP-based Qdrant access for remote instances without Python client
- **Dynamic Vector Dimensions**: Made embedding dimensions configurable via `EMBED_DIMENSION` env variable

### Configuration
- Updated `EMBED_MODEL` to `google/gemini-embedding-001` (3072 dimensions)
- Updated `EMBED_DIMENSION=3072`
- Embeddings now work with external APIs without requiring torch/transformers

### Testing
- Created `utils/test_embedder_smoke.py` - Tests embedder with OpenRouter API
- Created `utils/test_vector_store_smoke.py` - Tests Qdrant connectivity
- Created `utils/test_semantic_search_smoke.py` - Tests full semantic search pipeline
- Created `utils/test_batch_embedding.py` - Verifies batch embeddings are 3.7x faster

