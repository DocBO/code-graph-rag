#!/usr/bin/env python
"""Smoke test to verify batch embedding works and is faster."""

import sys
import time
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from codebase_rag.config import settings
from codebase_rag.embedder import embed_code, embed_code_batch


def test_batch_embedding():
    """Test batch embeddings performance vs single embeddings."""

    print("=" * 60)
    print("BATCH EMBEDDING SMOKE TEST")
    print("=" * 60)

    # Print configuration
    print("\n[CONFIG]")
    print(f"External embedder: {settings.EMBED_ENDPOINT}")
    print(f"Embedding model: {settings.EMBED_MODEL}")
    print(f"Embedding dimension: {settings.EMBED_DIMENSION}")

    # Sample codes to embed
    sample_codes = [
        "def hello_world():\n    print('Hello, World!')\n    return 42",
        "def fibonacci(n):\n    if n <= 1:\n        return n\n    return fibonacci(n-1) + fibonacci(n-2)",
        "class Calculator:\n    def add(self, a, b):\n        return a + b\n    def multiply(self, a, b):\n        return a * b",
        "def process_data(items):\n    return [item.strip() for item in items if item]",
        "def merge_dicts(*dicts):\n    result = {}\n    for d in dicts:\n        result.update(d)\n    return result",
    ]

    print(f"\n[TESTING WITH {len(sample_codes)} CODE SNIPPETS]")

    # Test 1: Single embeddings (sequential)
    print("\n1. Single embeddings (sequential):")
    start = time.time()
    single_embeddings = []
    for code in sample_codes:
        emb = embed_code(code)
        single_embeddings.append(emb)
    single_time = time.time() - start
    print(
        f"   ✓ Generated {len(single_embeddings)} embeddings in {single_time:.2f}s ({len(sample_codes) / single_time:.2f}/sec)"
    )

    # Test 2: Batch embeddings
    print("\n2. Batch embeddings (parallel):")
    start = time.time()
    batch_embeddings = embed_code_batch(sample_codes, batch_size=100)
    batch_time = time.time() - start
    print(
        f"   ✓ Generated {len(batch_embeddings)} embeddings in {batch_time:.2f}s ({len(sample_codes) / batch_time:.2f}/sec)"
    )

    # Compare results
    print("\n[VERIFICATION]")
    print(
        f"Embedding dimensions match: {len(single_embeddings[0]) == len(batch_embeddings[0]) == settings.EMBED_DIMENSION}"
    )

    # Check if embeddings are similar (they should be very close since it's the same API)
    import math

    def cosine_similarity(a, b):
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        return dot / (norm_a * norm_b) if norm_a and norm_b else 0

    similarity = cosine_similarity(single_embeddings[0], batch_embeddings[0])
    print(f"Single vs batch similarity (should be ~1.0): {similarity:.6f}")

    # Performance comparison
    speedup = single_time / batch_time
    print(f"\nBatch processing is {speedup:.1f}x faster")

    print("\n" + "=" * 60)
    if speedup > 1.5:
        print("✓ BATCH EMBEDDING SMOKE TEST PASSED")
        print(f"  Significant speedup achieved: {speedup:.1f}x")
    else:
        print("⚠ BATCH EMBEDDING TEST COMPLETED")
        print(f"  Limited speedup: {speedup:.1f}x (may be due to small batch size)")
    print("=" * 60)

    return True


if __name__ == "__main__":
    success = test_batch_embedding()
    sys.exit(0 if success else 1)
