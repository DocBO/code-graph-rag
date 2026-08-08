from pathlib import Path
from unittest.mock import MagicMock

import pytest
from watchdog.events import (
    DirCreatedEvent,
    FileCreatedEvent,
    FileDeletedEvent,
    FileModifiedEvent,
    FileMovedEvent,
)

from realtime_updater import (
    CodeChangeEventHandler,
    MODULE_CALLER_PATHS_QUERY,
    MODULE_CALLS_DELETE_QUERY,
    MODULE_SUBGRAPH_DELETE_QUERY,
)


@pytest.fixture
def event_handler(mock_updater: MagicMock) -> CodeChangeEventHandler:
    """Provides a CodeChangeEventHandler instance with a mocked updater."""
    return CodeChangeEventHandler(mock_updater, debounce_seconds=3600)


def test_file_creation_flow(
    event_handler: CodeChangeEventHandler, mock_updater: MagicMock, temp_repo: Path
) -> None:
    """Test that creating a new file triggers parsing and ingestion."""
    test_file = temp_repo / "new_file.py"
    test_file.write_text("def new_func(): pass")
    event = FileCreatedEvent(str(test_file))

    event_handler.dispatch(event)
    event_handler._process_pending_changes()

    assert mock_updater.ingestor.execute_write.call_count == 2
    mock_updater.factory.definition_processor.process_file.assert_called_once_with(
        test_file,
        "python",
        mock_updater.queries,
        mock_updater.factory.structure_processor.structural_elements,
    )
    mock_updater.update_embeddings_for_files.assert_called_once_with([test_file])
    mock_updater.ingestor.flush_all.assert_called_once()


def test_file_modification_flow(
    event_handler: CodeChangeEventHandler, mock_updater: MagicMock, temp_repo: Path
) -> None:
    """Test that modifying a file triggers removal and re-ingestion."""
    test_file = temp_repo / "existing_file.py"
    test_file.touch()
    event = FileModifiedEvent(str(test_file))

    event_handler.dispatch(event)
    event_handler._process_pending_changes()

    assert mock_updater.ingestor.execute_write.call_count == 2
    assert (
        mock_updater.ingestor.execute_write.call_args_list[0].args[0]
        == MODULE_SUBGRAPH_DELETE_QUERY
    )
    assert "[:DEFINES*0..]" in MODULE_SUBGRAPH_DELETE_QUERY
    assert "[*0..]" not in MODULE_SUBGRAPH_DELETE_QUERY
    assert (
        mock_updater.ingestor.execute_write.call_args_list[1].args[0]
        == MODULE_CALLS_DELETE_QUERY
    )
    assert "MATCH (n)-[r:CALLS]->()" not in MODULE_CALLS_DELETE_QUERY
    assert "OPTIONAL MATCH" not in MODULE_CALLER_PATHS_QUERY
    assert "[:DEFINES|DEFINES_METHOD*..5]" in MODULE_CALLER_PATHS_QUERY
    mock_updater.ingestor.fetch_all.assert_called_once_with(
        MODULE_CALLER_PATHS_QUERY,
        {"path": "existing_file.py", "repo_path": mock_updater.ingestor.repo_path},
    )
    mock_updater._process_files.assert_not_called()
    mock_updater._process_function_calls.assert_not_called()
    mock_updater.process_function_calls_for_files.assert_called_once_with([test_file])
    mock_updater.factory.definition_processor.process_file.assert_called_once_with(
        test_file,
        "python",
        mock_updater.queries,
        mock_updater.factory.structure_processor.structural_elements,
    )
    mock_updater.update_embeddings_for_files.assert_called_once_with([test_file])
    mock_updater.ingestor.flush_all.assert_called_once()


def test_file_deletion_flow(
    event_handler: CodeChangeEventHandler, mock_updater: MagicMock, temp_repo: Path
) -> None:
    """Test that deleting a file triggers its removal from the graph."""
    test_file = temp_repo / "deleted_file.py"
    event = FileDeletedEvent(str(test_file))

    event_handler.dispatch(event)
    event_handler._process_pending_changes()

    assert mock_updater.ingestor.execute_write.call_count == 1
    mock_updater.factory.definition_processor.process_file.assert_not_called()
    mock_updater.update_embeddings_for_files.assert_called_once_with([test_file])
    mock_updater.ingestor.flush_all.assert_called_once()


def test_irrelevant_files_are_ignored(
    event_handler: CodeChangeEventHandler, mock_updater: MagicMock, temp_repo: Path
) -> None:
    """Test that files in ignored directories are skipped."""
    ignored_dir = temp_repo / ".git"
    ignored_dir.mkdir()
    ignored_file = ignored_dir / "config"
    ignored_file.touch()
    event = FileCreatedEvent(str(ignored_file))

    event_handler.dispatch(event)

    mock_updater.ingestor.execute_write.assert_not_called()
    mock_updater.factory.definition_processor.process_file.assert_not_called()
    mock_updater.ingestor.flush_all.assert_not_called()


def test_directory_creation_is_ignored(
    event_handler: CodeChangeEventHandler, mock_updater: MagicMock, temp_repo: Path
) -> None:
    """Test that creating a directory does not trigger any graph operations."""
    test_dir = temp_repo / "new_dir"
    event = DirCreatedEvent(str(test_dir))

    event_handler.dispatch(event)

    mock_updater.ingestor.execute_write.assert_not_called()
    mock_updater.factory.definition_processor.process_file.assert_not_called()
    mock_updater.ingestor.flush_all.assert_not_called()


def test_unsupported_file_types_are_ignored(
    event_handler: CodeChangeEventHandler, mock_updater: MagicMock, temp_repo: Path
) -> None:
    """Test that changing an unsupported file type is ignored after deletion query."""
    unsupported_file = temp_repo / "document.md"
    unsupported_file.write_text("# Markdown file")
    event = FileModifiedEvent(str(unsupported_file))

    event_handler.dispatch(event)
    event_handler._process_pending_changes()

    assert mock_updater.ingestor.execute_write.call_count == 1
    mock_updater.factory.definition_processor.process_file.assert_not_called()
    mock_updater.update_embeddings_for_files.assert_called_once_with([unsupported_file])
    mock_updater.ingestor.flush_all.assert_called_once()


def test_file_move_updates_source_and_destination(
    event_handler: CodeChangeEventHandler, mock_updater: MagicMock, temp_repo: Path
) -> None:
    """Test moved files queue both source deletion and destination re-ingestion."""
    src_file = temp_repo / "old_name.py"
    dest_file = temp_repo / "new_name.py"
    dest_file.write_text("def renamed(): pass")
    event = FileMovedEvent(str(src_file), str(dest_file))

    event_handler.dispatch(event)
    event_handler._process_pending_changes()

    assert mock_updater.ingestor.execute_write.call_count == 3
    mock_updater.ingestor.fetch_all.assert_called_once_with(
        MODULE_CALLER_PATHS_QUERY,
        {"path": "new_name.py", "repo_path": mock_updater.ingestor.repo_path},
    )
    mock_updater.factory.definition_processor.process_file.assert_called_once_with(
        dest_file,
        "python",
        mock_updater.queries,
        mock_updater.factory.structure_processor.structural_elements,
    )
    mock_updater.process_function_calls_for_files.assert_called_once_with([dest_file])
    embed_paths = mock_updater.update_embeddings_for_files.call_args.args[0]
    assert set(embed_paths) == {src_file, dest_file}
