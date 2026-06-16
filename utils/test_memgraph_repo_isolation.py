#!/usr/bin/env python3
"""Test that Memgraph nodes are tagged with repo_path and queries filter by repo."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from codebase_rag.services.graph_service import MemgraphIngestor

print("=== MEMGRAPH REPO ISOLATION TEST ===\n")

# Test with two different repos
repo_path_1 = "/home/test/repo-a"
repo_path_2 = "/home/test/repo-b"

try:
    # Create ingestor for repo 1
    print(f"[1] Creating ingestor for repo: {repo_path_1}")
    ingestor1 = MemgraphIngestor(
        host="localhost",
        port=7687,
        batch_size=100,
        repo_path=repo_path_1,
    )
    print(f"    Stored repo_path: {ingestor1.repo_path}")
    assert ingestor1.repo_path == str(Path(repo_path_1).resolve()), "Repo path not stored correctly"
    print("[1] ✓ Ingestor 1 created with repo_path")

    # Create ingestor for repo 2
    print(f"\n[2] Creating ingestor for repo: {repo_path_2}")
    ingestor2 = MemgraphIngestor(
        host="localhost",
        port=7687,
        batch_size=100,
        repo_path=repo_path_2,
    )
    print(f"    Stored repo_path: {ingestor2.repo_path}")
    assert ingestor2.repo_path == str(Path(repo_path_2).resolve()), "Repo path not stored correctly"
    print("[2] ✓ Ingestor 2 created with repo_path")

    # Test _get_repo_filter
    print("\n[3] Testing repo filter generation:")
    filter1 = ingestor1._get_repo_filter("n")
    filter2 = ingestor2._get_repo_filter("n")
    print(f"    Filter 1: {filter1}")
    print(f"    Filter 2: {filter2}")
    assert filter1 != filter2, "Different repos should have different filters"
    print("[3] ✓ Repo filters are distinct")

    # Test default repo path (no param)
    print("\n[4] Testing default repo_path:")
    ingestor_default = MemgraphIngestor(
        host="localhost",
        port=7687,
        batch_size=100,
    )
    print(f"    Default repo_path: {ingestor_default.repo_path}")
    expected_default = str(Path(".").expanduser().resolve())
    assert ingestor_default.repo_path == expected_default, f"Default repo_path should be resolved CWD, got: {ingestor_default.repo_path}"
    filter_default = ingestor_default._get_repo_filter("n")
    print(f"    Default filter: '{filter_default}' (should be empty)")
    assert filter_default == "", "Default repo_path should return empty filter"
    print("[4] ✓ Default repo_path behavior correct")

    print("\n✓ MEMGRAPH REPO ISOLATION TEST PASSED")

except Exception as e:
    print(f"\n✗ TEST FAILED: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
