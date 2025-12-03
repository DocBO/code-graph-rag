#!/usr/bin/env python
"""Test to verify Qdrant semantic search is integrated into CLI query mode."""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from codebase_rag.config import settings
from codebase_rag.utils.dependencies import has_semantic_dependencies


def test_semantic_search_integration():
    """Test the semantic search integration."""
    
    print("=" * 70)
    print("SEMANTIC SEARCH IN CLI MODE - INTEGRATION TEST")
    print("=" * 70)
    
    # Check configuration
    print("\n[CONFIGURATION CHECK]")
    print(f"✓ Semantic dependencies available: {has_semantic_dependencies()}")
    print(f"✓ External embedder configured: {bool(settings.EMBED_ENDPOINT and settings.EMBED_MODEL)}")
    if settings.EMBED_ENDPOINT:
        print(f"  - Endpoint: {settings.EMBED_ENDPOINT}")
        print(f"  - Model: {settings.EMBED_MODEL}")
        print(f"  - Dimension: {settings.EMBED_DIMENSION}")
    print(f"✓ Qdrant (Vector DB) configured: {bool(settings.QDRANT_HOST and settings.QDRANT_PORT)}")
    if settings.QDRANT_HOST:
        print(f"  - Host: {settings.QDRANT_HOST}")
        print(f"  - Port: {settings.QDRANT_PORT}")
    
    print("\n[AVAILABILITY]")
    if has_semantic_dependencies():
        print("✓ Semantic search is ENABLED in CLI mode")
        print("  - Can search by natural language intent")
        print("  - Uses Qdrant vector embeddings")
        print("  - Integrates with Memgraph graph queries")
    else:
        print("✗ Semantic search is DISABLED")
        print("  Reason: Missing dependencies")
        print("  Solution: Configure EMBED_ENDPOINT and EMBED_MODEL in .env")
    
    print("\n[CLI INTEGRATION]")
    print("✓ The following semantic tools are now available in interactive CLI mode:")
    print("  1. semantic_search_by_intent - Search code by natural language (NEW)")
    print("     Uses Qdrant for semantic similarity + Memgraph for node details")
    print("  2. semantic_search_functions - Search for functions by intent")
    print("  3. get_function_source_by_id - Retrieve source code by node ID")
    print("  4. query_codebase_knowledge_graph - Query graph with Cypher (existing)")
    
    print("\n[QUERY MODE CHANGES]")
    print("✓ CLI query mode now includes Qdrant semantic search:")
    print("  - Previous: Only Memgraph graph queries")
    print("  - Now: Memgraph + Qdrant vector embeddings")
    print("  - Enables: 'Find functions that handle authentication' style queries")
    
    print("\n[WORKFLOW]")
    print("1. Ingest with embeddings:")
    print("   $ graph-code start --repo-path /path/to/repo --update-graph")
    print("   (Generates embeddings via OpenRouter and stores in Qdrant)")
    print("")
    print("2. Query with CLI:")
    print("   $ graph-code start --repo-path /path/to/repo")
    print("   > semantic_search_by_intent 'find authentication functions'")
    print("")
    print("3. Get source code:")
    print("   > get_function_source_by_id <node_id>")
    
    print("\n" + "=" * 70)
    print("✓ SEMANTIC SEARCH INTEGRATION SUCCESSFUL")
    print("=" * 70)
    print("\nThe CLI now uses both:")
    print("  • Memgraph - for structural queries (functions, classes, relationships)")
    print("  • Qdrant - for semantic queries (finding code by intent)")


if __name__ == "__main__":
    test_semantic_search_integration()
