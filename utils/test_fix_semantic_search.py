
import sys
from pathlib import Path
import os

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from codebase_rag.config import settings
from codebase_rag.vector_store import search_embeddings, store_embedding, get_collection_name

def test_auto_collection_creation():
    print("=== Testing Auto Collection Creation ===")
    
    # Use a fake repo path that definitely doesn't exist in Qdrant yet
    fake_repo = "/tmp/fake_repo_test_auto_creation"
    collection_name = get_collection_name(fake_repo)
    print(f"Target collection: {collection_name}")
    
    # Create a dummy embedding
    dummy_embedding = [0.1] * (settings.EMBED_DIMENSION or 768)
    
    print("\n1. Attempting to search in non-existent collection...")
    try:
        # This should now succeed (returning empty list) instead of failing or returning empty due to error
        results = search_embeddings(dummy_embedding, top_k=5, repo_path=fake_repo)
        print(f"✓ Search succeeded, found {len(results)} results (expected 0)")
    except Exception as e:
        print(f"✗ Search failed: {e}")
        return False

    print("\n2. Attempting to store in non-existent collection...")
    try:
        store_embedding(node_id=12345, embedding=dummy_embedding, qualified_name="fake.node", repo_path=fake_repo)
        print("✓ Store succeeded")
    except Exception as e:
        print(f"✗ Store failed: {e}")
        return False

    print("\n3. Attempting to search again...")
    try:
        results = search_embeddings(dummy_embedding, top_k=5, repo_path=fake_repo)
        print(f"✓ Search succeeded, found {len(results)} results")
        if len(results) > 0 and results[0][0] == 12345:
            print("✓ Found the stored node!")
        else:
            print(f"✗ Could not find the stored node. Results: {results}")
            return False
    except Exception as e:
        print(f"✗ Search failed: {e}")
        return False

    print("\n=== Test Passed! ===")
    return True

if __name__ == "__main__":
    if test_auto_collection_creation():
        sys.exit(0)
    else:
        sys.exit(1)
