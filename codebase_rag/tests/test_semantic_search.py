from __future__ import annotations

import pytest

from codebase_rag.tools.semantic_search import (
    SemanticSearchOutcome,
    SemanticSearchStatus,
    semantic_code_search_outcome,
    semantic_match_label,
)


class TestSemanticSearchOutcome:
    def test_labels_markdown_matches_with_their_file_path(self) -> None:
        assert (
            semantic_match_label(
                {
                    "node_id": 42,
                    "qualified_name": None,
                    "file_path": "docs/E2E_FRONTEND_MIMIC.md",
                }
            )
            == "docs/E2E_FRONTEND_MIMIC.md"
        )

    def test_no_dependencies_status_when_extra_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "codebase_rag.tools.semantic_search.has_semantic_dependencies",
            lambda: False,
        )

        outcome = semantic_code_search_outcome("auth", top_k=5, repo_path="/tmp/repo")

        assert isinstance(outcome, SemanticSearchOutcome)
        assert outcome.status == SemanticSearchStatus.NO_DEPENDENCIES
        assert outcome.matches == []
        assert "semantic" in outcome.message

    def test_failed_status_when_embedder_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "codebase_rag.tools.semantic_search.has_semantic_dependencies",
            lambda: True,
        )

        def fake_embed(query: str) -> object:
            raise RuntimeError("embedder exploded")

        monkeypatch.setattr("codebase_rag.embedder.embed_code", fake_embed)

        outcome = semantic_code_search_outcome("auth", top_k=5, repo_path="/tmp/repo")

        assert outcome.status == SemanticSearchStatus.FAILED
        assert outcome.matches == []
        assert "embedder exploded" in outcome.message

    def test_ok_status_with_matches(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "codebase_rag.tools.semantic_search.has_semantic_dependencies",
            lambda: True,
        )
        monkeypatch.setattr(
            "codebase_rag.embedder.embed_code",
            lambda query: [0.1, 0.2],
        )
        monkeypatch.setattr(
            "codebase_rag.vector_store.search_embedding_matches",
            lambda query_embedding, top_k, repo_path: [
                {
                    "node_id": 42,
                    "score": 0.91,
                    "matched_qualified_name": "x",
                    "file_path": "docs/authentication.md",
                },
            ],
        )

        def fake_execute_read_query(
            host: str, port: int, query: str, params: dict[str, object]
        ) -> list[dict[str, object]]:
            return [
                {
                    "node_id": 42,
                    "qualified_name": "pkg.auth.login",
                    "type": ["Function"],
                    "name": "login",
                }
            ]

        monkeypatch.setattr(
            "codebase_rag.services.graph_service.execute_read_query",
            fake_execute_read_query,
        )

        outcome = semantic_code_search_outcome("auth", top_k=5, repo_path="/tmp/repo")

        assert outcome.status == SemanticSearchStatus.OK
        assert len(outcome.matches) == 1
        assert outcome.matches[0]["qualified_name"] == "pkg.auth.login"
        assert outcome.matches[0]["score"] == 0.91
        assert outcome.matches[0]["file_path"] == "docs/authentication.md"
