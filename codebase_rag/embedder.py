"""Embedding clients (external or local)."""

from __future__ import annotations

import functools
from typing import Any

import httpx

from .config import settings
from .utils.dependencies import has_torch, has_transformers


class EmbeddingError(Exception):
    """Raised when embedding generation fails."""


def _use_external_embedder() -> bool:
    return bool(settings.EMBED_ENDPOINT and settings.EMBED_MODEL)


async def _embed_external_batch(
    codes: list[str], max_length: int = 512
) -> list[list[float]]:
    """Generate embeddings for multiple code snippets in a single API call."""
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

    async with httpx.AsyncClient(timeout=60.0) as client:  # Increased timeout for batch
        resp = await client.post(endpoint, json=payload, headers=headers)  # type: ignore[arg-type]
        if resp.status_code >= 400:
            raise EmbeddingError(
                f"External embedder error {resp.status_code}: {resp.text}"
            )
        data = resp.json()

        # Accept either {"embedding": [...]} or OpenAI-style {"data":[{"embedding": [...]}]}
        embeddings: list[list[float]] = []

        if isinstance(data, dict) and "data" in data and isinstance(data["data"], list):
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


async def _embed_external(code: str, max_length: int = 512) -> list[float]:
    """Generate a single embedding."""
    embeddings = await _embed_external_batch([code], max_length=max_length)
    return embeddings[0]


# Local UniXcoder fallback

if has_torch() and has_transformers():
    import torch

    from .unixcoder import UniXcoder

    @functools.lru_cache(maxsize=1)
    def get_model():
        model = UniXcoder("microsoft/unixcoder-base")
        model.eval()
        if torch.cuda.is_available():
            model = model.cuda()
        return model

    def _embed_local(code: str, max_length: int = 512) -> list[float]:
        model = get_model()
        device = next(model.parameters()).device
        tokens = model.tokenize([code], max_length=max_length)
        tokens_tensor = torch.tensor(tokens).to(device)
        with torch.no_grad():
            _, sentence_embeddings = model(tokens_tensor)
            embedding = sentence_embeddings.cpu().numpy()
        return embedding[0].tolist()
else:

    def _embed_local(code: str, max_length: int = 512) -> list[float]:
        raise EmbeddingError("Local embedding requires torch and transformers.")


def embed_code(code: str, max_length: int = 512) -> list[float]:
    """Generate an embedding using external API if configured, else local UniXcoder.
    
    This function handles both sync and async contexts by checking if an event loop
    is already running.
    """

    if _use_external_embedder():
        import asyncio

        try:
            # Check if we're already in an async context
            loop = asyncio.get_running_loop()
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

    return _embed_local(code, max_length=max_length)


async def embed_code_async(code: str, max_length: int = 512) -> list[float]:
    """Async version of embed_code for use in async contexts (e.g., LLM agents).
    
    Use this when calling from async code (like pydantic_ai tools).
    """
    if _use_external_embedder():
        return await _embed_external(code, max_length=max_length)

    return _embed_local(code, max_length=max_length)


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
        import asyncio

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
            loop = asyncio.get_running_loop()
            raise RuntimeError(
                "embed_code_batch() cannot be called directly from async context. "
                "Use embed_code_batch_async() instead."
            )
        except RuntimeError as e:
            if "no running event loop" in str(e).lower():
                return asyncio.run(_batch_embed())
            raise
    else:
        # Local embedder - process sequentially
        return [_embed_local(code, max_length=max_length) for code in codes]


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
    else:
        # Local embedder - process sequentially
        return [_embed_local(code, max_length=max_length) for code in codes]
