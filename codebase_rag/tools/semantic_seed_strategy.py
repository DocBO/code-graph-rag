from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from itertools import islice

from loguru import logger

from ..config import settings
from ..services.graph_service import execute_read_query
from ..services.llm import create_context_synthesizer
from ..utils.source_extraction import extract_source_lines
from .semantic_search import semantic_code_search_async


@dataclass(frozen=True)
class SeedHit:
    node_id: int
    qualified_name: str
    name: str
    node_type: str
    score: float


@dataclass(frozen=True)
class ExpansionHit:
    seed_id: int
    seed_name: str
    neighbor_id: int
    neighbor_name: str
    neighbor_labels: list[str]
    relationship_types: list[str]


def _choose_expansion_depth(scores: Iterable[float]) -> int:
    scores_list = list(scores)
    if not scores_list:
        return 1
    top_score = max(scores_list)
    if top_score >= 0.85:
        return 1
    if top_score >= 0.75:
        return 2
    return 3


def _format_seed_hits(hits: list[SeedHit]) -> str:
    lines = ["Semantic seed hits:"]
    for hit in hits:
        display = hit.qualified_name or hit.name or f"node:{hit.node_id}"
        lines.append(
            f"- {display} ({hit.node_type}, score={hit.score:.3f}, id={hit.node_id})"
        )
    return "\n".join(lines)


def _format_expansions(expansions: list[ExpansionHit]) -> str:
    if not expansions:
        return "Graph expansions: none"
    lines = ["Graph expansions:"]
    for exp in expansions:
        neighbor_name = exp.neighbor_name or f"node:{exp.neighbor_id}"
        label_str = ", ".join(exp.neighbor_labels) if exp.neighbor_labels else "Unknown"
        rel_str = "->".join(exp.relationship_types) if exp.relationship_types else "RELATED"
        lines.append(
            f"- Seed {exp.seed_name} -> {neighbor_name} ({label_str}) via {rel_str}"
        )
    return "\n".join(lines)


def _trim_source(source: str, limit: int = 2000) -> str:
    if len(source) <= limit:
        return source
    return f"{source[:limit]}\n... [truncated]"


def _read_file_head(file_path: str, repo_path: str, max_lines: int = 80) -> str | None:
    path_obj = Path(file_path)
    if not path_obj.is_absolute():
        path_obj = Path(repo_path) / path_obj
    if not path_obj.exists():
        return None
    try:
        with open(path_obj, "r", encoding="utf-8") as handle:
            lines = list(islice(handle, max_lines))
        return "".join(lines).strip()
    except Exception as exc:
        logger.warning("Failed to read file head for {}: {}", path_obj, exc)
        return None


def _fetch_node_location(node_id: int, repo_path: str) -> dict[str, Any] | None:
    query = """
    MATCH (n)
    WHERE id(n) = $node_id AND n._repo_path = $repo_path
    OPTIONAL MATCH (m:Module)-[:DEFINES|CONTAINS*..5]->(n)
    RETURN labels(n) AS labels,
           n.qualified_name AS qualified_name,
           n.name AS name,
           n.start_line AS start_line,
           n.end_line AS end_line,
           coalesce(m.path, n.path) AS path
    LIMIT 1
    """
    results = execute_read_query(
        host=settings.MEMGRAPH_HOST,
        port=settings.MEMGRAPH_PORT,
        query=query,
        params={"node_id": node_id, "repo_path": repo_path},
    )
    if not results:
        return None
    return results[0]


def _get_node_source_snippet(node_id: int, repo_path: str) -> str | None:
    info = _fetch_node_location(node_id, repo_path)
    if not info:
        return None
    labels = set(info.get("labels") or [])
    path = info.get("path")
    start_line = info.get("start_line")
    end_line = info.get("end_line")

    if not path:
        return None

    if labels.intersection({"Function", "Method", "Class"}) and start_line and end_line:
        return extract_source_lines(
            Path(path), int(start_line), int(end_line), repo_path=repo_path
        )

    if labels.intersection({"Module", "File"}):
        return _read_file_head(path, repo_path=repo_path)

    return None


def _format_sources(label: str, sources: list[tuple[str, str]]) -> str:
    if not sources:
        return f"{label}: none"
    lines = [f"{label}:"]
    for name, source in sources:
        lines.append(f"- {name}:\n```\n{_trim_source(source)}\n```")
    return "\n".join(lines)


def _collect_sources(
    nodes: list[tuple[int, str]],
    *,
    repo_path: str,
    max_items: int,
) -> list[tuple[str, str]]:
    sources: list[tuple[str, str]] = []
    for node_id, display_name in nodes:
        if len(sources) >= max_items:
            break
        source = _get_node_source_snippet(node_id, repo_path=repo_path)
        if source:
            sources.append((display_name, source))
    return sources


async def _gather_seeds(queries: list[str], repo_path: str, top_k: int) -> list[SeedHit]:
    """Gather semantic and keyword seeds for a set of queries."""
    all_hits = {}  # node_id -> hit_dict
    for query in queries:
        # Semantic search
        sem_results = await semantic_code_search_async(
            query, top_k=top_k, repo_path=repo_path
        )
        for res in sem_results:
            all_hits[res["node_id"]] = res

        # Keyword search
        potential_keywords = re.findall(r"\b[A-Z][a-zA-Z0-9_]+\b", query)
        if potential_keywords:
            logger.debug(f"Searching for keyword seeds in round: {potential_keywords}")
            placeholders = ", ".join(f"${i}" for i in range(len(potential_keywords)))
            kw_query = f"""
            MATCH (n)
            WHERE (n.name IN [{placeholders}] OR n.qualified_name IN [{placeholders}])
              AND n._repo_path = $repo_path
            RETURN id(n) AS node_id, n.qualified_name AS qualified_name, 
                   n.name AS name, labels(n) AS type
            LIMIT 5
            """
            kw_params = {str(i): kw for i, kw in enumerate(potential_keywords)}
            kw_params["repo_path"] = repo_path
            kw_results = execute_read_query(
                host=settings.MEMGRAPH_HOST,
                port=settings.MEMGRAPH_PORT,
                query=kw_query,
                params=kw_params,
            )
            for res in kw_results:
                if res["node_id"] not in all_hits:
                    logger.info(f"  Found keyword seed: {res['name']} ({res['node_id']})")
                    all_hits[res["node_id"]] = {
                        "node_id": res["node_id"],
                        "qualified_name": res["qualified_name"],
                        "name": res["name"],
                        "type": res["type"][0] if res["type"] else "Unknown",
                        "score": 1.0,
                    }

    return [
        SeedHit(
            node_id=hit["node_id"],
            qualified_name=hit.get("qualified_name") or "",
            name=hit.get("name") or "",
            node_type=hit.get("type") or "Unknown",
            score=float(hit.get("score") or 0.0),
        )
        for hit in all_hits.values()
    ]


def _extract_sufficiency_info(response: str) -> tuple[str, list[str]]:
    """Extract sufficiency status and missing concepts from response."""
    status = "Sufficient"
    missing = []

    # Context Sufficiency: [Sufficient/Partial/Insufficient]
    status_match = re.search(
        r"Context Sufficiency:\s*(Sufficient|Partial|Insufficient|None Detected)",
        response,
        re.IGNORECASE,
    )
    if status_match:
        status = status_match.group(1).capitalize()

    # Missing: [List exact symbol names, concepts, or missing implementation details, or 'None']
    missing_match = re.search(r"Missing:\s*(.*)", response, re.IGNORECASE)
    if missing_match:
        concepts_str = missing_match.group(1).strip()
        if concepts_str.lower() != "none" and concepts_str:
            # Handle comma separated or bulleted lists
            parts = re.split(r",|\*|\s*-\s*", concepts_str)
            missing = [p.strip() for p in parts if p.strip()]

    return status, missing


async def run_semantic_seed_strategy(
    question: str,
    repo_path: str,
    *,
    top_k: int = 10,
    max_neighbors: int = 75,
    max_retries: int = 2,
    synthesizer_factory: Callable[[], Any] = create_context_synthesizer,
) -> str:
    if not question.strip():
        return "Please provide a question after `/semantic-seed-strategy`."

    logger.info("Starting semantic seed strategy for question: {}", question)
    logger.info("Repo path: {}", repo_path)

    current_search_queries = [question]
    accumulated_seed_hits: dict[int, SeedHit] = {}
    accumulated_neighbor_ids: set[int] = set()
    all_expansions: list[ExpansionHit] = []
    
    last_response = ""

    for attempt in range(max_retries + 1):
        logger.info(
            "Semantic Seed Strategy: Round {}/{} ({} search queries)",
            attempt + 1,
            max_retries + 1,
            len(current_search_queries),
        )

        # 1. Gather seeds for current queries
        try:
            new_seeds = await _gather_seeds(current_search_queries, repo_path, top_k)
        except Exception as exc:
            logger.error("Seed gathering failed: {}", exc, exc_info=True)
            return f"Error gathering semantic seeds: {exc}"
        
        # Keep only truly new seeds
        truly_new_seeds = [s for s in new_seeds if s.node_id not in accumulated_seed_hits]
        for s in truly_new_seeds:
            accumulated_seed_hits[s.node_id] = s

        if not truly_new_seeds and attempt > 0:
            logger.info("  No new seeds found in this round. Stopping.")
            break
            
        if not accumulated_seed_hits:
             return (
                f"No semantic or keyword matches found for: '{question}'. "
                "Try a more specific intent query."
            )

        # 2. Expand from all seeds (potentially deeper if context is thin)
        seed_hits = list(accumulated_seed_hits.values())
        depth = _choose_expansion_depth([hit.score for hit in seed_hits])
        node_ids = [hit.node_id for hit in seed_hits]
        placeholders = ", ".join(f"${i}" for i in range(len(node_ids)))
        limit = max(10, min(max_neighbors, 20 + len(node_ids) * 10))
        
        expansion_query = f"""
        MATCH (seed)
        WHERE id(seed) IN [{placeholders}] AND seed._repo_path = $repo_path
        MATCH path=(seed)-[rels*1..{depth}]-(neighbor)
        WHERE neighbor._repo_path = $repo_path
        RETURN id(seed) AS seed_id,
               coalesce(seed.qualified_name, seed.name) AS seed_name,
               id(neighbor) AS neighbor_id,
               coalesce(neighbor.qualified_name, neighbor.name) AS neighbor_name,
               labels(neighbor) AS neighbor_labels,
               [rel IN rels | type(rel)] AS relationship_types
        LIMIT $limit
        """

        params = {str(i): node_id for i, node_id in enumerate(node_ids)}
        params["repo_path"] = repo_path
        params["limit"] = limit

        logger.info(
            "  Graph expansion query (round={}, depth={}, limit={}): symbols={}",
            attempt + 1,
            depth,
            limit,
            [h.name for h in seed_hits[:5]] + (["..."] if len(seed_hits) > 5 else []),
        )

        expansions_raw = execute_read_query(
            host=settings.MEMGRAPH_HOST,
            port=settings.MEMGRAPH_PORT,
            query=expansion_query,
            params=params,
        )

        logger.info("  Found {} graph expansions.", len(expansions_raw))
        
        # Process expansions
        new_expansions = []
        for row in expansions_raw:
            exp = ExpansionHit(
                seed_id=row["seed_id"],
                seed_name=row.get("seed_name") or f"node:{row['seed_id']}",
                neighbor_id=row["neighbor_id"],
                neighbor_name=row.get("neighbor_name") or f"node:{row['neighbor_id']}",
                neighbor_labels=row.get("neighbor_labels") or [],
                relationship_types=row.get("relationship_types") or [],
            )
            new_expansions.append(exp)
            accumulated_neighbor_ids.add(exp.neighbor_id)
            
        all_expansions = new_expansions # Refresh expansions with all seeds

        # 3. Collect sources
        seed_source_nodes = [
            (hit.node_id, hit.qualified_name or hit.name or f"node:{hit.node_id}")
            for hit in seed_hits
            if hit.node_type in {"Function", "Method", "Class"}
        ]
        seed_sources = _collect_sources(
            seed_source_nodes,
            repo_path=repo_path,
            max_items=min(5 + attempt * 2, len(seed_hits)),
        )
        
        neighbor_source_nodes = []
        for exp in all_expansions:
            if not {"Function", "Method", "Class", "Module", "File"}.intersection(
                exp.neighbor_labels
            ):
                continue
            neighbor_source_nodes.append(
                (exp.neighbor_id, exp.neighbor_name or f"node:{exp.neighbor_id}")
            )
            
        # Unique neighbor source nodes
        unique_neighbor_nodes = []
        seen_ids = set()
        for nid, name in neighbor_source_nodes:
            if nid not in seen_ids:
                unique_neighbor_nodes.append((nid, name))
                seen_ids.add(nid)

        neighbor_sources = _collect_sources(
            unique_neighbor_nodes,
            repo_path=repo_path,
            max_items=5 + attempt * 5,
        )

        # 4. Synthesize
        context_blocks = [
            f"Question: {question}",
            f"Expansion depth: {depth}",
            f"Retrieval round: {attempt + 1}",
            _format_seed_hits(seed_hits),
            _format_expansions(all_expansions),
            _format_sources("Seed source snippets", seed_sources),
            _format_sources("Neighbor source snippets", neighbor_sources),
        ]
        context = "\n\n".join(context_blocks)

        try:
            synthesizer = synthesizer_factory()
            prompt = (
                "Use ONLY the following context to answer the user's question. "
                "If the context is insufficient, say so explicitly in the 'Context Sufficiency' section.\n\n"
                f"{context}"
            )
            result = await synthesizer.run(prompt)
            last_response = result.output
            
            # 5. Check sufficiency
            status, missing_concepts = _extract_sufficiency_info(last_response)
            logger.info("  Round {} sufficiency: {} (Missing: {})", attempt + 1, status, missing_concepts)
            
            if status == "Sufficient" or not missing_concepts:
                break
                
            # Prepare for next round
            current_search_queries = missing_concepts
            
        except Exception as e:
            logger.error("  Synthesis round failed: {}", e)
            if attempt == 0:
                 return f"Semantic seed strategy failed: {e}"
            break

    return last_response

