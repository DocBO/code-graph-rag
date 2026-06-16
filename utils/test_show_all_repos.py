#!/usr/bin/env python3
"""Test to show all repositories in Memgraph."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from codebase_rag.services.graph_service import execute_read_query


def test_show_all_repos():
    """Query Memgraph to display all repositories currently in the graph.
    
    This test:
    1. Connects to Memgraph
    2. Queries for all distinct _repo_path values
    3. For each repo, shows:
       - The absolute path
       - Number of nodes in that repo
       - Types of nodes (counts by label)
    """
    
    host = "localhost"
    port = 7687
    
    print("\n" + "="*70)
    print("MEMGRAPH REPOSITORIES OVERVIEW")
    print("="*70)
    
    # Query 1: Get all distinct repository paths
    print("\n[1] Fetching distinct repositories...")
    repos_query = """
    MATCH (n)
    WHERE n._repo_path IS NOT NULL
    RETURN DISTINCT n._repo_path AS repo_path
    ORDER BY n._repo_path
    """
    
    try:
        repos_results = execute_read_query(host, port, repos_query)
    except Exception as e:
        print(f"❌ Error querying Memgraph: {e}")
        print("\nMake sure Memgraph is running:")
        print("  docker-compose up -d")
        return
    
    if not repos_results:
        print("⚠️  No repositories found with _repo_path property")
        print("\nTip: Ingest a repository first with:")
        print("  python -m codebase_rag.main start --repo-path /path/to/repo")
        return
    
    print(f"✓ Found {len(repos_results)} repositories\n")
    
    # Query 2: For each repo, get detailed statistics
    for idx, repo_data in enumerate(repos_results, 1):
        repo_path = repo_data["repo_path"]
        
        print(f"[Repository {idx}] {repo_path}")
        print("-" * 70)
        
        # Get total node count for this repo
        count_query = """
        MATCH (n)
        WHERE n._repo_path = $repo_path
        RETURN COUNT(n) AS total_nodes
        """
        
        count_results = execute_read_query(host, port, count_query, {"repo_path": repo_path})
        total_nodes = count_results[0]["total_nodes"] if count_results else 0
        print(f"  Total nodes: {total_nodes}")
        
        # Get node types distribution
        types_query = """
        MATCH (n)
        WHERE n._repo_path = $repo_path
        RETURN
            labels(n)[0] AS node_type,
            COUNT(n) AS count
        ORDER BY count DESC
        """
        
        try:
            types_results = execute_read_query(host, port, types_query, {"repo_path": repo_path})
            
            if types_results:
                print(f"  Node types:")
                for type_data in types_results:
                    node_type = type_data["node_type"] or "Unknown"
                    count = type_data["count"]
                    print(f"    - {node_type}: {count}")
        except Exception as e:
            print(f"  ⚠️  Could not fetch node types: {e}")
        
        # Get relationship count for this repo
        rel_query = """
        MATCH (n)-[r]->(m)
        WHERE n._repo_path = $repo_path
        RETURN COUNT(r) AS total_relationships
        """
        
        try:
            rel_results = execute_read_query(host, port, rel_query, {"repo_path": repo_path})
            total_rels = rel_results[0]["total_relationships"] if rel_results else 0
            print(f"  Total relationships: {total_rels}")
        except Exception as e:
            print(f"  ⚠️  Could not fetch relationships: {e}")
        
        print()
    
    # Summary statistics
    print("="*70)
    print("SUMMARY")
    print("="*70)
    print(f"Total repositories: {len(repos_results)}")
    
    # Get total graph stats
    total_nodes_query = "MATCH (n) WHERE n._repo_path IS NOT NULL RETURN COUNT(n) AS total"
    total_rels_query = "MATCH (n)-[r]->(m) WHERE n._repo_path IS NOT NULL RETURN COUNT(r) AS total"
    
    try:
        total_nodes = execute_read_query(host, port, total_nodes_query)[0]["total"]
        total_rels = execute_read_query(host, port, total_rels_query)[0]["total"]
        print(f"Total nodes (all repos): {total_nodes}")
        print(f"Total relationships (all repos): {total_rels}")
    except Exception as e:
        print(f"⚠️  Could not fetch global stats: {e}")
    
    print("="*70 + "\n")


if __name__ == "__main__":
    test_show_all_repos()
