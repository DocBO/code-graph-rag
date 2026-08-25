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


def test_embedding_chunks_include_only_python_api_descriptions_and_markdown(
    tmp_path: Path,
) -> None:
    python_file = tmp_path / "src" / "checkout.py"
    markdown_file = tmp_path / "docs" / "checkout.md"
    python_file.parent.mkdir()
    python_file.write_text(
        """
def confirm_purchase():
    \"\"\"Confirm payment and notify the customer.\"\"\"
    return "secret implementation body"
""".strip(),
        encoding="utf-8",
    )
    markdown_file.parent.mkdir()
    markdown_file.write_text(
        "# Checkout\n\nPayment confirmation documentation.",
        encoding="utf-8",
    )

    updater = _make_updater(tmp_path)
    chunks = updater._prepare_embedding_chunks(
        [
            {
                "node_id": 10,
                "qualified_name": "shop.src.confirm_purchase",
                "path": "src/checkout.py",
                "start_line": 1,
                "end_line": 3,
                "node_type": "Function",
            },
            {
                "node_id": 11,
                "qualified_name": None,
                "path": "docs/checkout.md",
                "node_type": "File",
            },
            {
                "node_id": 12,
                "qualified_name": "shop.src.CheckoutPanel",
                "path": "src/CheckoutPanel.tsx",
                "node_type": "Module",
            },
        ]
    )

    documents = {node_id: document for document, node_id, _, _ in chunks}
    assert set(documents) == {10, 11}
    assert "shop.src.confirm_purchase" in documents[10]
    assert "Confirm payment" in documents[10]
    assert "secret implementation body" not in documents[10]
    assert "Markdown file: docs/checkout.md" in documents[11]
    assert "Payment confirmation documentation" in documents[11]


def test_embedding_chunks_split_markdown_and_keep_python_name_without_docstring(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    python_file = tmp_path / "worker.py"
    markdown_file = tmp_path / "guide.md"
    python_file.write_text("def run_worker():\n    return 'implementation'\n")
    markdown_file.write_text("# Guide\n\n" + "Documentation text. " * 20)
    monkeypatch.setattr("codebase_rag.graph_updater.settings.EMBED_MAX_CHUNK_SIZE", 60)

    chunks = _make_updater(tmp_path)._prepare_embedding_chunks(
        [
            {
                "node_id": 1,
                "qualified_name": "app.run_worker",
                "path": "worker.py",
                "start_line": 1,
                "end_line": 2,
                "node_type": "Function",
            },
            {
                "node_id": 2,
                "qualified_name": None,
                "path": "guide.md",
                "node_type": "File",
            },
            {
                "node_id": 3,
                "qualified_name": "app.render",
                "path": "view.ts",
                "node_type": "Function",
            },
        ]
    )

    python_chunks = [chunk for chunk in chunks if chunk[1] == 1]
    markdown_chunks = [chunk for chunk in chunks if chunk[1] == 2]
    assert python_chunks == [
        ("Python Function: app.run_worker", 1, "app.run_worker", "worker.py")
    ]
    assert len(markdown_chunks) > 1
    assert all(len(document) <= 60 for document, *_ in markdown_chunks)
    assert [chunk[2] for chunk in markdown_chunks] == [
        f"file:guide.md_chunk_{index}" for index in range(len(markdown_chunks))
    ]
    assert not [chunk for chunk in chunks if chunk[1] == 3]


def test_full_embedding_pass_stores_python_and_markdown_chunks_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    python_file = tmp_path / "catalog.py"
    python_file.write_text(
        'def list_products():\n    """List products for the catalog."""\n    return []\n',
        encoding="utf-8",
    )
    updater = _make_updater(tmp_path)
    updater.ingestor._execute_query.return_value = [
        {
            "node_id": 42,
            "qualified_name": "shop.list_products",
            "start_line": 1,
            "end_line": 3,
            "path": "catalog.py",
            "node_type": "Function",
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
    # Collection cleanup is destructive and external; this test isolates the
    # document-selection boundary without writing to a real Qdrant instance.
    monkeypatch.setattr(
        "codebase_rag.vector_store.clean_collection", lambda repo_path: None
    )

    updater._generate_semantic_embeddings()

    query = updater.ingestor._execute_query.call_args.args[0]
    params = updater.ingestor._execute_query.call_args.args[1]
    assert "n:Function" in query
    assert "n:File" in query
    assert "path ENDS WITH '.py'" in query
    assert params["markdown_extension"] == ".md"
    assert len(stored) == 1
    assert stored[0][0] == 42
    assert stored[0][1][0] > 0
    assert stored[0][2] == "shop.list_products"


def test_incremental_embedding_replaces_only_python_and_markdown_documents(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    python_file = tmp_path / "jobs.py"
    markdown_file = tmp_path / "jobs.md"
    typescript_file = tmp_path / "jobs.ts"
    python_file.write_text(
        'def run_job():\n    """Run a scheduled job."""\n    return "body"\n',
        encoding="utf-8",
    )
    markdown_file.write_text("# Jobs\n\nSchedule and monitor jobs.", encoding="utf-8")
    typescript_file.write_text("export const run = () => 'body';", encoding="utf-8")
    updater = _make_updater(tmp_path)
    updater.ingestor._execute_query.side_effect = [
        [
            {
                "node_id": 20,
                "qualified_name": "app.run_job",
                "start_line": 1,
                "end_line": 3,
                "path": "jobs.py",
                "node_type": "Function",
            }
        ],
        [
            {
                "node_id": 21,
                "qualified_name": None,
                "start_line": None,
                "end_line": None,
                "path": "jobs.md",
                "node_type": "File",
            }
        ],
    ]
    stored: list[tuple[int, list[float], str, str, str]] = []
    deleted: list[str] = []

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
    monkeypatch.setattr(
        "codebase_rag.vector_store.delete_embeddings_for_files",
        lambda paths, repo_path: deleted.extend(paths),
    )

    updater.update_embeddings_for_files([python_file, markdown_file, typescript_file])

    assert deleted == ["jobs.py", "jobs.md", "jobs.ts"]
    assert {row[0] for row in stored} == {20, 21}
    assert "Run a scheduled job" in stored[0][3]
    assert "body" not in stored[0][3]
    assert "Schedule and monitor jobs" in stored[1][3]


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
