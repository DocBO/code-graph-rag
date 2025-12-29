"""Vector store access (local or remote Qdrant)."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import httpx
from loguru import logger

from .config import settings
from .utils.dependencies import has_qdrant_client


class VectorStoreError(Exception):
    pass


def _use_remote_qdrant() -> bool:
    return bool(settings.QDRANT_HOST and settings.QDRANT_PORT)


def get_collection_name(repo_path: str | Path | None = None) -> str:
    """Generate a repository-specific collection name.
    
    Uses the repo path to create a unique collection name so multiple
    repositories can have their own vector collections in the same Qdrant instance.
    """
    if repo_path is None:
        repo_path = settings.TARGET_REPO_PATH or "."
    
    repo_path = str(Path(repo_path).expanduser().resolve())
    # Create a hash of the repo path to keep collection names reasonable length
    path_hash = hashlib.md5(repo_path.encode()).hexdigest()[:8]
    return f"code_embeddings_{path_hash}"


def get_stable_point_id(qualified_name: str) -> int:
    """Generate a stable point ID from qualified name only.
    
    This ensures that the same function always gets the same Qdrant point ID,
    regardless of its location in the file (line numbers). This way:
    - When a function moves to a different location, its vector gets updated (upsert)
    - When a function is renamed, it gets a new ID (new vector)
    - Memgraph and Qdrant stay synchronized on identity
    
    Args:
        qualified_name: The qualified name (e.g., "module.ClassName.method_name")
        
    Returns:
        Integer ID suitable for Qdrant point IDs
    """
    # Use MD5 hash of qualified_name, convert to 31-bit integer to avoid overflow
    hash_hex = hashlib.md5(qualified_name.encode()).hexdigest()
    return int(hash_hex, 16) % (2**31 - 1)


if has_qdrant_client():
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, PointStruct, VectorParams

    _CLIENT = None
    _COLLECTION_NAME = None
    _REPO_PATH = None

    def _get_collection_name() -> str:
        """Get the current collection name."""
        global _COLLECTION_NAME, _REPO_PATH
        if _COLLECTION_NAME is None or _REPO_PATH != (settings.TARGET_REPO_PATH or "."):
            _REPO_PATH = settings.TARGET_REPO_PATH or "."
            _COLLECTION_NAME = get_collection_name(_REPO_PATH)
        return _COLLECTION_NAME

    def get_qdrant_client() -> QdrantClient:
        """Get or create Qdrant client instance (remote if configured, else local disk)."""
        global _CLIENT
        if _CLIENT is not None:
            return _CLIENT

        if _use_remote_qdrant():
            _CLIENT = QdrantClient(
                host=settings.QDRANT_HOST,
                port=settings.QDRANT_PORT,
                api_key=settings.QDRANT_API_KEY,
                https=settings.QDRANT_PORT == 443,
            )
        else:
            _CLIENT = QdrantClient(path="./.qdrant_code_embeddings")

        return _CLIENT

    def _ensure_collection_exists(client: QdrantClient, collection_name: str) -> None:
        """Ensure the collection exists in Qdrant."""
        if not client.collection_exists(collection_name):
            vector_size = settings.EMBED_DIMENSION or 768
            client.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
            )

    def store_embedding(
        node_id: int, embedding: list[float], qualified_name: str, repo_path: str | Path | None = None
    ) -> None:
        """Store code embedding in Qdrant vector database.
        
        Uses qualified_name as stable point ID so that:
        - Function moves update the vector (same ID)
        - Function renames create new vector (different ID)
        - Qdrant stays synchronized with Memgraph's qualified_name identity
        """
        try:
            client = get_qdrant_client()
            collection_name = get_collection_name(repo_path)
            _ensure_collection_exists(client, collection_name)
            
            stable_point_id = get_stable_point_id(qualified_name)
            client.upsert(
                collection_name=collection_name,
                points=[
                    PointStruct(
                        id=stable_point_id,
                        vector=embedding,
                        payload={"node_id": node_id, "qualified_name": qualified_name},
                    )
                ],
            )
        except Exception as e:
            logger.warning(f"Failed to store embedding for {qualified_name}: {e}")
            raise

    def search_embeddings(
        query_embedding: list[float], top_k: int = 5, repo_path: str | Path | None = None
    ) -> list[tuple[int, float]]:
        """Search for similar code embeddings."""
        try:
            client = get_qdrant_client()
            collection_name = get_collection_name(repo_path)
            _ensure_collection_exists(client, collection_name)
            
            hits = client.search(
                collection_name=collection_name,
                query_vector=query_embedding,
                limit=top_k,
            )
            return [(hit.payload["node_id"], hit.score) for hit in hits]
        except Exception as e:
            logger.warning(f"Failed to search embeddings: {e}")
            return []

    def clean_collection(repo_path: str | Path | None = None) -> None:
        """Delete all vectors from a Qdrant collection.
        
        Args:
            repo_path: Repository path to identify collection. Uses TARGET_REPO_PATH if None.
        """
        try:
            client = get_qdrant_client()
            collection_name = get_collection_name(repo_path)
            logger.info(f"Cleaning Qdrant collection: {collection_name}")
            client.delete(
                collection_name=collection_name,
                points_selector=None,  # Delete all points
            )
            logger.info(f"Qdrant collection cleaned: {collection_name}")
        except Exception as e:
            logger.warning(f"Failed to clean Qdrant collection: {e}")
            raise

elif _use_remote_qdrant():
    """Fall back to HTTP-based Qdrant access if remote Qdrant is configured."""
    _COLLECTION_NAME = None
    _REPO_PATH = None

    def _get_collection_name(repo_path: str | Path | None = None) -> str:
        """Get the current collection name, caching when possible."""
        return get_collection_name(repo_path)

    def _build_qdrant_url(path: str) -> str:
        """Build Qdrant HTTP URL."""
        scheme = "https" if settings.QDRANT_PORT == 443 else "http"
        return f"{scheme}://{settings.QDRANT_HOST}:{settings.QDRANT_PORT}{path}"

    def get_qdrant_client() -> Any:
        raise VectorStoreError("Qdrant client not available. Using HTTP API instead.")

    def _ensure_collection_exists(collection_name: str) -> None:
        """Ensure the collection exists in remote Qdrant."""
        try:
            vector_size = settings.EMBED_DIMENSION or 768
            headers = {"Content-Type": "application/json"}
            if settings.QDRANT_API_KEY:
                headers["api-key"] = settings.QDRANT_API_KEY

            # Check if collection exists
            check_url = _build_qdrant_url(f"/collections/{collection_name}")
            resp = httpx.get(check_url, headers=headers, timeout=10.0)

            if resp.status_code == 404:
                # Create collection via PUT to /collections/{name}
                create_url = _build_qdrant_url(f"/collections/{collection_name}")
                payload = {
                    "vectors": {"size": vector_size, "distance": "Cosine"},
                }
                create_resp = httpx.put(
                    create_url, json=payload, headers=headers, timeout=10.0
                )
                if create_resp.status_code >= 400:
                    logger.warning(
                        f"Failed to create Qdrant collection {collection_name}: {create_resp.text}"
                    )
                else:
                    logger.info(f"Created Qdrant collection: {collection_name}")
        except Exception as e:
            logger.warning(f"Failed to ensure Qdrant collection exists: {e}")

    def store_embedding(
        node_id: int, embedding: list[float], qualified_name: str, repo_path: str | Path | None = None
    ) -> None:
        """Store code embedding in remote Qdrant via HTTP.
        
        Uses qualified_name as stable point ID so that:
        - Function moves update the vector (same ID)
        - Function renames create new vector (different ID)
        - Qdrant stays synchronized with Memgraph's qualified_name identity
        """
        try:
            collection_name = _get_collection_name(repo_path)
            _ensure_collection_exists(collection_name)

            headers = {"Content-Type": "application/json"}
            if settings.QDRANT_API_KEY:
                headers["api-key"] = settings.QDRANT_API_KEY

            stable_point_id = get_stable_point_id(qualified_name)
            url = _build_qdrant_url(f"/collections/{collection_name}/points")
            payload = {
                "points": [
                    {
                        "id": stable_point_id,
                        "vector": embedding,
                        "payload": {
                            "node_id": node_id,
                            "qualified_name": qualified_name,
                        },
                    }
                ]
            }

            resp = httpx.put(url, json=payload, headers=headers, timeout=10.0)
            if resp.status_code >= 400:
                logger.warning(f"Failed to store embedding via HTTP: {resp.text}")
        except Exception as e:
            logger.warning(f"Failed to store embedding for {qualified_name}: {e}")
            raise

    def search_embeddings(
        query_embedding: list[float], top_k: int = 5, repo_path: str | Path | None = None
    ) -> list[tuple[int, float]]:
        """Search for similar code embeddings via HTTP."""
        try:
            collection_name = _get_collection_name(repo_path)
            headers = {"Content-Type": "application/json"}
            if settings.QDRANT_API_KEY:
                headers["api-key"] = settings.QDRANT_API_KEY

            url = _build_qdrant_url(f"/collections/{collection_name}/points/search")
            payload = {"vector": query_embedding, "limit": top_k, "with_payload": True}

            resp = httpx.post(url, json=payload, headers=headers, timeout=10.0)
            if resp.status_code >= 400:
                logger.warning(f"Failed to search embeddings: {resp.text}")
                return []

            data = resp.json()
            return [
                (hit["payload"]["node_id"], hit["score"])
                for hit in data.get("result", [])
            ]
        except Exception as e:
            logger.warning(f"Failed to search embeddings: {e}")
            return []

    def clean_collection(repo_path: str | Path | None = None) -> None:
        """Delete all vectors from a Qdrant collection via HTTP.
        
        Args:
            repo_path: Repository path to identify collection. Uses TARGET_REPO_PATH if None.
        """
        try:
            collection_name = _get_collection_name(repo_path)
            logger.info(f"Cleaning Qdrant collection via HTTP: {collection_name}")
            
            headers = {"Content-Type": "application/json"}
            if settings.QDRANT_API_KEY:
                headers["api-key"] = settings.QDRANT_API_KEY
            
            # Delete all points using points selector with empty list
            url = _build_qdrant_url(f"/collections/{collection_name}/points/delete")
            payload = {"points": []}  # Empty list means match all/truncate
            
            resp = httpx.post(url, json=payload, headers=headers, timeout=10.0)
            if resp.status_code >= 400:
                logger.warning(f"Failed to clean Qdrant collection: {resp.text}")
                raise VectorStoreError(f"Failed to clean collection: {resp.text}")
            
            logger.info(f"Qdrant collection cleaned via HTTP: {collection_name}")
        except Exception as e:
            logger.warning(f"Failed to clean Qdrant collection: {e}")
            raise

else:

    def get_qdrant_client() -> Any:
        raise VectorStoreError(
            "Qdrant client not available. Install qdrant-client or use --extra semantic."
        )

    def store_embedding(
        node_id: int, embedding: list[float], qualified_name: str
    ) -> None:
        raise VectorStoreError("Qdrant client not available. Cannot store embeddings.")

    def search_embeddings(
        query_embedding: list[float], top_k: int = 5
    ) -> list[tuple[int, float]]:
        return []

    def clean_collection(repo_path: str | Path | None = None) -> None:
        raise VectorStoreError("Qdrant client not available. Cannot clean collections.")

