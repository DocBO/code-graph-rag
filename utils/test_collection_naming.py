#!/usr/bin/env python3
"""Test that collection names are generated correctly from repo paths."""

import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from codebase_rag.vector_store import get_collection_name

# Test 1: Current repo
current_repo = Path(".").resolve()
collection_name = get_collection_name(current_repo)
print(f"[Test 1] Current repo: {current_repo}")
print(f"         Collection: {collection_name}")
assert collection_name.startswith("code_embeddings_"), f"Unexpected format: {collection_name}"

# Test 2: Different repo path
other_repo = Path("/home/oliver/other-repo").resolve()
other_collection = get_collection_name(other_repo)
print(f"\n[Test 2] Other repo: {other_repo}")
print(f"         Collection: {other_collection}")
assert other_collection.startswith("code_embeddings_"), f"Unexpected format: {other_collection}"
assert other_collection != collection_name, "Different repos should have different collections"

# Test 3: Same repo path should produce same collection
same_collection = get_collection_name(current_repo)
print(f"\n[Test 3] Same repo again: {current_repo}")
print(f"         Collection: {same_collection}")
assert same_collection == collection_name, "Same repo should produce same collection name"

print("\n✓ All collection naming tests passed!")
