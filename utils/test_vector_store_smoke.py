#!/usr/bin/env python
"""Smoke test to verify HTTP Qdrant vector store works."""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from codebase_rag.config import settings
from codebase_rag.vector_store import search_embeddings, store_embedding


def test_vector_store():
    """Test the vector store with HTTP Qdrant."""

    print("=" * 60)
    print("VECTOR STORE (HTTP QDRANT) SMOKE TEST")
    print("=" * 60)

    # Print configuration
    print("\n[CONFIG]")
    print(f"Qdrant Host: {settings.QDRANT_HOST}")
    print(f"Qdrant Port: {settings.QDRANT_PORT}")
    print(f"Embedding Dimension: {settings.EMBED_DIMENSION}")

    # Create a sample embedding (using the dimension from config)
    embedding_dim = settings.EMBED_DIMENSION or 768
    sample_embedding = [0.1 * i for i in range(embedding_dim)]

    print("\n[STORING EMBEDDING]")
    print(f"Storing embedding with {len(sample_embedding)} dimensions...")

    try:
        store_embedding(
            node_id=99999,
            embedding=sample_embedding,
            qualified_name="test.sample_function",
        )
        print("✓ Successfully stored embedding")

        print("\n[SEARCHING EMBEDDINGS]")
        results = search_embeddings(sample_embedding, top_k=5)
        print(f"✓ Search returned {len(results)} results")
        if results:
            for node_id, score in results:
                print(f"  - Node ID: {node_id}, Score: {score:.6f}")

        print("\n" + "=" * 60)
        print("✓ VECTOR STORE SMOKE TEST PASSED")
        print("=" * 60)
        return True

    except Exception as e:
        print("\n✗ VECTOR STORE SMOKE TEST FAILED")
        print(f"Error: {type(e).__name__}: {e}")
        print("=" * 60)
        return False


if __name__ == "__main__":
    success = test_vector_store()
    sys.exit(0 if success else 1)
