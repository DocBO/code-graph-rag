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
from codebase_rag.language_config import get_language_config
from codebase_rag.parser_loader import load_parsers
from codebase_rag.services.graph_service import MemgraphIngestor


class CodeChangeEventHandler(FileSystemEventHandler):
    """Handles file system events and updates the graph accordingly."""

    def __init__(self, updater: GraphUpdater, debounce_seconds: int = 20):
        self.updater = updater
        # Using centralized ignore patterns from config
        self.ignore_patterns = IGNORE_PATTERNS
        self.ignore_suffixes = IGNORE_SUFFIXES
        self.pending_changes = set()
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
            ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp",
            ".pdf", ".zip", ".tar", ".gz", ".7z", ".rar",
            ".exe", ".dll", ".so", ".dylib",
            ".pyc", ".pyo", ".pyd",
            ".db", ".sqlite", ".sqlite3",
            ".db-journal", ".db-shm", ".db-wal",
            ".sqlite-journal", ".sqlite-shm", ".sqlite-wal",
            ".woff", ".woff2", ".ttf", ".eot",
            ".mp3", ".mp4", ".wav", ".avi", ".mov",
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
        self.timer = threading.Timer(self.debounce_seconds, self._process_pending_changes)
        self.timer.start()

    def _process_pending_changes(self):
        """Process all pending changes after debounce period."""
        if not self.pending_changes:
            return

        start_time = time.time()
        num_files = len(self.pending_changes)
        logger.info(f"🔄 Starting graph update for {num_files} file(s)...")

        # Process each changed file: delete old data and re-parse
        for path_str in self.pending_changes:
            path = Path(path_str)
            # Check if file still exists (might have been deleted)
            if not path.exists():
                logger.debug(f"File {path} no longer exists, skipping re-parse.")
                # We still need to delete it from the graph if it was deleted
                relative_path_str = str(path.relative_to(self.updater.repo_path))
                delete_query = "MATCH (m:Module {path: $path, _repo_path: $repo_path})-[*0..]->(c) DETACH DELETE m, c"
                self.updater.ingestor.execute_write(
                    delete_query,
                    {"path": relative_path_str, "repo_path": self.updater.ingestor.repo_path},
                )
                self.updater.remove_file_from_state(path)
                continue

            relative_path_str = str(path.relative_to(self.updater.repo_path))

            logger.debug(f"Updating graph for: {relative_path_str}")

            # Delete old data for this file
            delete_query = "MATCH (m:Module {path: $path, _repo_path: $repo_path})-[*0..]->(c) DETACH DELETE m, c"
            self.updater.ingestor.execute_write(
                delete_query,
                {"path": relative_path_str, "repo_path": self.updater.ingestor.repo_path},
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

        # Recalculate all function call relationships once for all changes
        logger.info("Recalculating all function call relationships for consistency...")
        
        # Pass 1: Re-identify structure to ensure all folders/packages exist
        logger.info("  - Pass 1: Re-identifying structure...")
        self.updater.factory.structure_processor.identify_structure()
        
        # Pass 2: Re-process all files to ensure all definitions exist
        logger.info("  - Pass 2: Re-processing all files for definitions...")
        self.updater._process_files()
        
        # Pass 3: Re-process all function calls
        logger.info("  - Pass 3: Re-processing function calls...")
        self.updater.ingestor.execute_write(
            "MATCH (n)-[r:CALLS]->() WHERE n._repo_path = $repo_path DELETE r",
            {"repo_path": self.updater.ingestor.repo_path},
        )
        self.updater._process_function_calls()

        # Flush all changes
        self.updater.ingestor.flush_all()
        
        # Update semantic embeddings for changed files
        logger.info("  Updating semantic embeddings...")
        changed_paths = [Path(p) for p in self.pending_changes]
        self.updater.update_embeddings_for_files(changed_paths)
        
        elapsed = time.time() - start_time
        logger.success(f"✓ Graph update completed in {elapsed:.2f}s for {num_files} file(s).")

        # Clear pending changes
        self.pending_changes.clear()

    def dispatch(self, event: Any) -> None:
        """A single dispatch method to handle all file system events."""
        if event.is_directory or not self._is_relevant(event.src_path):
            return

        # Only care about events that actually change the file content or existence
        relevant_events = {"created", "modified", "deleted", "moved"}
        if event.event_type not in relevant_events:
            return

        logger.warning(
            f"Change detected: {event.event_type} on {event.src_path}. Queuing for processing."
        )

        # Add to pending changes and schedule processing
        self.pending_changes.add(event.src_path)
        self._schedule_processing()


def start_watcher(
    repo_path: str,
    host: str,
    port: int,
    batch_size: int | None = None,
    debounce: int = 20,
) -> None:
    """Initializes the graph updater and starts the file system watcher."""
    repo_path_obj = Path(repo_path).resolve()
    parsers, queries = load_parsers()

    effective_batch_size = settings.resolve_batch_size(batch_size)

    with MemgraphIngestor(
        host=host,
        port=port,
        batch_size=effective_batch_size,
        repo_path=repo_path_obj,
    ) as ingestor:
        updater = GraphUpdater(ingestor, repo_path_obj, parsers, queries)

        # --- Perform an initial full scan to build the complete context ---
        # This is essential for the real-time updates to have a valid baseline.
        logger.info("Performing initial full codebase scan...")
        updater.run()
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
        format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
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
    args = parser.parse_args()

    start_watcher(
        args.repo_path, args.host, args.port, args.batch_size, debounce=args.debounce
    )
