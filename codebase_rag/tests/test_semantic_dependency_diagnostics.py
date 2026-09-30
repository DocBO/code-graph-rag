"""Diagnostics for a skipped semantic embedding pass.

A skip used to log one catch-all sentence, which cannot distinguish a missing
``semantic`` extra from an unread ``.env`` or a different virtualenv — the
failure mode is silent, because the run still reports success afterwards.
These tests pin the extended, self-describing report.
"""

from __future__ import annotations

import sys
from collections.abc import Generator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from loguru import logger

from codebase_rag.config import settings
from codebase_rag.graph_updater import GraphUpdater


@pytest.fixture
def log_messages() -> Generator[list[str], None, None]:
    """Capture log messages using a custom sink."""
    messages: list[str] = []

    def sink(message: Any) -> None:
        messages.append(str(message))

    handler_id = logger.add(sink, format="{message}")
    yield messages
    logger.remove(handler_id)


def _make_updater(repo_path: Path) -> GraphUpdater:
    return GraphUpdater(
        ingestor=MagicMock(),
        repo_path=repo_path,
        parsers={},
        queries={},
    )


class TestSkippedSemanticPassReport:
    def test_embedding_pass_names_the_missing_requirement(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        log_messages: list[str],
    ) -> None:
        monkeypatch.setattr(
            "codebase_rag.graph_updater.has_semantic_dependencies", lambda: False
        )
        monkeypatch.setattr(settings, "EMBED_MODEL", None)
        monkeypatch.setattr(
            "codebase_rag.utils.dependencies.has_qdrant_client", lambda: True
        )
        updater = _make_updater(tmp_path)

        updater._generate_semantic_embeddings()

        warnings = [
            message
            for message in log_messages
            if "skipping embedding generation" in message
        ]
        assert len(warnings) == 1
        assert "EMBED_MODEL is not set" in warnings[0]
        assert "EMBED_MODEL=<unset>" in warnings[0]
        assert f"python={sys.executable}" in warnings[0]
        updater.ingestor._execute_query.assert_not_called()

    def test_incremental_update_reports_the_cause_once(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        log_messages: list[str],
    ) -> None:
        monkeypatch.setattr(
            "codebase_rag.graph_updater.has_semantic_dependencies", lambda: False
        )
        monkeypatch.setattr(settings, "EMBED_ENDPOINT", None)
        monkeypatch.setattr(
            "codebase_rag.utils.dependencies.has_qdrant_client", lambda: True
        )
        updater = _make_updater(tmp_path)

        # The watcher calls this for every debounce batch; the first call must
        # explain the degraded state without repeating itself on every change.
        updater.update_embeddings_for_files([tmp_path / "first.py"])
        updater.update_embeddings_for_files([tmp_path / "second.py"])

        warnings = [
            message
            for message in log_messages
            if "skipping incremental embedding update" in message
        ]
        assert len(warnings) == 1
        assert "EMBED_ENDPOINT is not set" in warnings[0]
        updater.ingestor._execute_query.assert_not_called()

    def test_configured_qdrant_server_lets_the_pass_run_without_the_client(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        log_messages: list[str],
    ) -> None:
        """A configured Qdrant server is a usable backend through its HTTP API.

        The ``semantic`` extra only supplies the Python client; without it the
        pass must still run against a configured server instead of skipping.
        """
        python_file = tmp_path / "app.py"
        python_file.write_text(
            'def run_job():\n    """Run a scheduled job."""\n    return "body"\n',
            encoding="utf-8",
        )
        monkeypatch.setattr(settings, "EMBED_ENDPOINT", "https://embed.test/v1")
        monkeypatch.setattr(settings, "EMBED_MODEL", "test-embedding-model")
        monkeypatch.setattr(settings, "QDRANT_HOST", "qdrant.test")
        monkeypatch.setattr(settings, "QDRANT_PORT", 6333)
        monkeypatch.setattr(
            "codebase_rag.utils.dependencies.has_qdrant_client", lambda: False
        )
        monkeypatch.setattr(
            "codebase_rag.vector_store.clean_collection", lambda repo_path: None
        )
        monkeypatch.setattr(
            "codebase_rag.embedder.embed_code_batch",
            lambda documents, batch_size: [
                [float(len(document))] for document in documents
            ],
        )
        stored: list[tuple[int, list[float], str]] = []
        monkeypatch.setattr(
            "codebase_rag.vector_store.batch_store_embeddings",
            lambda data, repo_path: stored.extend(data),
        )
        updater = _make_updater(tmp_path)
        updater.ingestor._execute_query.return_value = [
            {
                "node_id": 7,
                "qualified_name": "app.run_job",
                "start_line": 1,
                "end_line": 3,
                "path": "app.py",
                "node_type": "Function",
            }
        ]

        updater._generate_semantic_embeddings()

        assert not [
            message
            for message in log_messages
            if "skipping embedding generation" in message
        ]
        updater.ingestor._execute_query.assert_called_once()
        assert len(stored) == 1
        assert stored[0][0] == 7
