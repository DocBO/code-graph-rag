# Graph-RAG Quality Assessment

## 2026-01-09

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
