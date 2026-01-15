# Graph-RAG Quality Assessment

## 2026-01-14

### Feature: Iterative Retrieval Strategy
1. **Reason for triggering**: User noted that complex cross-file queries often failed due to "Insufficient context" in the first pass.
2. **Expected outcome**: The RAG engine should automatically resolve missing dependencies identified by the LLM and pull them into a secondary retrieval round.
3. **Real outcome**: Re-engineered `semantic-seed-strategy` into a multi-round iterative loop. Round 1 context is analyzed for "Missing Concepts"; Round 2/3 then uses these concepts as specific search queries in the vector store and graph.
4. **Score of success**: 6/6 - Dramatically improved the system's ability to answer "How does X use Y" when X and Y are in distant parts of the codebase.

## 2026-01-09

### Fix: Repository Isolation and Path Normalization
1. **Reason for triggering**: User reported "repository mixing" where queries for one project (addibase) returned results from another (elysia).
2. **Expected outcome**: Results should be strictly confined to the repository specified in `--repo-path`.
3. **Real outcome**: Standardized all path resolutions to use absolute paths with `Path.expanduser().resolve()`. Injected mandatory isolation rules (`n._repo_path = $repo_path`) into LLM prompts and automated parameter injection in `MemgraphIngestor.fetch_all`. Updated manual tool queries to include the filter.
4. **Score of success**: 6/6 - Data leakage between repositories is now prevented at the architectural level.

### Fix: Type Inference Infinite Recursion & Phase 4 Optimization
1. **Reason for triggering**: User reported process hang during ingestion of `addibase` repository.
2. **Expected outcome**: Ingestion should complete efficiently, including phase 4 (semantic embeddings).
3. **Real outcome**: Identified infinite recursion in `_analyze_self_assignments` due to circular type references. Implemented a `visited` set recursion guard. Restored Phase 4 with batch processing optimizations.
4. **Score of success**: 6/6 - Ingestion now completes on `addibase` and semantic embeddings are correctly generated.

## 2025-12-29

### Fix: CALLS relationship failures & Real-time Updater Consistency
1. **Reason for triggering**: User reported "Failed to create CALLS relationships" and unique constraint violations in `realtime_updater.py`.
2. **Expected outcome**: Real-time updates should be consistent and not interfere with other repositories in the same database.
3. **Real outcome**: Identified that `realtime_updater.py` was using global queries without repository filters. Standardized all operations to use absolute paths for `_repo_path` and added repository-specific filters to all `DELETE` and `MATCH` operations.
4. **Score of success**: 6/6 - All identified causes were addressed and verified.

### Fix: Semantic Search Inconsistency
1. **Reason for triggering**: User reported `/semantic-seed-strategy` not working consistently.
2. **Expected outcome**: Semantic search should work reliably even for new repositories or paths with `~`.
3. **Real outcome**: Fixed Qdrant collection auto-creation and path normalization.
4. **Score of success**: 6/6 - Verified with a dedicated test script.

### Fix: MCP `query_codebase` default strategy
1. **Reason for triggering**: User reported `query_codebase` was not using `semantic-seed-strategy` as default.
2. **Expected outcome**: `query_codebase` should use the optimized semantic seed strategy by default.
3. **Real outcome**: Identified that the MCP server was incorrectly passing slash commands to the agent instead of executing the strategy directly. Fixed by calling `run_semantic_seed_strategy` in the MCP context.
4. **Score of success**: 6/6 - Implementation now matches documentation and user expectations.
