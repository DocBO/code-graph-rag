#!/usr/bin/env python3
import httpx
import sys
from pathlib import Path

# Add parent directory to path to import settings if needed, 
# but for a standalone utility we can just read from environment or vars
host = "localhost"
port = 6333

def delete_all_code_embeddings():
    base_url = f"http://{host}:{port}"
    
    try:
        # Get all collections
        response = httpx.get(f"{base_url}/collections")
        response.raise_for_status()
        collections = response.json().get("result", {}).get("collections", [])
        
        target_collections = [c["name"] for c in collections if c["name"].startswith("code_embeddings_")]
        
        if not target_collections:
            print("No collections starting with 'code_embeddings_' found.")
            return

        print(f"Found {len(target_collections)} collections to delete:")
        for name in target_collections:
            print(f"  - {name}")
            
        confirm = input("\nAre you sure you want to delete ALL these collections? (y/N): ")
        if confirm.lower() != 'y':
            print("Aborted.")
            return

        for name in target_collections:
            print(f"Deleting {name}...", end=" ", flush=True)
            del_resp = httpx.delete(f"{base_url}/collections/{name}")
            if del_resp.status_code == 200:
                print("OK")
            else:
                print(f"FAILED ({del_resp.status_code})")
                
        print("\nCleanup complete.")

    except httpx.ConnectError:
        print(f"Error: Could not connect to Qdrant at {base_url}. Is it running?")
        sys.exit(1)
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        sys.exit(1)

if __name__ == "__main__":
    delete_all_code_embeddings()
