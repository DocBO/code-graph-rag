from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from codebase_rag.services.graph_service import MemgraphIngestor


def _create_ingestor_with_mocked_connection(
    batch_size: int = 2,
) -> tuple[MemgraphIngestor, MagicMock]:
    """Create a MemgraphIngestor with a mocked mgclient connection."""
    ingestor = MemgraphIngestor(host="localhost", port=7687, batch_size=batch_size)
    conn_mock = MagicMock()
    cursor_mock = MagicMock()
    # Default to a non-returning query result so fetch loops terminate.
    cursor_mock.description = None
    cursor_mock.fetchone.return_value = None
    conn_mock.cursor.return_value = cursor_mock
    ingestor.conn = conn_mock
    return ingestor, cursor_mock


def test_node_batch_flushes_when_threshold_reached() -> None:
    ingestor, cursor_mock = _create_ingestor_with_mocked_connection()

    ingestor.ensure_node_batch("File", {"path": "a", "name": "a.txt"})
    assert len(ingestor.node_buffer) == 1
    cursor_mock.execute.assert_not_called()

    ingestor.ensure_node_batch("File", {"path": "b", "name": "b.txt"})

    assert len(ingestor.node_buffer) == 0
    cursor_mock.execute.assert_called_once()
    executed_query = cursor_mock.execute.call_args[0][0]
    assert "UNWIND $batch" in executed_query
    cursor_mock.close.assert_called()


def test_node_batch_preserves_per_row_properties() -> None:
    ingestor, cursor_mock = _create_ingestor_with_mocked_connection()

    ingestor.ensure_node_batch(
        "Function",
        {"qualified_name": "demo.fn1", "name": "fn1", "decorators": ["@a"]},
    )
    ingestor.ensure_node_batch(
        "Function",
        {"qualified_name": "demo.fn2", "name": "fn2"},
    )

    executed_query = cursor_mock.execute.call_args[0][0]
    assert "SET n += row.props" in executed_query

    batch_rows = cursor_mock.execute.call_args[0][1]["batch"]
    expected_repo_path = ingestor.repo_path
    assert batch_rows == [
        {
            "id": "demo.fn1",
            "props": {
                "name": "fn1",
                "decorators": ["@a"],
                "_repo_path": expected_repo_path,
            },
        },
        {
            "id": "demo.fn2",
            "props": {"name": "fn2", "_repo_path": expected_repo_path},
        },
    ]


def test_relationship_batch_flushes_after_threshold_and_respects_node_flush() -> None:
    ingestor, cursor_mock = _create_ingestor_with_mocked_connection()
    # Relationship flush uses _execute_batch_with_return() and needs a finite
    # cursor stream to avoid infinite loops with MagicMock defaults.
    cursor_mock.description = [SimpleNamespace(name="created")]
    cursor_mock.fetchone.side_effect = [(2,), None]

    with patch.object(
        ingestor, "flush_nodes", wraps=ingestor.flush_nodes
    ) as flush_nodes_spy:
        ingestor.ensure_relationship_batch(
            ("Module", "qualified_name", "proj.module1"),
            "CONTAINS_FILE",
            ("File", "path", "file1"),
        )
        assert len(ingestor.relationship_buffer) == 1
        cursor_mock.execute.assert_not_called()

        ingestor.ensure_relationship_batch(
            ("Module", "qualified_name", "proj.module2"),
            "CONTAINS_FILE",
            ("File", "path", "file2"),
        )

        assert flush_nodes_spy.call_count == 1

    assert len(ingestor.relationship_buffer) == 0
    cursor_mock.execute.assert_called_once()
    executed_query = cursor_mock.execute.call_args[0][0]
    assert "UNWIND $batch" in executed_query
    cursor_mock.close.assert_called()
