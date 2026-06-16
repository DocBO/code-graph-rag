import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx
from codebase_rag.config import settings

async def test_dim():
    headers = {"Content-Type": "application/json"}
    if settings.EMBED_API_KEY:
        headers["Authorization"] = f"Bearer {settings.EMBED_API_KEY}"

    payload = {
        "model": settings.EMBED_MODEL,
        "input": ["test"],
    }

    endpoint = settings.EMBED_ENDPOINT
    if endpoint and not endpoint.endswith("/embeddings"):
        endpoint = endpoint.rstrip("/") + "/embeddings"

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(endpoint, json=payload, headers=headers)
        data = resp.json()
        
        embedding = None
        if "data" in data and len(data["data"]) > 0:
            embedding = data["data"][0]["embedding"]
        elif "embedding" in data:
            embedding = data["embedding"]
            
        if embedding:
            print(f"Model: {settings.EMBED_MODEL}")
            print(f"Dimension: {len(embedding)}")
        else:
            print(f"Failed to get embedding: {data}")

if __name__ == "__main__":
    asyncio.run(test_dim())
