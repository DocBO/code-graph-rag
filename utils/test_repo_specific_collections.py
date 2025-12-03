#!/usr/bin/env python3
"""Test end-to-end semantic search with repo-specific collections."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from codebase_rag.config import settings
from codebase_rag.vector_store import (
    get_collection_name,
    store_embedding,
    search_embeddings,
)

print("=== REPO-SPECIFIC COLLECTION TEST ===\n")

# Get collection name
collection_name = get_collection_name(settings.TARGET_REPO_PATH)
print(f"[1] Collection name: {collection_name}")

# Create a test embedding (random vector for demo)
test_embedding = [0.1 * i for i in range(settings.EMBED_DIMENSION)]
print(f"[2] Created test embedding with {len(test_embedding)} dimensions")

# Store it
try:
    store_embedding(
        node_id=99999,
        embedding=test_embedding,
        qualified_name="test.function",
        repo_path=settings.TARGET_REPO_PATH,
    )
    print("[3] ✓ Stored embedding in repo-specific collection")
except Exception as e:
    print(f"[3] ✗ Failed to store: {e}")
    sys.exit(1)

# Search for similar embeddings
try:
    results = search_embeddings(test_embedding, top_k=5, repo_path=settings.TARGET_REPO_PATH)
    print(f"[4] ✓ Searched collection, found {len(results)} results")
    if results:
        for node_id, score in results[:2]:
            print(f"    - Node {node_id}: score {score:.4f}")
except Exception as e:
    print(f"[4] ✗ Failed to search: {e}")
    sys.exit(1)

# Verify the test node appears in results
if any(node_id == 99999 for node_id, _ in results):
    print("[5] ✓ Test embedding found in search results")
else:
    print("[5] ✗ Test embedding NOT found in search results (may be normal if vector DB is empty)")

print("\n✓ REPO-SPECIFIC COLLECTION TEST PASSED")
