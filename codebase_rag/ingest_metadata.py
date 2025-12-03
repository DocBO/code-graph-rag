"""Helpers for tracking ingest metadata on a per-repo basis."""

from __future__ import annotations

import json
import os
import fnmatch
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .config import IGNORE_PATTERNS, IGNORE_SUFFIXES

METADATA_FILENAME = ".graphcode_ingest.json"


@dataclass
class IngestMetadata:
    timestamp: datetime
    file_index: dict[str, float]
    metadata_path: Path


def _should_ignore(path: Path) -> bool:
    name = path.name
    if name in IGNORE_PATTERNS:
        return True
    if path.suffix in IGNORE_SUFFIXES:
        return True
    return False


def _is_ignored(path: Path, repo_root: Path) -> bool:
    """Check if a path (file or directory) should be ignored."""
    rel_parts = path.relative_to(repo_root).parts
    # Check each segment against ignore patterns for directory-level exclusion
    for part in rel_parts:
        if part in IGNORE_PATTERNS:
            return True
    # Also allow fnmatch on the relative path to catch wildcards
    rel_str = path.relative_to(repo_root).as_posix()
    return any(fnmatch.fnmatch(rel_str, pattern) for pattern in IGNORE_PATTERNS)


def _walk_files(repo_path: Path) -> dict[str, float]:
    """Return mapping of relative file paths to mtime, honoring ignore patterns."""

    index: dict[str, float] = {}
    repo_path = repo_path.resolve()
    metadata_path = repo_path / METADATA_FILENAME

    for root, dirnames, filenames in os.walk(repo_path):
        current_root = Path(root)
        if _is_ignored(current_root, repo_path):
            dirnames[:] = []
            continue

        # Prune ignored directories in-place
        dirnames[:] = [d for d in dirnames if not _is_ignored(current_root / d, repo_path)]

        for filename in filenames:
            candidate = current_root / filename
            if candidate == metadata_path or _is_ignored(candidate, repo_path) or _should_ignore(candidate):
                continue
            try:
                rel = candidate.relative_to(repo_path).as_posix()
            except ValueError:
                continue
            try:
                stat_result = candidate.stat()
                index[rel] = stat_result.st_mtime_ns / 1_000_000_000
            except OSError:
                continue
    return index


def write_ingest_metadata(repo_path: Path) -> IngestMetadata:
    """Write ingest metadata file with current timestamp and file index."""

    repo_path = repo_path.resolve()
    file_index = _walk_files(repo_path)
    now = datetime.now(UTC)
    metadata_path = repo_path / METADATA_FILENAME
    payload = {
        "timestamp": now.isoformat(),
        "file_index": file_index,
        "repo_path": str(repo_path),
        "version": 1,
    }
    metadata_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return IngestMetadata(
        timestamp=now, file_index=file_index, metadata_path=metadata_path
    )


def read_ingest_metadata(repo_path: Path) -> IngestMetadata | None:
    """Load ingest metadata if it exists."""

    metadata_path = repo_path.resolve() / METADATA_FILENAME
    if not metadata_path.exists():
        return None

    try:
        data = json.loads(metadata_path.read_text(encoding="utf-8"))
        ts = datetime.fromisoformat(data.get("timestamp"))
        return IngestMetadata(
            timestamp=ts,
            file_index=data.get("file_index", {}),
            metadata_path=metadata_path,
        )
    except Exception:
        return None


def compute_changes_since(
    metadata: IngestMetadata, current_index: dict[str, float]
) -> dict[str, int]:
    """Compute added/modified/deleted counts relative to stored metadata."""

    previous_index = metadata.file_index
    prev_keys = set(previous_index.keys())
    curr_keys = set(current_index.keys())

    added = curr_keys - prev_keys
    deleted = prev_keys - curr_keys
    modified = {
        k
        for k in prev_keys & curr_keys
        if previous_index.get(k) != current_index.get(k)
    }

    return {
        "added": len(added),
        "deleted": len(deleted),
        "modified": len(modified),
        "total": len(added) + len(deleted) + len(modified),
    }


def summarize_ingest_status(repo_path: Path) -> tuple[str | None, dict[str, int], Path]:
    """Return (timestamp_iso or None, change_counts, metadata_path)."""

    repo_path = repo_path.resolve()
    metadata = read_ingest_metadata(repo_path)
    current_index = _walk_files(repo_path)

    if metadata is None:
        return (
            None,
            {
                "added": len(current_index),
                "deleted": 0,
                "modified": 0,
                "total": len(current_index),
            },
            repo_path / METADATA_FILENAME,
        )

    changes = compute_changes_since(metadata, current_index)
    return metadata.timestamp.isoformat(), changes, metadata.metadata_path
