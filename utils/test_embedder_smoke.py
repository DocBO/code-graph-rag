#!/usr/bin/env python
"""Smoke test to verify embedder works and check embedding dimensions."""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from codebase_rag.config import settings
from codebase_rag.embedder import embed_code


def test_embedder():
    """Test the embedder with sample code and verify dimensions."""

    print("=" * 60)
    print("EMBEDDER SMOKE TEST")
    print("=" * 60)

    # Print configuration
    print("\n[CONFIG]")
    print(
        f"Using external embedder: {bool(settings.EMBED_ENDPOINT and settings.EMBED_MODEL)}"
    )
    if settings.EMBED_ENDPOINT:
        print(f"  Endpoint: {settings.EMBED_ENDPOINT}")
        print(f"  Model: {settings.EMBED_MODEL}")
        if settings.EMBED_DIMENSION:
            print(f"  Expected dimension: {settings.EMBED_DIMENSION}")
    else:
        print("  Using local UniXcoder embedder (microsoft/unixcoder-base)")

    # Sample code to embed
    sample_code = """
def hello_world():
    print("Hello, World!")
    return 42
"""

    print("\n[INPUT CODE]")
    print(sample_code)

    try:
        print("\n[EMBEDDING GENERATION]")
        print("Generating embedding...")
        embedding = embed_code(sample_code)

        print("✓ Success!")
        print(f"  Embedding dimension: {len(embedding)}")
        print(f"  First 5 values: {embedding[:5]}")
        print(f"  Last 5 values: {embedding[-5:]}")
        print(f"  Min value: {min(embedding):.6f}")
        print(f"  Max value: {max(embedding):.6f}")
        print(f"  Mean value: {sum(embedding) / len(embedding):.6f}")

        # Verify dimension if configured
        if settings.EMBED_DIMENSION:
            if len(embedding) == settings.EMBED_DIMENSION:
                print(
                    f"\n✓ Dimension is correct: {len(embedding)} == {settings.EMBED_DIMENSION}"
                )
            else:
                print(
                    f"\n⚠ Dimension mismatch: {len(embedding)} != {settings.EMBED_DIMENSION}"
                )
        else:
            print(
                f"\n✓ Embedding dimension: {len(embedding)} (no expected dimension configured)"
            )

        print("\n" + "=" * 60)
        print("✓ EMBEDDER SMOKE TEST PASSED")
        print("=" * 60)
        return True

    except Exception as e:
        print("\n✗ EMBEDDER SMOKE TEST FAILED")
        print(f"Error: {type(e).__name__}: {e}")
        print("=" * 60)
        return False


if __name__ == "__main__":
    success = test_embedder()
    sys.exit(0 if success else 1)
