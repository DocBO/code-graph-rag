#!/usr/bin/env python
"""Test async embedder functionality."""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from codebase_rag.embedder import embed_code_async, embed_code_batch_async
from codebase_rag.config import settings


async def test_async_embedder():
    """Test async embedding functions."""
    
    print("=" * 70)
    print("ASYNC EMBEDDER TEST")
    print("=" * 70)
    
    # Check configuration
    print("\n[CONFIG]")
    print(f"External embedder: {settings.EMBED_ENDPOINT}")
    print(f"Embedding model: {settings.EMBED_MODEL}")
    print(f"Embedding dimension: {settings.EMBED_DIMENSION}")
    
    sample_codes = [
        "def hello_world():\n    print('Hello, World!')\n    return 42",
        "def fibonacci(n):\n    if n <= 1:\n        return n\n    return fibonacci(n-1) + fibonacci(n-2)",
        "class Calculator:\n    def add(self, a, b):\n        return a + b",
    ]
    
    # Test 1: Single async embedding
    print("\n[TEST 1: Single Async Embedding]")
    try:
        embedding = await embed_code_async(sample_codes[0])
        print(f"✓ Generated embedding with {len(embedding)} dimensions")
        print(f"  First 5 values: {embedding[:5]}")
    except Exception as e:
        print(f"✗ Error: {type(e).__name__}: {e}")
        return False
    
    # Test 2: Batch async embeddings
    print("\n[TEST 2: Batch Async Embeddings]")
    try:
        embeddings = await embed_code_batch_async(sample_codes, batch_size=2)
        print(f"✓ Generated {len(embeddings)} embeddings")
        for i, emb in enumerate(embeddings):
            print(f"  Embedding {i+1}: {len(emb)} dimensions")
    except Exception as e:
        print(f"✗ Error: {type(e).__name__}: {e}")
        return False
    
    # Test 3: Multiple async calls in a single event loop
    print("\n[TEST 3: Multiple Async Calls in Event Loop]")
    try:
        results = await asyncio.gather(
            embed_code_async(sample_codes[0]),
            embed_code_async(sample_codes[1]),
            embed_code_async(sample_codes[2]),
        )
        print(f"✓ Generated {len(results)} embeddings concurrently")
        for i, emb in enumerate(results):
            print(f"  Embedding {i+1}: {len(emb)} dimensions")
    except Exception as e:
        print(f"✗ Error: {type(e).__name__}: {e}")
        return False
    
    print("\n" + "=" * 70)
    print("✓ ASYNC EMBEDDER TEST PASSED")
    print("=" * 70)
    return True


if __name__ == "__main__":
    success = asyncio.run(test_async_embedder())
    sys.exit(0 if success else 1)
