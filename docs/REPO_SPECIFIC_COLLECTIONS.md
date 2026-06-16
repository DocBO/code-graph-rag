# Repository-Specific Vector Collections

## Overview

The semantic search system now supports multiple repositories sharing a single Qdrant vector database instance. Each repository automatically gets its own isolated collection based on its file path.

## How It Works

### Collection Naming

Collections are named using a deterministic hash-based approach:

```
Collection Name = code_embeddings_{MD5_HASH_OF_REPO_PATH}[:8]
```

**Examples:**
- `/home/oliver/github/code-graph-rag` → `code_embeddings_8e336968`
- `/home/oliver/other-repo` → `code_embeddings_febc9344`
- Same path always produces same collection name (deterministic)

### Automatic Creation

When embeddings are stored or searched:

1. The `TARGET_REPO_PATH` setting is resolved to an absolute path
2. An MD5 hash of the path is computed (first 8 characters)
3. Collection name is generated: `code_embeddings_{hash}`
4. If collection doesn't exist, it's created automatically with:
   - Vector size: `EMBED_DIMENSION` from config (default: 3072)
   - Distance metric: Cosine similarity
   - Auto-indexed for efficient search

## Usage

### Automatic (Recommended)

The system works automatically during normal operations:

```python
from codebase_rag.vector_store import store_embedding, search_embeddings

# Automatically uses repo-specific collection
store_embedding(node_id, embedding, qualified_name)
search_results = search_embeddings(query_embedding, top_k=5)
```

### Explicit (Advanced)

To work with a specific repository's collection:

```python
from pathlib import Path

# Use specific repo path
store_embedding(
    node_id=123,
    embedding=vector,
    qualified_name="module.function",
    repo_path="/home/user/my-repo"  # Optional: uses TARGET_REPO_PATH if None
)

results = search_embeddings(
    query_embedding=vector,
    top_k=5,
    repo_path="/home/user/my-repo"  # Optional: uses TARGET_REPO_PATH if None
)
```

## Configuration

### In `.env`

The system respects standard settings:

```env
# Qdrant connection
QDRANT_HOST=localhost
QDRANT_PORT=6333
QDRANT_API_KEY=          # Optional

# Embedding configuration
EMBED_DIMENSION=3072     # Must match vector size used
EMBED_ENDPOINT=https://openrouter.ai/api/v1
EMBED_API_KEY=...
EMBED_MODEL=google/gemini-embedding-001

# Repository path
TARGET_REPO_PATH=.       # Defaults to current directory
```

### Via Python Settings

```python
from codebase_rag.config import settings

print(settings.TARGET_REPO_PATH)  # Repository being analyzed
print(settings.EMBED_DIMENSION)   # Vector dimensions (3072)
```

## Collection Management

### View Collections

```bash
# List all collections
curl http://localhost:6333/collections | jq '.result.collections[].name'

# Check specific collection
curl http://localhost:6333/collections/code_embeddings_8e336968
```

### Get Collection Name Programmatically

```python
from codebase_rag.vector_store import get_collection_name

collection_name = get_collection_name()  # Uses TARGET_REPO_PATH
# or
collection_name = get_collection_name("/specific/repo/path")
```

### Delete a Collection

```bash
# Delete a specific collection
curl -X DELETE http://localhost:6333/collections/code_embeddings_8e336968

# Delete ALL code_embeddings collections using the utility script
python utils/delete_all_collections.py
```

## Benefits

✅ **Multi-Repo Support** - Run multiple codebases with one Qdrant instance  
✅ **Isolation** - Embeddings from different repos don't interfere  
✅ **Deterministic** - Same path always maps to same collection  
✅ **Automatic** - No manual configuration needed  
✅ **Scalable** - Add new repos without setup overhead  

## Implementation Details

### File Changes

**`codebase_rag/vector_store.py`**
- Added `get_collection_name(repo_path)` function
- Updated `store_embedding()` signature: added `repo_path` parameter
- Updated `search_embeddings()` signature: added `repo_path` parameter
- Fixed HTTP API endpoint for collection creation

**`codebase_rag/tools/semantic_search.py`**
- Both sync and async search functions pass `repo_path` to `search_embeddings()`

**`codebase_rag/graph_updater.py`**
- `store_embedding()` calls include `repo_path=self.repo_path`

### Function Signatures

```python
def get_collection_name(repo_path: str | Path | None = None) -> str:
    """Generate repository-specific collection name."""

def store_embedding(
    node_id: int,
    embedding: list[float],
    qualified_name: str,
    repo_path: str | Path | None = None  # NEW parameter
) -> None:
    """Store embedding in repo-specific collection."""

def search_embeddings(
    query_embedding: list[float],
    top_k: int = 5,
    repo_path: str | Path | None = None  # NEW parameter
) -> list[tuple[int, float]]:
    """Search in repo-specific collection."""
```

## Troubleshooting

### Collection Not Found Error

**Problem:** "Collection doesn't exist" error even after ingesting

**Solution:** Ensure `TARGET_REPO_PATH` is consistent between operations:
```python
from codebase_rag.config import settings
print(f"Current repo path: {settings.TARGET_REPO_PATH}")
```

### Different Collections for Same Repo

**Problem:** Same repo creates multiple collections

**Solution:** Check for path normalization issues:
```python
from pathlib import Path
from codebase_rag.vector_store import get_collection_name

path1 = get_collection_name("./repo")
path2 = get_collection_name("/absolute/repo")  # Different hashes!
path3 = get_collection_name(Path("./repo").resolve())  # Use absolute paths
```

### Dimension Mismatch

**Problem:** "Vector dimension error: expected dim: 3072, got 4096"

**Solution:** Collections use `EMBED_DIMENSION` setting. If you change it:
1. Update `.env`: `EMBED_DIMENSION=3072`
2. Delete old collection: `curl -X DELETE http://localhost:6333/collections/code_embeddings_HASH`
3. Re-run ingest to create new collection with correct dimension

## Testing

Run the test suite:

```bash
# Test collection naming determinism
python utils/test_collection_naming.py

# Test end-to-end storage and search
python utils/test_repo_specific_collections.py
```

Expected output:
```
✓ All collection naming tests passed!
✓ REPO-SPECIFIC COLLECTION TEST PASSED
```
