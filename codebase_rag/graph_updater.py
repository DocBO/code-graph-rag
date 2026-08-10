import sys
from collections import OrderedDict, defaultdict
from collections.abc import ItemsView, KeysView
from pathlib import Path
from typing import Any, cast

from loguru import logger
from tree_sitter import Node, Parser

from .config import IGNORE_PATTERNS, IGNORE_SUFFIXES, settings
from .language_config import LANGUAGE_FQN_CONFIGS, get_language_config
from .parsers.factory import ProcessorFactory
from .services.graph_service import MemgraphIngestor
from .utils.chunking import chunk_boundaries
from .utils.dependencies import has_semantic_dependencies
from .utils.fqn_resolver import find_function_source_by_fqn
from .utils.source_extraction import extract_source_with_fallback

SEMANTIC_ASSET_EXTENSIONS = {
    ".css",
    ".html",
    ".htm",
    ".less",
    ".sass",
    ".scss",
    ".svelte",
    ".vue",
}


class FunctionRegistryTrie:
    """Trie data structure optimized for function qualified name lookups."""

    def __init__(self) -> None:
        self.root: dict[str, Any] = {}
        self._entries: dict[str, str] = {}

    def insert(self, qualified_name: str, func_type: str) -> None:
        """Insert a function into the trie."""
        self._entries[qualified_name] = func_type

        # Build trie path from qualified name parts
        parts = qualified_name.split(".")
        current = self.root

        for part in parts:
            if part not in current:
                current[part] = {}
            current = current[part]

        # Mark end of qualified name
        current["__type__"] = func_type
        current["__qn__"] = qualified_name

    def get(self, qualified_name: str, default: str | None = None) -> str | None:
        """Get function type by exact qualified name."""
        return self._entries.get(qualified_name, default)

    def __contains__(self, qualified_name: str) -> bool:
        """Check if qualified name exists in registry."""
        return qualified_name in self._entries

    def __getitem__(self, qualified_name: str) -> str:
        """Get function type by qualified name."""
        return self._entries[qualified_name]

    def __setitem__(self, qualified_name: str, func_type: str) -> None:
        """Set function type for qualified name."""
        self.insert(qualified_name, func_type)

    def __delitem__(self, qualified_name: str) -> None:
        """Remove qualified name from registry and clean up trie structure.

        Performs proper cleanup of the trie to prevent memory leaks during
        long-running sessions with file deletions/updates.
        """
        if qualified_name not in self._entries:
            return

        del self._entries[qualified_name]

        # Clean up trie structure by removing empty nodes
        parts = qualified_name.split(".")
        self._cleanup_trie_path(parts, self.root)

    def _cleanup_trie_path(self, parts: list[str], node: dict[str, Any]) -> bool:
        """Recursively clean up empty trie nodes.

        Args:
            parts: Remaining parts of the qualified name path
            node: Current trie node

        Returns:
            True if current node is empty and can be deleted
        """
        if not parts:
            # Remove the qualifier markers if they exist
            node.pop("__qn__", None)
            node.pop("__type__", None)
            # Node is empty if it has no children
            return len(node) == 0

        part = parts[0]
        if part not in node:
            return False  # Path doesn't exist

        # Recursively check if child can be cleaned up
        child_empty = self._cleanup_trie_path(parts[1:], node[part])

        # If child is empty and has no other qualified names, remove it
        if child_empty:
            del node[part]

        # A node can be cleaned up if it's not an endpoint and has no children.
        is_endpoint = "__qn__" in node
        has_children = any(not key.startswith("__") for key in node)
        return not has_children and not is_endpoint

    def keys(self) -> KeysView[str]:
        """Return all qualified names."""
        return self._entries.keys()

    def items(self) -> ItemsView[str, str]:
        """Return all (qualified_name, type) pairs."""
        return self._entries.items()

    def __len__(self) -> int:
        """Return number of entries."""
        return len(self._entries)

    def find_with_prefix_and_suffix(self, prefix: str, suffix: str) -> list[str]:
        """Find all qualified names that start with prefix and end with suffix."""
        results = []
        prefix_parts = prefix.split(".") if prefix else []

        # Navigate to prefix in trie
        current = self.root
        for part in prefix_parts:
            if part not in current:
                return []  # Prefix doesn't exist
            current = current[part]

        # DFS to find all entries under this prefix that end with suffix
        def dfs(node: dict[str, Any]) -> None:
            if "__qn__" in node:
                qn = node["__qn__"]
                if qn.endswith(f".{suffix}"):
                    results.append(qn)

            for key, child in node.items():
                if not key.startswith("__"):  # Skip metadata keys
                    dfs(child)

        dfs(current)
        return results

    def find_ending_with(self, suffix: str) -> list[str]:
        """Find all qualified names ending with the given suffix."""
        return [qn for qn in self._entries.keys() if qn.endswith(f".{suffix}")]

    def find_with_prefix(self, prefix: str) -> list[tuple[str, str]]:
        """Find all qualified names that start with the given prefix.

        Args:
            prefix: The prefix to search for (e.g., "module.Class.method")

        Returns:
            List of (qualified_name, type) tuples matching the prefix
        """
        results = []
        prefix_parts = prefix.split(".")

        # Navigate to prefix in trie
        current = self.root
        for part in prefix_parts:
            if part not in current:
                return []  # Prefix doesn't exist
            current = current[part]

        # DFS to find all entries under this prefix
        def dfs(node: dict[str, Any]) -> None:
            if "__qn__" in node:
                qn = node["__qn__"]
                func_type = node["__type__"]
                results.append((qn, func_type))

            for key, child in node.items():
                if not key.startswith("__"):  # Skip metadata keys
                    dfs(child)

        dfs(current)
        return results


class BoundedASTCache:
    """Memory-aware AST cache with automatic cleanup to prevent memory leaks.

    Uses LRU eviction strategy and monitors memory usage to maintain
    reasonable memory consumption during long-running analysis sessions.
    """

    def __init__(self, max_entries: int = 1000, max_memory_mb: int = 500):
        """Initialize the bounded AST cache.

        Args:
            max_entries: Maximum number of AST entries to cache
            max_memory_mb: Soft memory limit in MB for cache eviction
        """
        self.cache: OrderedDict[Path, tuple[Node, str]] = OrderedDict()
        self.max_entries = max_entries
        self.max_memory_bytes = max_memory_mb * 1024 * 1024

    def __setitem__(self, key: Path, value: tuple[Node, str]) -> None:
        """Add or update an AST cache entry with automatic cleanup."""
        # Remove existing entry if present to update LRU order
        if key in self.cache:
            del self.cache[key]

        # Add new entry
        self.cache[key] = value

        # Evict entries if we exceed limits
        self._enforce_limits()

    def __getitem__(self, key: Path) -> tuple[Node, str]:
        """Get AST cache entry and mark as recently used."""
        value = self.cache[key]
        # Move to end to mark as recently used
        self.cache.move_to_end(key)
        return value

    def __delitem__(self, key: Path) -> None:
        """Remove entry from cache."""
        if key in self.cache:
            del self.cache[key]

    def __contains__(self, key: Path) -> bool:
        """Check if key exists in cache."""
        return key in self.cache

    def items(self) -> Any:
        """Return all cache items."""
        return self.cache.items()

    def _enforce_limits(self) -> None:
        """Enforce cache size and memory limits by evicting old entries."""
        # Check entry count limit
        while len(self.cache) > self.max_entries:
            self.cache.popitem(last=False)  # Remove least recently used

        # Check memory limit (rough estimate)
        if self._should_evict_for_memory():
            entries_to_remove = max(1, len(self.cache) // 10)  # Remove 10% of entries
            for _ in range(entries_to_remove):
                if self.cache:
                    self.cache.popitem(last=False)

    def _should_evict_for_memory(self) -> bool:
        """Check if we should evict entries due to memory pressure."""
        try:
            # Use sys.getsizeof for a rough memory estimate
            cache_size = sum(sys.getsizeof(v) for v in self.cache.values())
            return cache_size > self.max_memory_bytes
        except Exception:
            # If memory checking fails, use conservative entry-based eviction
            return len(self.cache) > self.max_entries * 0.8


class GraphUpdater:
    """Parses code using Tree-sitter and updates the graph."""

    def __init__(
        self,
        ingestor: MemgraphIngestor,
        repo_path: Path,
        parsers: dict[str, Parser],
        queries: dict[str, Any],
    ):
        self.ingestor = ingestor
        self.repo_path = repo_path
        self.parsers = parsers
        self.queries = self._prepare_queries_with_parsers(queries, parsers)
        self.project_name = repo_path.name
        self.function_registry = FunctionRegistryTrie()
        self.simple_name_lookup: dict[str, set[str]] = defaultdict(set)
        self.ast_cache = BoundedASTCache(max_entries=1000, max_memory_mb=500)
        self.ignore_dirs = IGNORE_PATTERNS
        self.ignore_suffixes = IGNORE_SUFFIXES

        # Create processor factory with all dependencies
        self.factory = ProcessorFactory(
            ingestor=self.ingestor,
            repo_path_getter=lambda: self.repo_path,
            project_name_getter=lambda: self.project_name,
            queries=self.queries,
            function_registry=self.function_registry,
            simple_name_lookup=self.simple_name_lookup,
            ast_cache=self.ast_cache,
        )

    def _is_dependency_file(self, file_name: str, filepath: Path) -> bool:
        """Check if a file is a dependency file that should be processed for external dependencies."""
        dependency_files = {
            "pyproject.toml",
            "requirements.txt",
            "package.json",
            "cargo.toml",
            "go.mod",
            "gemfile",
            "composer.json",
        }

        # Check by filename
        if file_name.lower() in dependency_files:
            return True

        # Check by extension (for .csproj files)
        if filepath.suffix.lower() == ".csproj":
            return True

        return False

    def _prepare_queries_with_parsers(
        self, queries: dict[str, Any], parsers: dict[str, Parser]
    ) -> dict[str, Any]:
        """Add parser references to query objects for processors."""
        updated_queries = {}
        for lang, query_data in queries.items():
            if lang in parsers:
                updated_queries[lang] = {**query_data, "parser": parsers[lang]}
            else:
                updated_queries[lang] = query_data
        return updated_queries

    def run(self) -> None:
        """Orchestrates the parsing and ingestion process."""
        self.ingestor.ensure_constraints()
        self.ingestor.ensure_node_batch("Project", {"name": self.project_name})
        logger.info(f"Ensuring Project: {self.project_name}")

        logger.info("--- Pass 1: Identifying Packages and Folders ---")
        self.factory.structure_processor.identify_structure()

        logger.info(
            "\n--- Pass 2: Processing Files, Caching ASTs, and Collecting Definitions ---"
        )
        self._process_files()

        logger.info(
            f"\n--- Found {len(self.function_registry)} functions/methods in codebase ---"
        )
        logger.info("--- Pass 3: Processing Function Calls from AST Cache ---")
        self._process_function_calls()
        logger.info("✓ Pass 3 complete: Function calls processed")

        # Process method overrides after all definitions are collected
        logger.info("Processing method overrides...")

        self.factory.definition_processor.process_all_method_overrides()

        logger.info("✓ Method overrides processed")

        logger.info("\n--- Analysis complete. Flushing all data to database... ---")
        self.ingestor.flush_all()

        # Generate embeddings for functions and methods if semantic deps available
        self._generate_semantic_embeddings()

        logger.info("✓✓✓ Ingestion complete")

    def update_embeddings_for_files(self, file_paths: list[Path]) -> None:
        """Update semantic embeddings for code entities in specific files."""
        if not has_semantic_dependencies():
            return

        try:
            from .embedder import embed_code_batch
            from .vector_store import batch_store_embeddings, delete_embeddings_for_files

            # Convert paths to relative strings as stored in DB
            rel_paths = [str(p.relative_to(self.repo_path)) for p in file_paths]

            # Remove any existing vectors tied to changed/deleted files before
            # regenerating to keep Qdrant aligned with current file state.
            delete_embeddings_for_files(rel_paths, repo_path=self.repo_path)

            # Query database for symbols in these files.
            placeholders = ", ".join(f"${i}" for i in range(len(rel_paths)))
            symbol_query = f"""
            MATCH (m:Module)-[:DEFINES|CONTAINS*..5]->(n)
            WHERE (n:Function OR n:Method OR n:Class)
              AND m.path IN [{placeholders}]
              AND n._repo_path = $repo_path
            RETURN id(n) AS node_id, n.qualified_name AS qualified_name,
                   n.start_line AS start_line, n.end_line AS end_line,
                   m.path AS path, labels(n)[0] AS node_type
            """

            params: dict[str, Any] = {str(i): path for i, path in enumerate(rel_paths)}
            params["repo_path"] = str(self.repo_path)

            results = self.ingestor._execute_query(symbol_query, params)

            # Include complete parseable modules and frontend assets. Module-level
            # JSX/template text and CSS selectors often live outside named symbols.
            file_query = f"""
            MATCH (n)
            WHERE n._repo_path = $repo_path
              AND n.path IN [{placeholders}]
              AND (
                n:Module
                OR (n:File AND n.extension IN $asset_extensions)
              )
            RETURN id(n) AS node_id, n.qualified_name AS qualified_name,
                   null AS start_line, null AS end_line,
                   n.path AS path, labels(n)[0] AS node_type
            """
            file_params = dict(params)
            file_params["asset_extensions"] = sorted(SEMANTIC_ASSET_EXTENSIONS)
            results.extend(self.ingestor._execute_query(file_query, file_params))

            if not results:
                logger.debug(
                    f"No semantic content found for embedding update in {len(file_paths)} files"
                )
                return

            logger.info(
                f"Updating embeddings for {len(results)} code entities in changed files"
            )

            embeddings_to_process = self._prepare_embedding_chunks(results)

            if not embeddings_to_process:
                return

            # Process in batches
            batch_size = 100
            for batch_start in range(0, len(embeddings_to_process), batch_size):
                batch_end = min(batch_start + batch_size, len(embeddings_to_process))
                batch_chunks = embeddings_to_process[batch_start:batch_end]
                batch_codes = [c[0] for c in batch_chunks]

                try:
                    batch_embeddings = embed_code_batch(
                        batch_codes, batch_size=batch_size
                    )

                    batch_data = []
                    for idx, embedding in enumerate(batch_embeddings):
                        chunk_text, node_id, qualified_name, source_path = batch_chunks[idx]
                        batch_data.append(
                            (node_id, embedding, qualified_name, chunk_text, source_path)
                        )

                    if batch_data:
                        batch_store_embeddings(batch_data, repo_path=self.repo_path)
                except Exception as e:
                    logger.warning(
                        f"Failed to process embedding batch for changed files: {e}"
                    )

            logger.info(
                f"✓ Updated {len(embeddings_to_process)} embeddings for changed files"
            )

        except Exception as e:
            logger.warning(
                f"Failed to update semantic embeddings for changed files: {e}"
            )

    def remove_file_from_state(self, file_path: Path) -> None:
        """Removes all state associated with a file from the updater's memory."""
        logger.debug(f"Removing in-memory state for: {file_path}")

        # Clear AST cache
        if file_path in self.ast_cache:
            del self.ast_cache[file_path]
            logger.debug("  - Removed from ast_cache")

        # Determine the module qualified name prefix for the file
        relative_path = file_path.relative_to(self.repo_path)
        if file_path.name == "__init__.py":
            module_qn_prefix = ".".join(
                [self.project_name] + list(relative_path.parent.parts)
            )
        else:
            module_qn_prefix = ".".join(
                [self.project_name] + list(relative_path.with_suffix("").parts)
            )

        # We need to find all qualified names that belong to this file/module
        qns_to_remove = set()

        # Clean function_registry and collect qualified names to remove
        for qn in list(self.function_registry.keys()):
            if qn.startswith(module_qn_prefix + ".") or qn == module_qn_prefix:
                qns_to_remove.add(qn)
                del self.function_registry[qn]

        if qns_to_remove:
            logger.debug(
                f"  - Removing {len(qns_to_remove)} QNs from function_registry"
            )

        # Clean simple_name_lookup
        for simple_name, qn_set in self.simple_name_lookup.items():
            original_count = len(qn_set)
            new_qn_set = qn_set - qns_to_remove
            if len(new_qn_set) < original_count:
                self.simple_name_lookup[simple_name] = new_qn_set
                logger.debug(f"  - Cleaned simple_name '{simple_name}'")

    def _process_files(self) -> None:
        """Second pass: Efficiently processes all files, parses them, and caches their ASTs."""

        def should_skip_path(path: Path) -> bool:
            """Check if file path should be skipped based on ignore patterns."""
            # Skip based on suffix
            if any(path.name.endswith(suffix) for suffix in self.ignore_suffixes):
                return True

            relative_parts = path.relative_to(self.repo_path).parts

            return any(part in self.ignore_dirs for part in relative_parts)

        # Use pathlib.rglob for more efficient file iteration
        for filepath in self.repo_path.rglob("*"):
            if filepath.is_file() and not should_skip_path(filepath):
                # Check if this file type is supported for parsing
                lang_config = get_language_config(filepath.suffix)
                if lang_config and lang_config.name in self.parsers:
                    # Parse as Module and cache AST
                    result = self.factory.definition_processor.process_file(
                        filepath,
                        lang_config.name,
                        self.queries,
                        self.factory.structure_processor.structural_elements,
                    )
                    if result:
                        root_node, language = result
                        self.ast_cache[filepath] = (root_node, language)

                    # Also create CONTAINS_FILE relationship for parseable files
                    self.factory.structure_processor.process_generic_file(
                        filepath, filepath.name
                    )

                elif self._is_dependency_file(filepath.name, filepath):
                    self.factory.definition_processor.process_dependencies(filepath)
                    # Also create CONTAINS_FILE relationship for dependency files
                    self.factory.structure_processor.process_generic_file(
                        filepath, filepath.name
                    )
                else:
                    # Use StructureProcessor to handle generic files
                    self.factory.structure_processor.process_generic_file(
                        filepath, filepath.name
                    )

    def _process_function_calls(self) -> None:
        """Third pass: Process function calls using the cached ASTs."""
        # Create a copy of items to prevent "OrderedDict mutated during iteration" errors
        ast_cache_items = list(self.ast_cache.items())
        total_files = len(ast_cache_items)
        logger.info(f"Processing function calls for {total_files} files...")

        for i, (file_path, (root_node, language)) in enumerate(ast_cache_items):
            if i > 0 and i % 10 == 0:
                logger.debug(
                    f"  Progress: {i}/{total_files} files processed ({(i / total_files) * 100:.1f}%)"
                )

            self.factory.call_processor.process_calls_in_file(
                file_path, root_node, language, self.queries
            )

        logger.debug(
            f"  Progress: {total_files}/{total_files} files processed (100.0%)"
        )

    def process_function_calls_for_files(self, file_paths: list[Path]) -> None:
        """Process call relationships only for the supplied cached source files."""
        for file_path in file_paths:
            if file_path not in self.ast_cache:
                continue
            root_node, language = self.ast_cache[file_path]
            self.factory.call_processor.process_calls_in_file(
                file_path, root_node, language, self.queries
            )

    def _generate_semantic_embeddings(self) -> None:
        """Generate embeddings for symbols, modules, and frontend assets."""
        logger.info("--- Starting Pass 4: Generating semantic embeddings ---")

        if not has_semantic_dependencies():
            logger.info(
                "Semantic search dependencies not available, skipping embedding generation"
            )
            return

        try:
            from .embedder import embed_code_batch
            from .vector_store import batch_store_embeddings, clean_collection

            # Pass 4 regenerates embeddings for every embeddable node in the
            # repo, so purge the collection first. Otherwise points orphaned by
            # renames, deleted nodes, or chunk-config changes linger forever and
            # still surface in semantic search.
            try:
                clean_collection(self.repo_path)
            except Exception as exc:
                logger.warning(
                    "  [Pass 4] Could not clean existing embeddings: {}",
                    exc,
                )

            # Symbols alone miss common frontend behavior stored in top-level JSX,
            # templates, and styles. Include parseable modules and frontend assets.
            query = """
            MATCH (n)
            WHERE n._repo_path = $repo_path
              AND (
                n:Function OR n:Method OR n:Class OR n:Module
                OR (n:File AND n.extension IN $asset_extensions)
              )
            OPTIONAL MATCH (m:Module)-[:DEFINES|CONTAINS*..5]->(n)
            RETURN DISTINCT id(n) AS node_id, n.qualified_name AS qualified_name,
                   n.start_line AS start_line, n.end_line AS end_line,
                   coalesce(m.path, n.path) AS path,
                   labels(n)[0] AS node_type
            """

            params = {
                "repo_path": str(self.repo_path),
                "asset_extensions": sorted(SEMANTIC_ASSET_EXTENSIONS),
            }
            logger.info("  [Pass 4] Fetching semantic content from Memgraph...")

            results = self.ingestor._execute_query(query, params)

            if not results:
                logger.info(
                    "✓ [Pass 4] No embeddable items found for embedding generation"
                )
                return

            total_count = len(results)
            logger.info(f"✓ [Pass 4] Found {total_count} items to process")

            # Process in chunks to manage memory and provide progress updates
            chunk_size = 200  # Smaller chunks for better UI feedback
            processed_count = 0

            for i in range(0, total_count, chunk_size):
                chunk = results[i : i + chunk_size]
                prepared_chunks = self._prepare_embedding_chunks(chunk)
                chunk_codes = [item[0] for item in prepared_chunks]
                chunk_node_info = [
                    (item[1], item[2], item[3]) for item in prepared_chunks
                ]

                if chunk_codes:
                    try:
                        batch_embeddings = embed_code_batch(chunk_codes, batch_size=50)

                        # Prepare data for batch storage
                        embeddings_data = []
                        for idx, embedding in enumerate(batch_embeddings):
                            chunk_text = chunk_codes[idx]
                            node_id, qualified_name, source_path = chunk_node_info[idx]
                            embeddings_data.append(
                                (node_id, embedding, qualified_name, chunk_text, source_path)
                            )

                        if embeddings_data:
                            batch_store_embeddings(
                                embeddings_data,
                                repo_path=self.repo_path,
                            )

                        processed_count += len(chunk_codes)
                        percent = (processed_count / total_count) * 100
                        logger.info(
                            f"  [Pass 4] Progress: {processed_count}/{total_count} ({percent:.1f}%)"
                        )
                    except Exception as e:
                        logger.warning(f"  [Pass 4] Failed chunk at {i}: {e}")

            logger.info(
                f"✓ [Pass 4] Completed semantic embedding generation ({processed_count} items)"
            )

        except Exception as e:
            logger.error(f"Error during semantic embedding generation: {e}")
            logger.error("Skipping rest of Pass 4.")

    @staticmethod
    def _chunk_code(
        code: str,
        node_id: int,
        qualified_name: str,
        source_path: str | None,
    ) -> list[tuple[str, int, str, str | None]]:
        if not code:
            return []
        max_size = settings.EMBED_MAX_CHUNK_SIZE
        if len(code) <= max_size:
            return [(code, node_id, qualified_name, source_path)]
        chunks: list[tuple[str, int, str, str | None]] = []
        for start, end in chunk_boundaries(len(code), max_size):
            chunk_code = code[start:end]
            chunk_qn = f"{qualified_name}_chunk_{len(chunks)}"
            chunks.append((chunk_code, node_id, chunk_qn, source_path))
        return chunks

    def _prepare_embedding_chunks(
        self, results: list[dict[str, Any]]
    ) -> list[tuple[str, int, str, str | None]]:
        """Build searchable chunks with file and entity context."""
        prepared: list[tuple[str, int, str, str | None]] = []
        for result in results:
            node_id = result["node_id"]
            path = result.get("path")
            node_type = result.get("node_type") or "Code"
            qualified_name = result.get("qualified_name") or (
                f"file:{path}" if path else f"node:{node_id}"
            )

            if node_type in {"Module", "File"}:
                source_code = self._read_semantic_file(path)
            else:
                source_code = self._extract_source_code(
                    qualified_name,
                    path,
                    result.get("start_line"),
                    result.get("end_line"),
                )

            if not source_code:
                continue

            document = (
                f"Entity: {qualified_name}\n"
                f"Type: {node_type}\n"
                f"File: {path or 'unknown'}\n\n"
                f"{source_code}"
            )
            prepared.extend(
                self._chunk_code(document, node_id, qualified_name, path)
            )
        return prepared

    def _read_semantic_file(self, file_path: str | None) -> str | None:
        if not file_path:
            return None
        resolved_path = Path(file_path)
        if not resolved_path.is_absolute():
            resolved_path = self.repo_path / resolved_path
        try:
            return resolved_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            logger.debug("Skipping semantic file {}: {}", resolved_path, exc)
            return None

    def _extract_source_code(
        self,
        qualified_name: str,
        file_path: str | None,
        start_line: int | None,
        end_line: int | None,
    ) -> str | None:
        """Extract source code for a function, method or class from cached AST or file."""
        if not file_path or not start_line or not end_line:
            return None

        file_path_obj = Path(file_path)

        # Create AST extractor function if AST is available
        ast_extractor = None
        if file_path_obj in self.ast_cache:
            root_node, language = self.ast_cache[file_path_obj]
            fqn_config = LANGUAGE_FQN_CONFIGS.get(language)

            if fqn_config:

                def ast_extractor_func(qname: str, path: Path) -> str | None:
                    return cast(
                        str | None,
                        find_function_source_by_fqn(
                            root_node,
                            qname,
                            path,
                            self.repo_path,
                            self.project_name,
                            fqn_config,
                        ),
                    )

                ast_extractor = ast_extractor_func

        # Use shared utility with AST-based extraction and line-based fallback
        # Pass repo_path to resolve relative paths to absolute
        return cast(
            str | None,
            extract_source_with_fallback(
                file_path_obj,
                start_line,
                end_line,
                qualified_name,
                ast_extractor,
                repo_path=self.repo_path,
            ),
        )
