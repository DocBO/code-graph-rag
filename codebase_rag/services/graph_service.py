from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import mgclient
from loguru import logger


def execute_read_query(
    host: str, port: int, query: str, params: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Execute a read-only query without creating a full MemgraphIngestor.

    This is useful for tools that just need to read data and don't need
    the full ingestion machinery. Avoids connection pool issues.

    Args:
        host: Memgraph host
        port: Memgraph port
        query: Cypher query
        params: Query parameters

    Returns:
        List of result dictionaries

    Raises:
        Exception: If query execution fails
    """
    conn = None
    cursor = None
    try:
        conn = mgclient.connect(host=host, port=port)
        cursor = conn.cursor()
        cursor.execute(query, params or {})

        if not cursor.description:
            return []

        column_names = [desc.name for desc in cursor.description]
        # Use fetchone() in a loop to avoid loading entire result set into memory
        results = []
        while True:
            row = cursor.fetchone()
            if row is None:
                break
            results.append(dict(zip(column_names, row)))
        return results
    except Exception as e:
        error_str = str(e).lower()
        if "unexpected" in error_str and ("eof" in error_str or ";" in error_str):
            logger.error(
                f"!!! Cypher Syntax Error (likely invalid semicolon or syntax): {e}"
            )
            logger.error(f"    Query: {query}")
            logger.error(
                f"    Hint: Cypher does not use semicolons. Ensure query is valid."
            )
        else:
            logger.error(f"Query execution failed: {e}")
            logger.error(f"    Query: {query}")
        raise
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


class MemgraphIngestor:
    """Handles all communication and query execution with the Memgraph database."""

    def __init__(
        self,
        host: str,
        port: int,
        batch_size: int = 1000,
        repo_path: str | Path | None = None,
    ):
        self._host = host
        self._port = port
        if batch_size < 1:
            raise ValueError("batch_size must be a positive integer")
        self.batch_size = batch_size
        self.conn: mgclient.Connection | None = None
        self.node_buffer: list[tuple[str, dict[str, Any]]] = []
        self.relationship_buffer: list[tuple[tuple, str, tuple, dict | None]] = []
        # Store repo_path as a normalized absolute path string
        self._is_default_repo = not repo_path or str(repo_path) == "."
        self.repo_path = str(Path(repo_path or ".").expanduser().resolve())
        self.unique_constraints = {
            "Project": "name",
            "Package": "qualified_name",
            "Folder": "path",
            "Module": "qualified_name",
            "Class": "qualified_name",
            "Function": "qualified_name",
            "Method": "qualified_name",
            "File": "path",
            "ExternalPackage": "name",
        }

    def __enter__(self) -> "MemgraphIngestor":
        logger.info(f"Connecting to Memgraph at {self._host}:{self._port}...")
        conn = mgclient.connect(host=self._host, port=self._port)
        conn.autocommit = True
        self.conn = conn
        logger.info("Successfully connected to Memgraph.")
        return self

    def __exit__(
        self, exc_type: type | None, exc_val: Exception | None, exc_tb: Any
    ) -> None:
        if exc_type:
            logger.error(
                f"An exception occurred: {exc_val}. Flushing remaining items...",
                exc_info=True,
            )
        
        self.flush_all()
        
        if self.conn:
            import threading
            # Close the connection with a timeout to prevent hanging
            # on large repositories where Memgraph might be slow to finalize
            def close_connection():
                try:
                    self.conn.close()
                except Exception as e:
                    logger.warning(f"Error closing connection: {e}")
            
            close_thread = threading.Thread(target=close_connection, daemon=True)
            close_thread.start()
            close_thread.join(timeout=5.0)  # Wait max 5 seconds
            
            if close_thread.is_alive():
                logger.warning("Connection close timed out after 5 seconds - abandoning connection")
            else:
                logger.debug("Disconnected from Memgraph.")

    def _get_repo_filter(self, node_var: str = "n") -> str:
        """Get a Cypher WHERE clause filter for the current repo.

        Args:
            node_var: The variable name in the Cypher query (default 'n')

        Returns:
            A WHERE clause fragment, or empty string if repo_path is "."
            Example: "(n._repo_path = 'path') AND "
        """
        if self._is_default_repo:
            return ""
        return f"({node_var}._repo_path = '{self.repo_path}') AND "

    def _execute_query(self, query: str, params: dict[str, Any] | None = None) -> list:
        if not self.conn:
            raise ConnectionError("Not connected to Memgraph.")
        params = params or {}
        cursor = None
        try:
            cursor = self.conn.cursor()
            logger.debug(f"Executing query: {query[:100]}... with params: {params}")
            cursor.execute(query, params)
            if not cursor.description:
                return []
            column_names = [desc.name for desc in cursor.description]
            # Use fetchone() in a loop to avoid loading entire result set into memory
            logger.debug("Fetching results from cursor...")
            results = []
            row_count = 0
            while True:
                row = cursor.fetchone()
                if row is None:
                    break
                results.append(dict(zip(column_names, row)))
                row_count += 1
                if row_count % 1000 == 0:
                    logger.debug(f"  Fetched {row_count} rows so far...")
            logger.debug(f"Query completed. Total results: {len(results)}")
            return results
        except Exception as e:
            error_str = str(e).lower()
            # Check for common Cypher syntax errors
            if "unexpected" in error_str and ("eof" in error_str or ";" in error_str):
                logger.error(
                    f"!!! Cypher Syntax Error (likely invalid semicolon or syntax): {e}"
                )
                logger.error(f"    Query: {query}")
                logger.error(
                    f"    Hint: Cypher does not use semicolons. Ensure query is valid."
                )
            elif "already exists" not in error_str and "constraint" not in error_str:
                logger.error(f"!!! Cypher Error: {e}")
                logger.error(f"    Query: {query}")
                logger.error(f"    Params: {params}")
            raise
        finally:
            if cursor:
                cursor.close()

    def _execute_batch(
        self,
        query: str,
        params_list: list[dict[str, Any]],
        extra_params: dict[str, Any] | None = None,
    ) -> None:
        if not self.conn or not params_list:
            return
        cursor = None
        try:
            cursor = self.conn.cursor()
            batch_query = f"UNWIND $batch AS row\n{query}"

            full_params = {"batch": params_list}
            if extra_params:
                full_params.update(extra_params)

            cursor.execute(batch_query, full_params)
        except Exception as e:
            if "already exists" not in str(e).lower():
                logger.error(f"!!! Batch Cypher Error: {e}")
                logger.error(f"    Query: {query}")
                if len(params_list) > 10:
                    logger.error(
                        "    Params (first 10 of {}): {}...",
                        len(params_list),
                        params_list[:10],
                    )
                else:
                    logger.error(f"    Params: {params_list}")
            raise
        finally:
            if cursor:
                cursor.close()

    def _execute_batch_with_return(
        self,
        query: str,
        params_list: list[dict[str, Any]],
        extra_params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Execute a batch query that returns results."""
        if not self.conn or not params_list:
            return []
        cursor = None
        try:
            cursor = self.conn.cursor()
            batch_query = f"UNWIND $batch AS row\n{query}"

            full_params = {"batch": params_list}
            if extra_params:
                full_params.update(extra_params)

            logger.debug(f"Executing batch query with {len(params_list)} items...")
            cursor.execute(batch_query, full_params)
            if not cursor.description:
                return []
            column_names = [desc.name for desc in cursor.description]
            # Use fetchone() in a loop to avoid loading entire result set into memory
            results = []
            while True:
                row = cursor.fetchone()
                if row is None:
                    break
                results.append(dict(zip(column_names, row)))
            logger.debug(f"Batch query returned {len(results)} results")
            return results
        except Exception as e:
            logger.error(f"!!! Batch Cypher Error: {e}")
            logger.error(f"    Query: {query}")
            raise
        finally:
            if cursor:
                cursor.close()

    def clean_database(self) -> None:
        logger.info(f"--- Cleaning database for repo: {self.repo_path} ---")
        self._execute_query(
            "MATCH (n) WHERE n._repo_path = $repo_path DETACH DELETE n;",
            {"repo_path": self.repo_path},
        )
        logger.info("--- Database cleaned. ---")

    def ensure_constraints(self) -> None:
        logger.info("Ensuring constraints...")
        for label, prop in self.unique_constraints.items():
            # First, try to drop the old single-property constraint if it exists
            try:
                self._execute_query(
                    f"DROP CONSTRAINT ON (n:{label}) ASSERT n.{prop} IS UNIQUE;"
                )
                logger.info(
                    f"Dropped old single-property constraint for {label}({prop})"
                )
            except Exception:
                pass

            # Then, create the new composite constraint (property + _repo_path)
            try:
                self._execute_query(
                    f"CREATE CONSTRAINT ON (n:{label}) ASSERT n.{prop}, n._repo_path IS UNIQUE;"
                )
            except Exception as e:
                # If it already exists, that's fine
                if "already exists" not in str(e).lower():
                    logger.debug(
                        f"Note: Constraint for {label} may already exist or error: {e}"
                    )
        logger.info("Constraints checked/created.")

    def ensure_node_batch(self, label: str, properties: dict[str, Any]) -> None:
        """Adds a node to the buffer. Automatically adds repo_path to properties."""
        # Always add repo_path to ensure repo isolation
        properties_with_repo = {**properties, "_repo_path": self.repo_path}
        self.node_buffer.append((label, properties_with_repo))
        if len(self.node_buffer) >= self.batch_size:
            logger.debug(
                "Node buffer reached batch size ({}). Performing incremental flush.",
                self.batch_size,
            )
            self.flush_nodes()

    def ensure_relationship_batch(
        self,
        from_spec: tuple[str, str, Any],
        rel_type: str,
        to_spec: tuple[str, str, Any],
        properties: dict[str, Any] | None = None,
    ) -> None:
        """Adds a relationship to the buffer."""
        from_label, from_key, from_val = from_spec
        to_label, to_key, to_val = to_spec
        self.relationship_buffer.append(
            (
                (from_label, from_key, from_val),
                rel_type,
                (to_label, to_key, to_val),
                properties,
            )
        )
        if len(self.relationship_buffer) >= self.batch_size:
            logger.debug(
                "Relationship buffer reached batch size ({}). Performing incremental flush.",
                self.batch_size,
            )
            # Ensure all pending nodes exist before we flush relationships
            self.flush_nodes()
            self.flush_relationships()

    def flush_nodes(self) -> None:
        """Flushes the buffered nodes to the database."""
        if not self.node_buffer:
            return

        buffer_size = len(self.node_buffer)
        nodes_by_label = defaultdict(list)
        for label, props in self.node_buffer:
            nodes_by_label[label].append(props)
        flushed_total = 0
        skipped_total = 0
        for label, props_list in nodes_by_label.items():
            if not props_list:
                continue
            id_key = self.unique_constraints.get(label)
            if not id_key:
                logger.warning(
                    f"No unique constraint defined for label '{label}'. Skipping flush."
                )
                skipped_total += len(props_list)
                continue

            batch_rows: list[dict[str, Any]] = []
            for props in props_list:
                if id_key not in props:
                    logger.warning(
                        "Skipping {} node missing required '{}' property: {}",
                        label,
                        id_key,
                        props,
                    )
                    skipped_total += 1
                    continue
                row_props = {k: v for k, v in props.items() if k != id_key}
                batch_rows.append({"id": props[id_key], "props": row_props})

            if not batch_rows:
                continue

            flushed_total += len(batch_rows)

            query = f"MERGE (n:{label} {{{id_key}: row.id, _repo_path: $repo_path}})\nSET n += row.props"
            self._execute_batch(query, batch_rows, {"repo_path": self.repo_path})
        logger.info("Flushed {} of {} buffered nodes.", flushed_total, buffer_size)
        if skipped_total:
            logger.info(
                "Skipped {} buffered nodes due to missing identifiers or constraints.",
                skipped_total,
            )
        self.node_buffer.clear()

    def flush_relationships(self) -> None:
        """Flushes the buffered relationships to the database."""
        if not self.relationship_buffer:
            return

        rels_by_pattern = defaultdict(list)
        for from_node, rel_type, to_node, props in self.relationship_buffer:
            pattern = (from_node[0], from_node[1], rel_type, to_node[0], to_node[1])
            rels_by_pattern[pattern].append(
                {"from_val": from_node[2], "to_val": to_node[2], "props": props or {}}
            )

        total_attempted = 0
        total_successful = 0

        for pattern, params_list in rels_by_pattern.items():
            from_label, from_key, rel_type, to_label, to_key = pattern
            
            query = (
                f"MATCH (a:{from_label} {{{from_key}: row.from_val, _repo_path: $repo_path}}), "
                f"(b:{to_label} {{{to_key}: row.to_val, _repo_path: $repo_path}})\n"
                f"MERGE (a)-[r:{rel_type}]->(b)\n"
                f"RETURN count(r) as created"
            )
            if any(p["props"] for p in params_list):
                query = query.replace(
                    "RETURN count(r) as created",
                    "SET r += row.props\nRETURN count(r) as created",
                )

            total_attempted += len(params_list)
            
            results = self._execute_batch_with_return(
                query, params_list, {"repo_path": self.repo_path}
            )
            
            batch_successful = (
                sum(r.get("created", 0) for r in results) if results else 0
            )
            total_successful += batch_successful

            # Log failures for CALLS relationships
            if rel_type == "CALLS":
                failed = len(params_list) - batch_successful
                if failed > 0:
                    logger.debug(
                        f"Failed to create {failed} CALLS relationships - nodes may not exist"
                    )

        logger.info(
            f"Flushed {len(self.relationship_buffer)} relationships ({total_successful} successful, {total_attempted - total_successful} failed)."
        )
        self.relationship_buffer.clear()

    def flush_all(self) -> None:
        """Flushes all pending nodes and relationships to the database."""
        if not self.node_buffer and not self.relationship_buffer:
            return

        logger.info("--- Flushing all pending writes to database... ---")
        self.flush_nodes()
        self.flush_relationships()
        logger.info("--- Flushing complete. ---")

    def fetch_all(self, query: str, params: dict[str, Any] | None = None) -> list:
        """Executes a query and fetches all results.
        
        Automatically includes 'repo_path' in params for repository isolation.
        """
        params = params or {}
        if "repo_path" not in params:
            params["repo_path"] = self.repo_path
            
        logger.debug(f"Executing fetch query: {query} with params: {params}")
        return self._execute_query(query, params)

    def execute_write(self, query: str, params: dict[str, Any] | None = None) -> None:
        """Executes a write query without returning results."""
        logger.debug(f"Executing write query: {query} with params: {params}")
        self._execute_query(query, params)

    def export_graph_to_dict(self) -> dict[str, Any]:
        """Export the entire graph as a dictionary with nodes and relationships."""
        logger.info("Exporting graph data...")

        # Get all nodes with their labels and properties
        nodes_query = """
        MATCH (n)
        WHERE n._repo_path = $repo_path
        RETURN id(n) as node_id, labels(n) as labels, properties(n) as properties
        """
        nodes_data = self.fetch_all(nodes_query, {"repo_path": self.repo_path})

        # Get all relationships with their types and properties
        relationships_query = """
        MATCH (a)-[r]->(b)
        WHERE a._repo_path = $repo_path AND b._repo_path = $repo_path
        RETURN id(a) as from_id, id(b) as to_id, type(r) as type, properties(r) as properties
        """
        relationships_data = self.fetch_all(
            relationships_query, {"repo_path": self.repo_path}
        )

        graph_data = {
            "nodes": nodes_data,
            "relationships": relationships_data,
            "metadata": {
                "total_nodes": len(nodes_data),
                "total_relationships": len(relationships_data),
                "exported_at": self._get_current_timestamp(),
            },
        }

        logger.info(
            f"Exported {len(nodes_data)} nodes and {len(relationships_data)} relationships"
        )
        return graph_data

    def _get_current_timestamp(self) -> str:
        """Get current timestamp in ISO format."""
        return datetime.now(UTC).isoformat()
