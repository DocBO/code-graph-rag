from __future__ import annotations

import time
from pathlib import Path

from codebase_rag.ingest_metadata import (
    METADATA_FILENAME,
    compute_changes_since,
    read_ingest_metadata,
    summarize_ingest_status,
    write_ingest_metadata,
)


def test_write_and_read_ingest_metadata(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")

    meta = write_ingest_metadata(tmp_path)
    assert meta.metadata_path.name == METADATA_FILENAME
    assert meta.timestamp.tzinfo is not None
    assert "a.txt" in meta.file_index

    loaded = read_ingest_metadata(tmp_path)
    assert loaded is not None
    assert loaded.metadata_path == meta.metadata_path
    assert loaded.timestamp.tzinfo is not None


def test_compute_changes_since(tmp_path: Path) -> None:
    file_a = tmp_path / "a.txt"
    file_b = tmp_path / "b.txt"
    file_a.write_text("hello", encoding="utf-8")
    meta = write_ingest_metadata(tmp_path)

    time.sleep(1.1)
    # Modify and add files
    file_a.write_text("changed", encoding="utf-8")
    file_b.write_text("new", encoding="utf-8")

    current_index = {k: v for k, v in meta.file_index.items()}
    for path in [file_a, file_b]:
        current_index[path.relative_to(tmp_path).as_posix()] = (
            path.stat().st_mtime_ns / 1_000_000_000
        )

    changes = compute_changes_since(meta, current_index)
    assert changes["added"] == 1
    assert changes["modified"] == 1
    assert changes["deleted"] == 0
    assert changes["total"] == 2


def test_summarize_ingest_status_without_metadata(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hi", encoding="utf-8")
    last_ingest, changes, path = summarize_ingest_status(tmp_path)
    assert last_ingest is None
    assert changes["total"] >= 1
    assert path.name == METADATA_FILENAME
