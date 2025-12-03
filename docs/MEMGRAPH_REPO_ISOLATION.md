# Memgraph Repository-Specific Node Tagging

## Overview

The Memgraph graph database now supports repository-specific isolation through automatic node tagging. Each repository's code is tagged with its own `_repo_path` property, and all queries automatically filter by this property to ensure data isolation.

This complements the existing Qdrant vector collection isolation, providing end-to-end multi-repository support in a single knowledge graph database.

## How It Works

### Automatic Node Tagging

Every node created during ingestion is automatically tagged with a `_repo_path` property:

```
Node: Function
  Properties:
    - qualified_name: "module.MyClass.method"
    - start_line: 42
    - end_line: 55
    + _repo_path: "/absolute/path/to/repo"  ← Added automatically
```

### Repository Path Normalization

The repo path is normalized to an absolute path for consistency:

```python
# Input: "." or "./my-repo" or relative path
# Stored: "/absolute/path/to/repo"
```

This ensures that different ways of referring to the same repository (e.g., `.`, `./`, `/absolute/path`) all map to the same normalized path.

### Automatic Query Filtering

When you query the database, the Memgraph ingestor automatically adds a WHERE clause filter:

**Example Query (before filtering):**
```cypher
MATCH (n)
WHERE id(n) IN [1, 2, 3]
RETURN n.qualified_name
```

**Automatically becomes (after filtering):**
```cypher
MATCH (n)
WHERE (n._repo_path = '/absolute/path/to/repo') AND id(n) IN [1, 2, 3]
RETURN n.qualified_name
```

## Usage

### Automatic (Recommended)

Node tagging and query filtering happen automatically:

```python
from codebase_rag.services.graph_service import MemgraphIngestor

# Create ingestor with repo path
with MemgraphIngestor(
    host="localhost",
    port=7687,
    repo_path="/home/user/my-repo"  # Automatically tags all nodes
) as ingestor:
    # All queries automatically filtered by repo
    results = ingestor._execute_query(
        "MATCH (n) WHERE id(n) IN [1, 2, 3] RETURN n"
    )
    # Only returns nodes from /home/user/my-repo
```

### Configuration

**In `main.py`:**
```python
with MemgraphIngestor(
    host=settings.MEMGRAPH_HOST,
    port=settings.MEMGRAPH_PORT,
    repo_path=target_repo_path,  # Pass the repo path
) as ingestor:
    updater = GraphUpdater(ingestor, repo_path, parsers, queries)
    updater.run()
```

**In Command-Line:**
```bash
python -m codebase_rag.main start --repo-path /path/to/repo --update-graph
```

## Architecture

### MemgraphIngestor Changes

```python
class MemgraphIngestor:
    def __init__(
        self, 
        host: str, 
        port: int, 
        batch_size: int = 1000,
        repo_path: str | Path | None = None  # NEW parameter
    ):
        self.repo_path = str(Path(repo_path).resolve())  # Normalize to absolute
```

### Node Creation with Repo Tagging

```python
def ensure_node_batch(self, label: str, properties: dict[str, Any]) -> None:
    """Adds a node to the buffer. Automatically adds repo_path to properties."""
    # Add _repo_path to every node
    properties_with_repo = {**properties, "_repo_path": self.repo_path}
    self.node_buffer.append((label, properties_with_repo))
```

### Query Filtering

```python
def _get_repo_filter(self, node_var: str = "n") -> str:
    """Get a Cypher WHERE clause filter for the current repo."""
    if self.repo_path == ".":  # Default, no filtering
        return ""
    # Return: "(n._repo_path = '/path/to/repo') AND "
    return f"({node_var}._repo_path = '{self.repo_path}') AND "
```

## Multi-Repository Scenarios

### Scenario 1: Separate Analysis Sessions

Each session uses its own repo path:

```bash
# Session 1: Analyze repo-a
python -m codebase_rag.main start --repo-path /home/user/repo-a --update-graph

# Session 2: Analyze repo-b (uses same Memgraph instance)
python -m codebase_rag.main start --repo-path /home/user/repo-b --update-graph
```

**Result:**
- Memgraph contains nodes from both repos
- All queries automatically filtered by `_repo_path`
- No cross-repo contamination

### Scenario 2: Cleaning Database

When starting fresh:

```bash
# Clean old data and ingest new repo
python -m codebase_rag.main start \
  --repo-path /home/user/new-repo \
  --update-graph \
  --clean
```

- Cleans entire database (removes all repos)
- Ingest new repo with fresh data

## Benefits

✅ **True Multi-Repo Support** - Analyze multiple repos in single database  
✅ **Automatic Filtering** - No manual WHERE clauses needed  
✅ **Data Isolation** - Different repos don't interfere  
✅ **Backward Compatible** - Default `repo_path="."` behaves like before  
✅ **Transparent** - Works automatically without changing code  

## Implementation Details

### File Changes

**`codebase_rag/services/graph_service.py`**
- Added `repo_path` parameter to `__init__`
- Modified `ensure_node_batch()` to add `_repo_path` property
- Added `_get_repo_filter()` helper method

**`codebase_rag/main.py`**
- Updated all `MemgraphIngestor()` instantiations to pass `repo_path`
- Affects: `main_async()`, `start()`, `export()`, `optimize()`

**`codebase_rag/tools/semantic_search.py`**
- Both sync and async search functions pass `repo_path`
- Queries include repo filter in WHERE clause
- Validates results belong to current repo

### Cypher Query Pattern

All queries now follow this pattern:

```cypher
MATCH (n) -[r]-> (m)
WHERE <repo_filter> original_conditions
RETURN ...
```

Where `<repo_filter>` is either:
- `(n._repo_path = '/path/to/repo') AND ` - For specific repo
- `` (empty) - For default/backward compatibility

## Querying by Repo

### Get Nodes from Specific Repo

```python
query = """
MATCH (n)
WHERE n._repo_path = $repo_path
RETURN n.qualified_name, labels(n)
"""
results = ingestor._execute_query(query, {"repo_path": "/home/user/repo"})
```

### Count Nodes per Repo

```cypher
MATCH (n)
WHERE n._repo_path IS NOT NULL
RETURN n._repo_path, count(*) as node_count
GROUP BY n._repo_path
```

### Find Cross-Repo References

```cypher
MATCH (a) -[r]-> (b)
WHERE a._repo_path <> b._repo_path
RETURN a._repo_path, r.type, b._repo_path
```

## Troubleshooting

### Nodes Not Appearing

**Problem:** Ingested nodes not visible in queries

**Solution:** Check that `repo_path` matches:
```python
from codebase_rag.config import settings
print(f"Expected repo_path: {settings.TARGET_REPO_PATH}")
```

### Mixed Repos in Results

**Problem:** Results from multiple repos despite filtering

**Solution:** Ensure ingestor was created with correct `repo_path`:
```python
print(f"Ingestor repo_path: {ingestor.repo_path}")
```

### Database Growing Too Large

**Problem:** Multiple repos accumulating in database

**Solution:** Use `--clean` flag to clear database before new ingestion:
```bash
python -m codebase_rag.main start --repo-path /path/to/repo --update-graph --clean
```

Or manually delete repo's nodes:
```cypher
MATCH (n)
WHERE n._repo_path = '/path/to/old/repo'
DETACH DELETE n
```

## Testing

Run the repo tagging test:

```bash
python utils/test_memgraph_repo_tagging.py
```

Expected output:
```
✓ MEMGRAPH REPO TAGGING TEST PASSED

📝 Summary:
   - All nodes will be tagged with _repo_path property
   - Queries will filter by _repo_path to isolate repos
   - Default repo_path='.' skips filtering (backward compatible)
```

## Performance Notes

- `_repo_path` property adds negligible storage overhead
- WHERE clause filtering is fast (indexed property lookup)
- No performance impact on single-repo setups (filtering disabled for `repo_path="."`)

## Future Enhancements

- **Index on _repo_path**: Add database index for faster repo filtering
- **Repo Statistics**: Track nodes/relationships per repo
- **Repo Management CLI**: Commands to list, delete, migrate repos
- **Repo Tags**: Additional metadata (language, framework, version) per repo
