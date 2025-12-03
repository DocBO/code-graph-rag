#!/usr/bin/env python
"""Smoke test to verify semantic search works with configured embedder and Qdrant."""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from codebase_rag.config import settings
from codebase_rag.embedder import embed_code
from codebase_rag.vector_store import search_embeddings


def test_semantic_search():
    """Test semantic search with configured embedder and Qdrant."""

    print("=" * 60)
    print("SEMANTIC SEARCH SMOKE TEST")
    print("=" * 60)

    # Print configuration
    print("\n[CONFIG]")
    print(f"External embedder: {settings.EMBED_ENDPOINT}")
    print(f"Embedding model: {settings.EMBED_MODEL}")
    print(f"Embedding dimension: {settings.EMBED_DIMENSION}")
    print(f"Qdrant endpoint: {settings.QDRANT_HOST}:{settings.QDRANT_PORT}")

    # Test queries
    test_queries = [
        "configuration loading from environment",
        "graph database connection",
        "function parsing and extraction",
    ]

    print("\n[SEMANTIC SEARCHES]")
    all_passed = True

    for query in test_queries:
        print(f"\nQuery: '{query}'")
        try:
            # Step 1: Generate embedding for query
            print("  1. Generating embedding...")
            query_embedding = embed_code(query)
            print(
                f"     ✓ Query embedding generated ({len(query_embedding)} dimensions)"
            )

            # Step 2: Search in Qdrant
            print("  2. Searching in Qdrant...")
            search_results = search_embeddings(query_embedding, top_k=3)

            if search_results:
                print(f"     ✓ Found {len(search_results)} results:")
                for i, (node_id, score) in enumerate(search_results, 1):
                    print(f"       {i}. Node ID: {node_id}, Score: {score:.4f}")
            else:
                print("     ⚠ No results found in Qdrant")

        except Exception as e:
            print(f"  ✗ Search failed: {type(e).__name__}: {e}")
            all_passed = False

    print("\n" + "=" * 60)
    if all_passed:
        print("✓ SEMANTIC SEARCH SMOKE TEST PASSED")
    else:
        print("✗ SEMANTIC SEARCH SMOKE TEST FAILED")
    print("=" * 60)
    return all_passed


if __name__ == "__main__":
    success = test_semantic_search()
    sys.exit(0 if success else 1)
