from pathlib import Path
from unittest.mock import MagicMock

import pytest

from codebase_rag.graph_updater import GraphUpdater
from codebase_rag.tools.semantic_seed_strategy import (
    _choose_expansion_depth,
    _gather_seeds,
)


def _make_updater(repo_path: Path) -> GraphUpdater:
    return GraphUpdater(
        ingestor=MagicMock(),
        repo_path=repo_path,
        parsers={},
        queries={},
    )


@pytest.mark.parametrize(
    ("score", "expected_depth"),
    [
        (0.8, 1),
        (0.79, 2),
        (0.7, 2),
        (0.69, 3),
    ],
)
def test_expansion_depth_uses_lower_similarity_bands(
    score: float, expected_depth: int
) -> None:
    assert _choose_expansion_depth([score]) == expected_depth


def test_embedding_chunks_include_frontend_module_and_asset_content(
    tmp_path: Path,
) -> None:
    component = tmp_path / "src" / "CheckoutPanel.tsx"
    stylesheet = tmp_path / "src" / "checkout-panel.scss"
    component.parent.mkdir()
    component.write_text(
        """
export const CheckoutPanel = () => (
  <section aria-label="payment confirmation">Confirm purchase</section>
);
""".strip(),
        encoding="utf-8",
    )
    stylesheet.write_text(
        ".checkout-panel { display: grid; color: rebeccapurple; }",
        encoding="utf-8",
    )

    updater = _make_updater(tmp_path)
    chunks = updater._prepare_embedding_chunks(
        [
            {
                "node_id": 10,
                "qualified_name": "shop.src.CheckoutPanel",
                "path": "src/CheckoutPanel.tsx",
                "node_type": "Module",
            },
            {
                "node_id": 11,
                "qualified_name": None,
                "path": "src/checkout-panel.scss",
                "node_type": "File",
            },
        ]
    )

    documents = {node_id: document for document, node_id, _ in chunks}
    assert set(documents) == {10, 11}
    assert "payment confirmation" in documents[10]
    assert "Confirm purchase" in documents[10]
    assert "File: src/CheckoutPanel.tsx" in documents[10]
    assert ".checkout-panel" in documents[11]
    assert "Entity: file:src/checkout-panel.scss" in documents[11]


def test_full_embedding_pass_stores_frontend_module_chunks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    component = tmp_path / "CartSummary.tsx"
    component.write_text(
        'export const CartSummary = () => <aside aria-label="cart totals" />;',
        encoding="utf-8",
    )
    updater = _make_updater(tmp_path)
    updater.ingestor._execute_query.return_value = [
        {
            "node_id": 42,
            "qualified_name": "shop.CartSummary",
            "start_line": None,
            "end_line": None,
            "path": "CartSummary.tsx",
            "node_type": "Module",
        }
    ]
    stored: list[tuple[int, list[float], str]] = []

    # Embedding APIs and Qdrant are external and nondeterministic; this test keeps
    # the ingestion/query contract real while replacing only those boundaries.
    monkeypatch.setattr(
        "codebase_rag.graph_updater.has_semantic_dependencies", lambda: True
    )
    monkeypatch.setattr(
        "codebase_rag.embedder.embed_code_batch",
        lambda documents, batch_size: [
            [float(len(document))] for document in documents
        ],
    )
    monkeypatch.setattr(
        "codebase_rag.vector_store.batch_store_embeddings",
        lambda data, repo_path: stored.extend(data),
    )

    updater._generate_semantic_embeddings()

    query = updater.ingestor._execute_query.call_args.args[0]
    params = updater.ingestor._execute_query.call_args.args[1]
    assert "n:Module" in query
    assert "n:File" in query
    assert ".scss" in params["asset_extensions"]
    assert len(stored) == 1
    assert stored[0][0] == 42
    assert stored[0][1][0] > 100
    assert stored[0][2] == "shop.CartSummary"


@pytest.mark.asyncio
async def test_lexical_seed_fallback_matches_lowercase_frontend_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_semantic_results(
        query: str, top_k: int, repo_path: str | None = None
    ) -> list[dict]:
        return []

    def frontend_path_result(
        *, host: str, port: int, query: str, params: dict
    ) -> list[dict]:
        assert "toLower(coalesce(n.path" in query
        assert "checkout" in params["keywords"]
        return [
            {
                "node_id": 7,
                "qualified_name": "shop.checkout-panel",
                "name": "checkout-panel.tsx",
                "type": ["Module"],
            }
        ]

    # Memgraph is replaced because this unit verifies query construction against
    # an isolated repository path without creating persistent graph data.
    monkeypatch.setattr(
        "codebase_rag.tools.semantic_seed_strategy.semantic_code_search_async",
        no_semantic_results,
    )
    monkeypatch.setattr(
        "codebase_rag.tools.semantic_seed_strategy.execute_read_query",
        frontend_path_result,
    )

    seeds = await _gather_seeds(
        ["where is checkout confirmation rendered?"], "/repo", top_k=10
    )

    assert len(seeds) == 1
    assert seeds[0].node_type == "Module"
    assert seeds[0].name == "checkout-panel.tsx"
    assert seeds[0].score == pytest.approx(0.7)
