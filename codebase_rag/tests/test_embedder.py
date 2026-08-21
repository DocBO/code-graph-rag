from __future__ import annotations

import asyncio
from datetime import UTC
from unittest.mock import AsyncMock, MagicMock

import pytest

from codebase_rag.embedder import (
    EmbeddingError,
    EmbedRateLimiter,
    _embed_external_batch,
    _parse_retry_after,
)


class NoopRateLimiter:
    async def wait(self) -> None:
        return None


class TestEmbedRateLimiter:
    def test_allows_first_request_immediately(self) -> None:
        limiter = EmbedRateLimiter(requests_per_minute=60)

        async def _run() -> None:
            start = asyncio.get_running_loop().time()
            await limiter.wait()
            assert asyncio.get_running_loop().time() - start < 0.1

        asyncio.run(_run())

    def test_throttles_burst_to_one_request_per_interval(self) -> None:
        limiter = EmbedRateLimiter(requests_per_minute=60)  # 1 per second

        async def _run() -> None:
            start = asyncio.get_running_loop().time()
            await limiter.wait()
            await limiter.wait()
            elapsed = asyncio.get_running_loop().time() - start
            assert elapsed >= 0.9

        asyncio.run(_run())


class TestParseRetryAfter:
    def test_parses_seconds(self) -> None:
        headers = MagicMock()
        headers.get.return_value = "5"
        assert _parse_retry_after(headers) == 5.0

    def test_parses_http_date(self) -> None:
        from datetime import datetime, timedelta

        future = (datetime.now(UTC) + timedelta(seconds=30)).strftime(
            "%a, %d %b %Y %H:%M:%S GMT"
        )
        headers = MagicMock()
        headers.get.return_value = future
        result = _parse_retry_after(headers)
        assert result is not None
        assert result > 0

    def test_returns_none_when_missing(self) -> None:
        headers = MagicMock()
        headers.get.return_value = None
        assert _parse_retry_after(headers) is None


class TestEmbedExternalBatchRetry:
    def test_success_returns_embeddings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class FakeClient:
            def __init__(self, *args: object, **kwargs: object) -> None:
                self.post_calls = 0

            async def __aenter__(self) -> FakeClient:
                return self

            async def __aexit__(self, *args: object) -> None:
                return None

            async def post(self, *args: object, **kwargs: object) -> object:
                self.post_calls += 1
                return MagicMock(
                    status_code=200,
                    headers={},
                    json=lambda: {"data": [{"embedding": [0.1, 0.2]}]},
                )

        client = FakeClient()
        monkeypatch.setattr("codebase_rag.embedder.httpx.AsyncClient", lambda **kw: client)
        monkeypatch.setattr(
            "codebase_rag.embedder._get_rate_limiter", lambda: NoopRateLimiter()
        )

        result = asyncio.run(_embed_external_batch(["def f(): pass"]))
        assert result == [[0.1, 0.2]]

    def test_429_then_success_retries_and_waits(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        responses = [
            MagicMock(
                status_code=429,
                headers={"Retry-After": "0"},
                text="rate limited",
            ),
            MagicMock(
                status_code=200,
                headers={},
                json=lambda: {"data": [{"embedding": [1.0]}]},
            ),
        ]
        client = AsyncMock()
        client.post = AsyncMock(side_effect=responses)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)

        monkeypatch.setattr("codebase_rag.embedder.httpx.AsyncClient", lambda **kw: client)
        monkeypatch.setattr(
            "codebase_rag.embedder._get_rate_limiter", lambda: NoopRateLimiter()
        )
        sleep_calls: list[float] = []

        async def fake_sleep(delay: float) -> None:
            sleep_calls.append(delay)

        monkeypatch.setattr("codebase_rag.embedder.asyncio.sleep", fake_sleep)

        result = asyncio.run(_embed_external_batch(["def f(): pass"]))
        assert result == [[1.0]]
        assert client.post.await_count == 2
        assert sleep_calls == [0.0]

    def test_429_exhausts_retries_and_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("codebase_rag.embedder.settings.EMBED_MAX_RETRIES", 2)
        monkeypatch.setattr("codebase_rag.embedder.settings.EMBED_RETRY_BACKOFF", 0.0)

        responses = [
            MagicMock(status_code=429, headers={}, text="rate limited")
            for _ in range(3)
        ]
        client = AsyncMock()
        client.post = AsyncMock(side_effect=responses)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)

        monkeypatch.setattr("codebase_rag.embedder.httpx.AsyncClient", lambda **kw: client)
        monkeypatch.setattr(
            "codebase_rag.embedder._get_rate_limiter", lambda: NoopRateLimiter()
        )

        async def fake_sleep(delay: float) -> None:
            return None

        monkeypatch.setattr("codebase_rag.embedder.asyncio.sleep", fake_sleep)

        with pytest.raises(EmbeddingError, match="rate limit exceeded"):
            asyncio.run(_embed_external_batch(["def f(): pass"]))
        assert client.post.await_count == 3
