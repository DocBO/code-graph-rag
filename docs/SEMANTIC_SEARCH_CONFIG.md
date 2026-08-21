# Semantic Search & Embedding Configuration - Test Results

## Configuration Status ✓

All semantic features are working correctly with external APIs configured in `.env`:

### Embedder Configuration
- **Endpoint**: https://openrouter.ai/api/v1
- **Model**: qwen/qwen3-embedding-8b
- **Dimension**: 4096
- **Status**: ✓ Working (generates 4096-dimensional embeddings)

### Qdrant Vector Store Configuration
- **Host**: localhost
- **Port**: 6333
- **Status**: ✓ Working (stores and retrieves embeddings)

### Ingestion
- **Status**: ✓ Working (generates embeddings for all functions/methods)
- **No longer requires**: torch, transformers, or local Unixcoder model

## What Works

### 1. Embedder (`codebase_rag/embedder.py`)
- ✓ Generates embeddings using OpenRouter's Qwen3 API
- ✓ Properly constructs `/embeddings` endpoint
- ✓ Returns 4096-dimensional vectors

### 2. Vector Store (`codebase_rag/vector_store.py`)
- ✓ Supports both local Python client and HTTP-based Qdrant
- ✓ Uses configured `EMBED_DIMENSION` (4096)
- ✓ Stores embeddings with node metadata
- ✓ Performs semantic searches

### 3. Dependencies Check (`codebase_rag/utils/dependencies.py`)
- ✓ Recognizes external embedder configuration
- ✓ Allows semantic features with API keys only

### 4. Ingestion (`codebase_rag/graph_updater.py`)
- ✓ Generates semantic embeddings during ingest
- ✓ No longer skips when local dependencies missing

## Test Smoke Tests Created

Three smoke tests verify the implementation:

1. **`utils/test_embedder_smoke.py`**
   - Tests embedder with OpenRouter API
   - Verifies dimension configuration

2. **`utils/test_vector_store_smoke.py`**
   - Tests Qdrant connectivity and storage
   - Verifies HTTP API fallback support

3. **`utils/test_semantic_search_smoke.py`**
   - Tests full semantic search pipeline
   - Verifies embeddings are generated and searchable

## Configuration in .env

```properties
# Semantic embedding (optional external provider + remote Qdrant)
EMBED_ENDPOINT=https://openrouter.ai/api/v1
EMBED_API_KEY=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
EMBED_MODEL=qwen/qwen3-embedding-8b
EMBED_DIMENSION=4096
EMBED_RATE_LIMIT_RPM=60
EMBED_MAX_RETRIES=3
EMBED_RETRY_BACKOFF=2.0
QDRANT_HOST=localhost
QDRANT_PORT=6333
QDRANT_API_KEY=
```

### Rate limiting & retry (added 2026-08-12)

- `EMBED_RATE_LIMIT_RPM` — max external embedder requests per minute (default `60`). A shared token-bucket limiter spaces requests so full re-embeds (watcher Pass 4, MCP `start_updater`, CLI `--only-embedding`) never flood the endpoint.
- `EMBED_MAX_RETRIES` — retries on transient `429`/`5xx` responses (default `3`). The server's `Retry-After` header is honored when present, otherwise exponential backoff is used.
- `EMBED_RETRY_BACKOFF` — base backoff seconds (default `2.0`), doubled per retry.
- If a batch embed still fails after retries, Pass 4 falls back to per-item embedding so only genuinely failing items are skipped instead of the whole chunk.

## Files Modified

1. **`codebase_rag/embedder.py`** - Fixed endpoint URL construction for OpenRouter
2. **`codebase_rag/config.py`** - Added `EMBED_DIMENSION` setting
3. **`codebase_rag/utils/dependencies.py`** - Updated to recognize external embedder config
4. **`codebase_rag/vector_store.py`** - Added HTTP fallback for remote Qdrant
