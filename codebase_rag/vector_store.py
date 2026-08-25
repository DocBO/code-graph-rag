"""Vector store access (local or remote Qdrant)."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
from loguru import logger

from .config import settings
from .utils.dependencies import has_qdrant_client


class VectorStoreError(Exception):
    pass


def _is_transient_error(exc: BaseException) -> bool:
    """Return True for timeouts, connection failures, and server-side errors."""
    if isinstance(exc, TimeoutError | ConnectionError):
        return True
    if isinstance(exc, httpx.TransportError):
        return True
    status = getattr(exc, "status_code", None)
    return isinstance(status, int) and (status == 429 or status >= 500)


def _retry_qdrant_write(
    attempt_fn: Callable[[], None],
    description: str,
) -> None:
    """Run a Qdrant write with retries and exponential backoff on transient failures."""
    max_retries = max(settings.QDRANT_MAX_RETRIES, 0)
    for attempt in range(max_retries + 1):
        try:
            attempt_fn()
            return
        except Exception as e:
            if attempt >= max_retries or not _is_transient_error(e):
                raise
            delay = settings.QDRANT_RETRY_BACKOFF * (2**attempt)
            logger.warning(
                f"{description} failed (attempt {attempt + 1}/{max_retries + 1}): {e}; "
                f"retrying in {delay:.1f}s"
            )
            time.sleep(delay)


def _resolve_upsert_batch_size(total_points: int) -> int:
    """Return a safe upsert batch size for current settings and payload size."""
    configured = settings.QDRANT_UPSERT_BATCH_SIZE
    if configured < 1:
        return max(total_points, 1)
    return configured


def _unpack_embedding_row(
    row: tuple[int, list[float], str]
    | tuple[int, list[float], str, str]
    | tuple[int, list[float], str, str, str],
) -> tuple[int, list[float], str, str | None, str | None]:
    """Normalize embedding rows to (node_id, embedding, qualified_name, chunk_text, file_path)."""
    if len(row) == 3:
        node_id, embedding, qualified_name = row
        return node_id, embedding, qualified_name, None, None
    if len(row) == 4:
        node_id, embedding, qualified_name, chunk_text = row
        return node_id, embedding, qualified_name, chunk_text, None
    node_id, embedding, qualified_name, chunk_text, file_path = row
    return node_id, embedding, qualified_name, chunk_text, file_path


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
    from qdrant_client.models import (
        Distance,
        FieldCondition,
        Filter,
        MatchAny,
        PointStruct,
        VectorParams,
    )

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
                timeout=settings.QDRANT_TIMEOUT,
            )
        else:
            _CLIENT = QdrantClient(
                path="./.qdrant_code_embeddings", timeout=settings.QDRANT_TIMEOUT
            )

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
        node_id: int,
        embedding: list[float],
        qualified_name: str,
        repo_path: str | Path | None = None,
    ) -> None:
        """Store code embedding in Qdrant vector database.

        Uses qualified_name as stable point ID so that:
        - Function moves update the vector (same ID)
        - Function renames create new vector (different ID)
        - Qdrant stays synchronized with Memgraph's qualified_name identity
        """
        batch_store_embeddings([(node_id, embedding, qualified_name)], repo_path)

    def batch_store_embeddings(
        embeddings_data: list[
            tuple[int, list[float], str]
            | tuple[int, list[float], str, str]
            | tuple[int, list[float], str, str, str]
        ],
        repo_path: str | Path | None = None,
    ) -> None:
        """Store multiple code embeddings in Qdrant in a single batch."""
        if not embeddings_data:
            return

        try:
            client = get_qdrant_client()
            collection_name = get_collection_name(repo_path)
            _ensure_collection_exists(client, collection_name)

            points = []
            for row in embeddings_data:
                node_id, embedding, qualified_name, chunk_text, file_path = (
                    _unpack_embedding_row(row)
                )
                stable_point_id = get_stable_point_id(qualified_name)
                payload = {"node_id": node_id, "qualified_name": qualified_name}
                if chunk_text is not None:
                    payload["chunk_text"] = chunk_text
                if file_path is not None:
                    payload["file_path"] = file_path
                points.append(
                    PointStruct(
                        id=stable_point_id,
                        vector=embedding,
                        payload=payload,
                    )
                )

            upsert_batch_size = _resolve_upsert_batch_size(len(points))
            for start in range(0, len(points), upsert_batch_size):
                point_batch = points[start : start + upsert_batch_size]
                batch_num = (start // upsert_batch_size) + 1
                total_batches = (len(points) + upsert_batch_size - 1) // upsert_batch_size
                _retry_qdrant_write(
                    lambda batch=point_batch: client.upsert(
                        collection_name=collection_name,
                        points=batch,
                    ),
                    (
                        f"Qdrant upsert batch {batch_num}/{total_batches} "
                        f"({len(point_batch)} points) into {collection_name}"
                    ),
                )
        except Exception as e:
            logger.warning(
                f"Failed to store batch of {len(embeddings_data)} embeddings: {e}"
            )
            raise

    def delete_embeddings_for_files(
        file_paths: list[str],
        repo_path: str | Path | None = None,
    ) -> None:
        """Delete embeddings whose payload file_path matches any provided path."""
        normalized_paths = sorted({str(Path(p)) for p in file_paths if p})
        if not normalized_paths:
            return

        try:
            client = get_qdrant_client()
            collection_name = get_collection_name(repo_path)
            _ensure_collection_exists(client, collection_name)
            selector = Filter(
                must=[
                    FieldCondition(
                        key="file_path",
                        match=MatchAny(any=normalized_paths),
                    )
                ]
            )
            client.delete(collection_name=collection_name, points_selector=selector)
            logger.info(
                "Deleted embeddings for {} changed file(s) in {}",
                len(normalized_paths),
                collection_name,
            )
        except Exception as e:
            logger.warning(f"Failed to delete embeddings for changed files: {e}")
            raise

    def search_embedding_matches(
        query_embedding: list[float],
        top_k: int = 5,
        repo_path: str | Path | None = None,
    ) -> list[dict[str, Any]]:
        """Search similar code embeddings and retain matched chunk payload metadata."""
        try:
            client = get_qdrant_client()
            collection_name = get_collection_name(repo_path)
            _ensure_collection_exists(client, collection_name)

            hits = client.search(
                collection_name=collection_name,
                query_vector=query_embedding,
                limit=top_k,
            )
            matches: list[dict[str, Any]] = []
            for hit in hits:
                payload = hit.payload or {}
                node_id = payload.get("node_id")
                if node_id is None:
                    continue
                matches.append(
                    {
                        "node_id": node_id,
                        "score": hit.score,
                        "matched_qualified_name": payload.get("qualified_name"),
                        "chunk_text": payload.get("chunk_text"),
                    }
                )
            return matches
        except Exception as e:
            logger.warning(f"Failed to search embedding matches: {e}")
            return []

    def search_embeddings(
        query_embedding: list[float],
        top_k: int = 5,
        repo_path: str | Path | None = None,
    ) -> list[tuple[int, float]]:
        """Search for similar code embeddings."""
        matches = search_embedding_matches(query_embedding, top_k, repo_path)
        return [(int(match["node_id"]), float(match["score"])) for match in matches]

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
                points_selector=Filter(),
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
        node_id: int,
        embedding: list[float],
        qualified_name: str,
        repo_path: str | Path | None = None,
    ) -> None:
        """Store code embedding in remote Qdrant via HTTP.

        Uses qualified_name as stable point ID so that:
        - Function moves update the vector (same ID)
        - Function renames create new vector (different ID)
        - Qdrant stays synchronized with Memgraph's qualified_name identity
        """
        batch_store_embeddings([(node_id, embedding, qualified_name)], repo_path)

    def batch_store_embeddings(
        embeddings_data: list[
            tuple[int, list[float], str]
            | tuple[int, list[float], str, str]
            | tuple[int, list[float], str, str, str]
        ],
        repo_path: str | Path | None = None,
    ) -> None:
        """Store multiple code embeddings in remote Qdrant via HTTP in a single batch."""
        if not embeddings_data:
            return

        try:
            collection_name = _get_collection_name(repo_path)
            _ensure_collection_exists(collection_name)

            headers = {"Content-Type": "application/json"}
            if settings.QDRANT_API_KEY:
                headers["api-key"] = settings.QDRANT_API_KEY

            points = []
            for row in embeddings_data:
                node_id, embedding, qualified_name, chunk_text, file_path = (
                    _unpack_embedding_row(row)
                )
                stable_point_id = get_stable_point_id(qualified_name)
                payload = {
                    "node_id": node_id,
                    "qualified_name": qualified_name,
                }
                if chunk_text is not None:
                    payload["chunk_text"] = chunk_text
                if file_path is not None:
                    payload["file_path"] = file_path
                points.append(
                    {
                        "id": stable_point_id,
                        "vector": embedding,
                        "payload": payload,
                    }
                )

            url = _build_qdrant_url(f"/collections/{collection_name}/points")
            payload = {"points": points}

            upsert_batch_size = _resolve_upsert_batch_size(len(points))
            for start in range(0, len(points), upsert_batch_size):
                point_batch = points[start : start + upsert_batch_size]
                batch_num = (start // upsert_batch_size) + 1
                total_batches = (len(points) + upsert_batch_size - 1) // upsert_batch_size

                def _put_points(batch_points: list[dict[str, Any]] = point_batch) -> None:
                    resp = httpx.put(
                        url,
                        json={"points": batch_points},
                        headers=headers,
                        timeout=settings.QDRANT_TIMEOUT,
                    )
                    if resp.status_code >= 400:
                        raise VectorStoreError(
                            f"Qdrant HTTP upsert failed: {resp.status_code} {resp.text}"
                        )

                _retry_qdrant_write(
                    _put_points,
                    (
                        f"Qdrant HTTP upsert batch {batch_num}/{total_batches} "
                        f"({len(point_batch)} points) into {collection_name}"
                    ),
                )
        except Exception as e:
            logger.warning(
                f"Failed to store batch of {len(embeddings_data)} embeddings: {e}"
            )
            raise

    def delete_embeddings_for_files(
        file_paths: list[str],
        repo_path: str | Path | None = None,
    ) -> None:
        """Delete embeddings whose payload file_path matches any provided path."""
        normalized_paths = sorted({str(Path(p)) for p in file_paths if p})
        if not normalized_paths:
            return

        try:
            collection_name = _get_collection_name(repo_path)
            headers = {"Content-Type": "application/json"}
            if settings.QDRANT_API_KEY:
                headers["api-key"] = settings.QDRANT_API_KEY

            url = _build_qdrant_url(f"/collections/{collection_name}/points/delete")
            payload = {
                "filter": {
                    "must": [
                        {
                            "key": "file_path",
                            "match": {"any": normalized_paths},
                        }
                    ]
                }
            }
            resp = httpx.post(url, json=payload, headers=headers, timeout=10.0)
            if resp.status_code >= 400:
                logger.warning(
                    f"Failed to delete embeddings for changed files: {resp.text}"
                )
                raise VectorStoreError(resp.text)
            logger.info(
                "Deleted embeddings for {} changed file(s) in {}",
                len(normalized_paths),
                collection_name,
            )
        except Exception as e:
            logger.warning(f"Failed to delete embeddings for changed files: {e}")
            raise

    def search_embedding_matches(
        query_embedding: list[float],
        top_k: int = 5,
        repo_path: str | Path | None = None,
    ) -> list[dict[str, Any]]:
        """Search similar code embeddings and retain matched chunk payload metadata."""
        try:
            collection_name = _get_collection_name(repo_path)
            headers = {"Content-Type": "application/json"}
            if settings.QDRANT_API_KEY:
                headers["api-key"] = settings.QDRANT_API_KEY

            url = _build_qdrant_url(f"/collections/{collection_name}/points/search")
            payload = {"vector": query_embedding, "limit": top_k, "with_payload": True}

            resp = httpx.post(url, json=payload, headers=headers, timeout=10.0)
            if resp.status_code >= 400:
                logger.warning(f"Failed to search embedding matches: {resp.text}")
                return []

            data = resp.json()
            matches: list[dict[str, Any]] = []
            for hit in data.get("result", []):
                payload_data = hit.get("payload", {})
                node_id = payload_data.get("node_id")
                if node_id is None:
                    continue
                matches.append(
                    {
                        "node_id": node_id,
                        "score": hit.get("score"),
                        "matched_qualified_name": payload_data.get("qualified_name"),
                        "chunk_text": payload_data.get("chunk_text"),
                    }
                )
            return matches
        except Exception as e:
            logger.warning(f"Failed to search embedding matches: {e}")
            return []

    def search_embeddings(
        query_embedding: list[float],
        top_k: int = 5,
        repo_path: str | Path | None = None,
    ) -> list[tuple[int, float]]:
        """Search for similar code embeddings via HTTP."""
        matches = search_embedding_matches(query_embedding, top_k, repo_path)
        return [(int(match["node_id"]), float(match["score"])) for match in matches]

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

            delete_url = _build_qdrant_url(f"/collections/{collection_name}")
            resp = httpx.delete(delete_url, headers=headers, timeout=10.0)
            if resp.status_code >= 400 and resp.status_code != 404:
                logger.warning(f"Failed to delete Qdrant collection: {resp.text}")
                raise VectorStoreError(f"Failed to delete collection: {resp.text}")

            logger.info(f"Qdrant collection deleted: {collection_name}")
            _ensure_collection_exists(collection_name)
        except Exception as e:
            logger.warning(f"Failed to clean Qdrant collection: {e}")
            raise

else:

    def get_qdrant_client() -> Any:
        raise VectorStoreError(
            "Qdrant client not available. Install qdrant-client or use --extra semantic."
        )

    def store_embedding(
        node_id: int,
        embedding: list[float],
        qualified_name: str,
        repo_path: str | Path | None = None,
    ) -> None:
        raise VectorStoreError("Qdrant client not available. Cannot store embeddings.")

    def batch_store_embeddings(
        embeddings_data: list[
            tuple[int, list[float], str]
            | tuple[int, list[float], str, str]
            | tuple[int, list[float], str, str, str]
        ],
        repo_path: str | Path | None = None,
    ) -> None:
        raise VectorStoreError(
            "Qdrant client not available. Cannot store batch embeddings."
        )

    def delete_embeddings_for_files(
        file_paths: list[str],
        repo_path: str | Path | None = None,
    ) -> None:
        raise VectorStoreError(
            "Qdrant client not available. Cannot delete file-scoped embeddings."
        )

    def search_embeddings(
        query_embedding: list[float],
        top_k: int = 5,
        repo_path: str | Path | None = None,
    ) -> list[tuple[int, float]]:
        return []

    def search_embedding_matches(
        query_embedding: list[float],
        top_k: int = 5,
        repo_path: str | Path | None = None,
    ) -> list[dict[str, Any]]:
        return []

    def clean_collection(repo_path: str | Path | None = None) -> None:
        raise VectorStoreError("Qdrant client not available. Cannot clean collections.")
