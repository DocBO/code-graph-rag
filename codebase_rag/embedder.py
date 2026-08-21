"""Embedding clients (external only)."""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any

import httpx
from loguru import logger

from .config import settings


class EmbeddingError(Exception):
    """Raised when embedding generation fails."""


class EmbedRateLimiter:
    """Thread-safe token-bucket rate limiter shared across sync/async callers.

    A module-level instance is used by every embedder request, so parallel
    ingestion paths (watcher Pass 4, MCP start_updater, CLI --only-embedding)
    all share the same budget and never flood the external endpoint.
    """

    def __init__(self, requests_per_minute: int) -> None:
        self._interval = 60.0 / max(requests_per_minute, 1)
        self._lock = threading.Lock()
        self._last_request = 0.0

    async def wait(self) -> None:
        """Block until the next request is allowed by the rate limit."""
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_request
            if self._last_request == 0.0 or elapsed >= self._interval:
                self._last_request = now
                return
            delay = self._interval - elapsed
            self._last_request = now + delay
        if delay > 0:
            await asyncio.sleep(delay)


_embed_rate_limiter: EmbedRateLimiter | None = None
_rate_limiter_lock = threading.Lock()


def _get_rate_limiter() -> EmbedRateLimiter:
    global _embed_rate_limiter
    if _embed_rate_limiter is None:
        with _rate_limiter_lock:
            if _embed_rate_limiter is None:
                _embed_rate_limiter = EmbedRateLimiter(settings.EMBED_RATE_LIMIT_RPM)
    return _embed_rate_limiter


def _parse_retry_after(headers: httpx.Headers) -> float | None:
    """Return seconds to wait from a Retry-After header, if present."""
    value = headers.get("Retry-After")
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        # HTTP-date format (RFC 7231): e.g. "Wed, 21 Oct 2015 07:28:00 GMT"
        try:
            from datetime import UTC, datetime
            from email.utils import parsedate_to_datetime

            retry_at = parsedate_to_datetime(value)
            return float(max(0.0, (retry_at - datetime.now(UTC)).total_seconds()))
        except (TypeError, ValueError):
            return None


def _use_external_embedder() -> bool:
    return bool(settings.EMBED_ENDPOINT and settings.EMBED_MODEL)


async def _embed_external_batch(
    codes: list[str], max_length: int = 512
) -> list[list[float]]:
    """Generate embeddings for multiple code snippets in a single API call.

    Requests are throttled by a shared token bucket and retried with backoff on
    429/5xx responses, honoring the Retry-After header when the server sends it.
    """
    headers = {"Content-Type": "application/json"}
    if settings.EMBED_API_KEY:
        headers["Authorization"] = f"Bearer {settings.EMBED_API_KEY}"

    payload: dict[str, Any] = {
        "model": settings.EMBED_MODEL,
        "input": codes,  # OpenAI-compatible APIs accept both string and list
        "max_length": max_length,
    }

    # Construct the full endpoint URL (append /embeddings if it's a base API endpoint)
    endpoint = settings.EMBED_ENDPOINT
    if endpoint and not endpoint.endswith("/embeddings"):
        endpoint = endpoint.rstrip("/") + "/embeddings"

    max_retries = max(settings.EMBED_MAX_RETRIES, 0)
    base_backoff = max(settings.EMBED_RETRY_BACKOFF, 0.1)

    last_status: int | None = None
    last_body: str = ""
    for attempt in range(max_retries + 1):
        await _get_rate_limiter().wait()

        async with httpx.AsyncClient(
            timeout=60.0
        ) as client:  # Increased timeout for batch
            resp = await client.post(endpoint, json=payload, headers=headers)  # type: ignore[arg-type]

        if resp.status_code < 400:
            data = resp.json()

            # Accept either {"embedding": [...]} or OpenAI-style {"data":[{"embedding": [...]}]}
            embeddings: list[list[float]] = []

            if (
                isinstance(data, dict)
                and "data" in data
                and isinstance(data["data"], list)
            ):
                # OpenAI-style response with multiple embeddings
                for item in data["data"]:
                    if isinstance(item, dict) and "embedding" in item:
                        embeddings.append(item["embedding"])
                    elif isinstance(item, list):
                        embeddings.append(item)
            elif isinstance(data, dict) and "embedding" in data:
                # Single embedding response
                embeddings.append(data["embedding"])
            elif isinstance(data, list):
                # Direct list of embeddings
                embeddings = data
            else:
                raise EmbeddingError(
                    f"External embedder returned unexpected payload: {data}"
                )

            if len(embeddings) != len(codes):
                raise EmbeddingError(
                    f"Expected {len(codes)} embeddings, got {len(embeddings)}"
                )

            return embeddings

        last_status = resp.status_code
        last_body = resp.text
        retryable = resp.status_code in (429, 500, 502, 503, 504)
        if retryable and attempt < max_retries:
            retry_after = _parse_retry_after(resp.headers)
            delay = (
                retry_after if retry_after is not None else base_backoff * (2**attempt)
            )
            logger.warning(
                "Embedder returned HTTP {} (attempt {}/{}); retrying in {:.1f}s",
                resp.status_code,
                attempt + 1,
                max_retries,
                delay,
            )
            await asyncio.sleep(delay)
            continue

        if resp.status_code == 429:
            raise EmbeddingError(
                f"External embedder rate limit exceeded after {max_retries} retries "
                f"(last status {resp.status_code}): {resp.text}"
            )
        raise EmbeddingError(f"External embedder error {resp.status_code}: {resp.text}")

    raise EmbeddingError(
        f"External embedder rate limit exceeded after {max_retries} retries "
        f"(last status {last_status}): {last_body}"
    )


async def _embed_external(code: str, max_length: int = 512) -> list[float]:
    """Generate a single embedding."""
    embeddings = await _embed_external_batch([code], max_length=max_length)
    return embeddings[0]


def _no_embedder_error() -> EmbeddingError:
    return EmbeddingError(
        "No embedder configured. Set EMBED_ENDPOINT and EMBED_MODEL in .env "
        "(with optional EMBED_API_KEY)."
    )


def embed_code(code: str, max_length: int = 512) -> list[float]:
    """Generate an embedding using the external API.

    This function handles both sync and async contexts by checking if an event loop
    is already running.
    """

    if _use_external_embedder():
        try:
            # Check if we're already in an async context
            asyncio.get_running_loop()
            # If we get here, we're in an async context
            raise RuntimeError(
                "embed_code() cannot be called directly from async context. "
                "Use embed_code_async() instead or await the async function."
            )
        except RuntimeError as e:
            # If "no running event loop" error, we're in sync context
            if "no running event loop" in str(e).lower():
                return asyncio.run(_embed_external(code, max_length=max_length))
            # If it's our custom error, re-raise it
            raise

    raise _no_embedder_error()


async def embed_code_async(code: str, max_length: int = 512) -> list[float]:
    """Async version of embed_code for use in async contexts (e.g., LLM agents).

    Use this when calling from async code (like pydantic_ai tools).
    """
    if _use_external_embedder():
        return await _embed_external(code, max_length=max_length)

    raise _no_embedder_error()


def embed_code_batch(
    codes: list[str], max_length: int = 512, batch_size: int = 100
) -> list[list[float]]:
    """Generate embeddings for multiple code snippets in batches for better performance.

    Args:
        codes: List of code strings to embed
        max_length: Maximum token length per code snippet
        batch_size: Number of codes to embed per API call (default 100)

    Returns:
        List of embeddings, one per code string, in the same order
    """
    if not codes:
        return []

    if _use_external_embedder():

        async def _batch_embed():
            all_embeddings: list[list[float]] = []
            for i in range(0, len(codes), batch_size):
                batch = codes[i : i + batch_size]
                batch_embeddings = await _embed_external_batch(
                    batch, max_length=max_length
                )
                all_embeddings.extend(batch_embeddings)
            return all_embeddings

        try:
            # Check if we're already in an async context
            asyncio.get_running_loop()
            raise RuntimeError(
                "embed_code_batch() cannot be called directly from async context. "
                "Use embed_code_batch_async() instead."
            )
        except RuntimeError as e:
            if "no running event loop" in str(e).lower():
                return asyncio.run(_batch_embed())
            raise

    raise _no_embedder_error()


async def embed_code_batch_async(
    codes: list[str], max_length: int = 512, batch_size: int = 100
) -> list[list[float]]:
    """Async version of embed_code_batch for use in async contexts.

    Use this when calling from async code (like pydantic_ai tools).
    """
    if not codes:
        return []

    if _use_external_embedder():
        all_embeddings: list[list[float]] = []
        for i in range(0, len(codes), batch_size):
            batch = codes[i : i + batch_size]
            batch_embeddings = await _embed_external_batch(batch, max_length=max_length)
            all_embeddings.extend(batch_embeddings)
        return all_embeddings

    raise _no_embedder_error()
