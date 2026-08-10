import argparse
import sys
import threading
import time
from pathlib import Path
from typing import Any

from loguru import logger
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from codebase_rag.config import IGNORE_PATTERNS, IGNORE_SUFFIXES, settings
from codebase_rag.graph_updater import GraphUpdater
from codebase_rag.ingest_metadata import write_ingest_metadata
from codebase_rag.language_config import get_language_config
from codebase_rag.parser_loader import load_parsers
from codebase_rag.services.graph_service import MemgraphIngestor

MODULE_SUBGRAPH_DELETE_QUERY = """
MATCH (m:Module {path: $path, _repo_path: $repo_path})
OPTIONAL MATCH (m)-[:DEFINES*0..]->(defined)
OPTIONAL MATCH (defined)-[:DEFINES_METHOD*0..]->(node)
WITH collect(m) + collect(defined) + collect(node) AS nodes
UNWIND nodes AS node
WITH DISTINCT node
DETACH DELETE node
"""

MODULE_CALLS_DELETE_QUERY = """
MATCH (m:Module {path: $path, _repo_path: $repo_path})
OPTIONAL MATCH (m)-[:DEFINES*0..]->(defined)
OPTIONAL MATCH (defined)-[:DEFINES_METHOD*0..]->(caller)-[r:CALLS]->()
DELETE r
"""

MODULE_CALLER_PATHS_QUERY = """
MATCH (changed:Module {path: $path, _repo_path: $repo_path})
MATCH (changed)-[:DEFINES|DEFINES_METHOD*..5]->(callee)
MATCH (caller)-[:CALLS]->(callee)
MATCH (source:Module)-[:DEFINES|DEFINES_METHOD*..5]->(caller)
WHERE source._repo_path = $repo_path
RETURN DISTINCT source.path AS path
"""


class CodeChangeEventHandler(FileSystemEventHandler):
    """Handles file system events and updates the graph accordingly."""

    def __init__(self, updater: GraphUpdater, debounce_seconds: int = 20):
        self.updater = updater
        # Using centralized ignore patterns from config
        self.ignore_patterns = IGNORE_PATTERNS
        self.ignore_suffixes = IGNORE_SUFFIXES
        self.pending_changes = set()
        self.pending_changes_lock = threading.Lock()
        self.timer = None
        self.debounce_seconds = debounce_seconds
        logger.info(f"File watcher is now active (debounce: {debounce_seconds}s).")

    def _is_relevant(self, path_str: str) -> bool:
        """Check if the file path is relevant for processing."""
        path = Path(path_str)

        # Ignore files and folders starting with a dot (hidden files/folders)
        # We check all parts of the path relative to the repo root
        try:
            relative_path = path.relative_to(self.updater.repo_path)
            if any(part.startswith(".") for part in relative_path.parts):
                return False
        except ValueError:
            # If path is not relative to repo_path, it's definitely not relevant
            return False

        # Ignore common binary and media extensions
        ignored_extensions = {
            ".png",
            ".jpg",
            ".jpeg",
            ".gif",
            ".svg",
            ".ico",
            ".webp",
            ".pdf",
            ".zip",
            ".tar",
            ".gz",
            ".7z",
            ".rar",
            ".exe",
            ".dll",
            ".so",
            ".dylib",
            ".pyc",
            ".pyo",
            ".pyd",
            ".db",
            ".sqlite",
            ".sqlite3",
            ".db-journal",
            ".db-shm",
            ".db-wal",
            ".sqlite-journal",
            ".sqlite-shm",
            ".sqlite-wal",
            ".woff",
            ".woff2",
            ".ttf",
            ".eot",
            ".mp3",
            ".mp4",
            ".wav",
            ".avi",
            ".mov",
        }
        if path.suffix.lower() in ignored_extensions:
            return False

        if any(path.name.endswith(suffix) for suffix in self.ignore_suffixes):
            return False
        return not any(part in self.ignore_patterns for part in path.parts)

    def _schedule_processing(self):
        """Schedule processing of pending changes after debounce period."""
        if self.timer:
            self.timer.cancel()
        self.timer = threading.Timer(
            self.debounce_seconds, self._process_pending_changes
        )
        self.timer.daemon = True
        self.timer.start()

    def _process_pending_changes(self):
        """Process all pending changes after debounce period."""
        with self.pending_changes_lock:
            if not self.pending_changes:
                return
            pending_snapshot = list(self.pending_changes)

        start_time = time.time()
        num_files = len(pending_snapshot)
        logger.info(f"🔄 Starting graph update for {num_files} file(s)...")

        try:
            # Process each changed file: delete old data and re-parse
            changed_source_paths = set()
            affected_caller_paths = set()
            for path_str in pending_snapshot:
                path = Path(path_str)
                # Check if file still exists (might have been deleted)
                if not path.exists():
                    logger.debug(f"File {path} no longer exists, skipping re-parse.")
                    # We still need to delete it from the graph if it was deleted
                    relative_path_str = str(path.relative_to(self.updater.repo_path))
                    self.updater.ingestor.execute_write(
                        MODULE_SUBGRAPH_DELETE_QUERY,
                        {
                            "path": relative_path_str,
                            "repo_path": self.updater.ingestor.repo_path,
                        },
                    )
                    self.updater.remove_file_from_state(path)
                    continue

                relative_path_str = str(path.relative_to(self.updater.repo_path))

                logger.debug(f"Updating graph for: {relative_path_str}")

                caller_modules = self.updater.ingestor.fetch_all(
                    MODULE_CALLER_PATHS_QUERY,
                    {
                        "path": relative_path_str,
                        "repo_path": self.updater.ingestor.repo_path,
                    },
                )
                affected_caller_paths.update(
                    self.updater.repo_path / caller["path"]
                    for caller in caller_modules
                    if caller.get("path")
                )

                # Delete old data for this file
                self.updater.ingestor.execute_write(
                    MODULE_SUBGRAPH_DELETE_QUERY,
                    {
                        "path": relative_path_str,
                        "repo_path": self.updater.ingestor.repo_path,
                    },
                )
                logger.debug(f"Ran deletion query for path: {relative_path_str}")

                # Clear in-memory state
                self.updater.remove_file_from_state(path)

                # Re-parse the file
                lang_config = get_language_config(path.suffix)
                if lang_config and lang_config.name in self.updater.parsers:
                    result = self.updater.factory.definition_processor.process_file(
                        path,
                        lang_config.name,
                        self.updater.queries,
                        self.updater.factory.structure_processor.structural_elements,
                    )
                    if result:
                        root_node, language = result
                        self.updater.ast_cache[path] = (root_node, language)
                        changed_source_paths.add(path)

            # Rebuild only call edges that originate in changed modules. Their
            # symbols were removed and re-created above, so no other file needs
            # parsing or call-resolution work for a content-only edit.
            for path in changed_source_paths:
                self.updater.ingestor.execute_write(
                    MODULE_CALLS_DELETE_QUERY,
                    {
                        "path": str(path.relative_to(self.updater.repo_path)),
                        "repo_path": self.updater.ingestor.repo_path,
                    },
                )
            self.updater.process_function_calls_for_files(
                sorted(changed_source_paths | affected_caller_paths)
            )

            # Flush all changes
            self.updater.ingestor.flush_all()

            # Update semantic embeddings for changed files
            logger.info("  Updating semantic embeddings...")
            changed_paths = [Path(p) for p in pending_snapshot]
            self.updater.update_embeddings_for_files(changed_paths)

            elapsed = time.time() - start_time
            logger.success(
                f"✓ Graph update completed in {elapsed:.2f}s for {num_files} file(s)."
            )

            # Refresh ingest metadata so ingest_status no longer reports these
            # files as pending changes.
            write_ingest_metadata(self.updater.repo_path)

            with self.pending_changes_lock:
                self.pending_changes.difference_update(pending_snapshot)
        except Exception:
            logger.exception(
                "Graph update failed. Keeping pending changes queued and retrying after debounce interval."
            )
            self._schedule_processing()

    def dispatch(self, event: Any) -> None:
        """A single dispatch method to handle all file system events."""
        if event.is_directory:
            return

        # Only care about events that actually change the file content or existence
        relevant_events = {"created", "modified", "deleted", "moved"}
        if event.event_type not in relevant_events:
            return

        # Move events include source and destination paths. Queue both to keep
        # graph/vector state correlated when files are renamed or relocated.
        if event.event_type == "moved":
            dest_path = getattr(event, "dest_path", None)
            src_relevant = self._is_relevant(event.src_path)
            dest_relevant = bool(dest_path) and self._is_relevant(dest_path)
            if not src_relevant and not dest_relevant:
                return

            logger.warning(
                "Change detected: moved from {} to {}. Queuing for processing.",
                event.src_path,
                dest_path,
            )

            with self.pending_changes_lock:
                if src_relevant:
                    self.pending_changes.add(event.src_path)
                if dest_relevant:
                    self.pending_changes.add(dest_path)
            self._schedule_processing()
            return

        if not self._is_relevant(event.src_path):
            return

        logger.warning(
            f"Change detected: {event.event_type} on {event.src_path}. Queuing for processing."
        )

        # Add to pending changes and schedule processing
        with self.pending_changes_lock:
            self.pending_changes.add(event.src_path)
        self._schedule_processing()


def start_watcher(
    repo_path: str,
    host: str,
    port: int,
    batch_size: int | None = None,
    debounce: int = 20,
    skip_initial: bool = False,
) -> None:
    """Initializes the graph updater and starts the file system watcher."""
    repo_path_obj = Path(repo_path).resolve()
    parsers, queries = load_parsers()

    effective_batch_size = settings.resolve_batch_size(batch_size)
    logger.info(
        "Startup wiring resolved: repo_path={}, memgraph={}:{}, batch_size={}, debounce={}s, skip_initial={}",
        repo_path_obj,
        host,
        port,
        effective_batch_size,
        debounce,
        skip_initial,
    )

    with MemgraphIngestor(
        host=host,
        port=port,
        batch_size=effective_batch_size,
        repo_path=repo_path_obj,
    ) as ingestor:
        updater = GraphUpdater(ingestor, repo_path_obj, parsers, queries)

        if skip_initial:
            logger.info(
                "Skipping initial full scan (--no-update). Only watching for changes."
            )
        else:
            logger.info("Performing initial full codebase scan...")
            updater.run()
            # Refresh ingest metadata so ingest_status reports a clean index after
            # the full scan (covers CLI startup and UI-triggered full updates).
            write_ingest_metadata(repo_path_obj)
            logger.success("Initial scan complete. Starting real-time watcher.")

        event_handler = CodeChangeEventHandler(updater, debounce_seconds=debounce)
        observer = Observer()
        observer.schedule(event_handler, str(repo_path_obj), recursive=True)
        observer.start()
        logger.info(f"Watching for changes in: {repo_path_obj}")

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            observer.stop()
        observer.join()


if __name__ == "__main__":
    logger.remove()
    logger.add(
        sys.stdout,
        format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>\n{exception}",
        level="INFO",
    )
    logger.info("Logger configured for Real-Time Updater.")

    parser = argparse.ArgumentParser(
        description="Real-time graph updater for codebases."
    )
    parser.add_argument("repo_path", help="Path to the repository to watch.")
    parser.add_argument("--host", default="localhost", help="Memgraph host")
    parser.add_argument("--port", type=int, default=7687, help="Memgraph port")
    parser.add_argument(
        "--debounce",
        type=int,
        default=20,
        help="Debounce delay in seconds before processing changes (default: 20)",
    )

    def positive_int(value: str) -> int:
        """Argparse type that enforces positive integers."""
        try:
            ivalue = int(value)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(
                f"{value!r} is not a valid integer"
            ) from exc
        if ivalue < 1:
            raise argparse.ArgumentTypeError(
                f"{value!r} is not a valid positive integer"
            )
        return ivalue

    parser.add_argument(
        "--batch-size",
        type=positive_int,
        default=None,
        help="Number of buffered nodes/relationships before flushing to Memgraph",
    )
    parser.add_argument(
        "--no-update",
        action="store_true",
        default=False,
        help="Skip the initial full scan; only watch for incremental changes",
    )
    args = parser.parse_args()

    start_watcher(
        args.repo_path,
        args.host,
        args.port,
        args.batch_size,
        debounce=args.debounce,
        skip_initial=args.no_update,
    )
