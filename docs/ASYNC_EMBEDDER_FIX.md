# Fix: asyncio.run() in Async Context Error

## Problem
When using semantic search from the CLI's interactive chat mode (which runs on an event loop), the embedder was throwing:
```
asyncio.run() cannot be called from a running event loop
```

This is because `embed_code()` was using `asyncio.run()` internally, which doesn't work inside an already-running async context (like pydantic_ai tools).

## Root Cause
The embedder functions were designed as sync functions that wrapped async code with `asyncio.run()`:
```python
def embed_code(code: str) -> list[float]:
    if _use_external_embedder():
        import asyncio
        return asyncio.run(_embed_external(code))  # ❌ Fails if called from async context
    return _embed_local(code)
```

When pydantic_ai tools run in an event loop, calling `asyncio.run()` raises an error because you can't create a new event loop when one is already running.

## Solution
Created separate async and sync variants for all embedding functions:

### 1. **Sync Variants** (for standalone/script usage)
- `embed_code()` - Single embedding
- `embed_code_batch()` - Batch embeddings
- Smart detection of event loop availability

### 2. **Async Variants** (for use in pydantic_ai tools)
- `embed_code_async()` - Single embedding (async)
- `embed_code_batch_async()` - Batch embeddings (async)
- No `asyncio.run()` - directly awaitable

### 3. **Semantic Search Variants**
- `semantic_code_search()` - Sync version
- `semantic_code_search_async()` - Async version

## Implementation

### Embedder Changes
```python
# Async variants for use in event loops
async def embed_code_async(code: str, max_length: int = 512) -> list[float]:
    if _use_external_embedder():
        return await _embed_external(code, max_length=max_length)
    return _embed_local(code, max_length=max_length)

# Sync variant with smart event loop detection
def embed_code(code: str, max_length: int = 512) -> list[float]:
    if _use_external_embedder():
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            raise RuntimeError("Use embed_code_async() instead...")
        except RuntimeError as e:
            if "no running event loop" in str(e).lower():
                return asyncio.run(_embed_external(code, max_length=max_length))
            raise
    return _embed_local(code, max_length=max_length)
```

### Tool Updates
The semantic search tools now use the async variants:
```python
async def semantic_search_functions(query: str, top_k: int = 5) -> str:
    # Uses async version because pydantic_ai tools are async
    results = await semantic_code_search_async(query, top_k)
    ...
```

## Testing
Created `utils/test_async_embedder.py` which verifies:
✅ Single async embeddings work
✅ Batch async embeddings work
✅ Multiple concurrent embeddings work in the same event loop
✅ Dimensions are correct (3072)

## Benefits
- ✅ Fixes "asyncio.run() cannot be called from a running event loop" error
- ✅ Works seamlessly with pydantic_ai and other async frameworks
- ✅ Backward compatible (sync functions still work for scripts)
- ✅ Enables concurrent embedding generation
- ✅ No performance degradation

## Usage

### In Sync Context (scripts)
```python
from codebase_rag.embedder import embed_code, embed_code_batch

embedding = embed_code("def hello(): pass")
embeddings = embed_code_batch(["def foo(): pass", "def bar(): pass"])
```

### In Async Context (pydantic_ai tools)
```python
from codebase_rag.embedder import embed_code_async, embed_code_batch_async

async def my_tool(query: str):
    embedding = await embed_code_async(query)
    results = await search_embeddings(embedding)
    return results
```

## Related Files
- `codebase_rag/embedder.py` - Async variants added
- `codebase_rag/tools/semantic_search.py` - Uses async variants
- `codebase_rag/tools/enhanced_semantic_search.py` - Uses async variants
- `utils/test_async_embedder.py` - Test coverage
