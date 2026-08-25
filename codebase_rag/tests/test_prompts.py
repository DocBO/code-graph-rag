from __future__ import annotations

from codebase_rag.prompts import (
    CONTEXT_SYNTHESIS_PROMPT,
    CYPHER_SYSTEM_PROMPT,
    GRAPH_SCHEMA_AND_RULES,
    LOCAL_CYPHER_SYSTEM_PROMPT,
    RAG_ORCHESTRATOR_SYSTEM_PROMPT,
    RAG_READ_ONLY_SYSTEM_PROMPT,
)
from codebase_rag.tools.enhanced_semantic_search import (
    create_enhanced_semantic_search_tool,
)


class TestGraphSchemaAndRules:
    def test_contains_required_node_labels(self) -> None:
        for label in [
            "Project",
            "Function",
            "Method",
            "Class",
            "File",
            "Module",
            "ExternalPackage",
        ]:
            assert label in GRAPH_SCHEMA_AND_RULES, f"Missing node label: {label}"

    def test_contains_required_relationships(self) -> None:
        for rel in [
            "CALLS",
            "DEFINES",
            "IMPORTS",
            "INHERITS",
            "IMPLEMENTS",
            "CONTAINS_FILE",
            "DEPENDS_ON_EXTERNAL",
        ]:
            assert rel in GRAPH_SCHEMA_AND_RULES, f"Missing relationship: {rel}"

    def test_contains_repo_path_rule(self) -> None:
        assert "$repo_path" in CYPHER_SYSTEM_PROMPT

    def test_contains_starts_with_guidance(self) -> None:
        assert "STARTS WITH" in GRAPH_SCHEMA_AND_RULES


class TestCypherSystemPrompt:
    def test_includes_graph_schema(self) -> None:
        assert GRAPH_SCHEMA_AND_RULES in CYPHER_SYSTEM_PROMPT

    def test_prohibits_semicolons(self) -> None:
        assert "NO SEMICOLONS" in CYPHER_SYSTEM_PROMPT.upper()

    def test_requires_repo_isolation(self) -> None:
        assert "$repo_path" in CYPHER_SYSTEM_PROMPT


class TestLocalCypherSystemPrompt:
    def test_includes_graph_schema(self) -> None:
        assert GRAPH_SCHEMA_AND_RULES in LOCAL_CYPHER_SYSTEM_PROMPT

    def test_prohibits_semicolons(self) -> None:
        assert "NO SEMICOLONS" in LOCAL_CYPHER_SYSTEM_PROMPT.upper()

    def test_prohibits_union(self) -> None:
        assert "NO `UNION`" in LOCAL_CYPHER_SYSTEM_PROMPT

    def test_requires_clause_order(self) -> None:
        assert "CLAUSE ORDER" in LOCAL_CYPHER_SYSTEM_PROMPT

    def test_contains_example_queries(self) -> None:
        assert "MATCH" in LOCAL_CYPHER_SYSTEM_PROMPT


class TestContextSynthesisPrompt:
    def test_requires_context_sufficiency_section(self) -> None:
        assert "Context Sufficiency" in CONTEXT_SYNTHESIS_PROMPT

    def test_restricts_to_provided_context(self) -> None:
        assert "ONLY the provided context" in CONTEXT_SYNTHESIS_PROMPT


class TestRagOrchestratorSystemPrompt:
    def test_contains_tool_only_rule(self) -> None:
        assert "TOOL-ONLY ANSWERS" in RAG_ORCHESTRATOR_SYSTEM_PROMPT

    def test_contains_semantic_first_strategy(self) -> None:
        assert "SEMANTIC SEARCH FIRST" in RAG_ORCHESTRATOR_SYSTEM_PROMPT

    def test_contains_hybrid_approach(self) -> None:
        assert "HYBRID APPROACH" in RAG_ORCHESTRATOR_SYSTEM_PROMPT

    def test_describes_focused_qdrant_corpus_in_both_query_prompts(self) -> None:
        for prompt in (RAG_ORCHESTRATOR_SYSTEM_PROMPT, RAG_READ_ONLY_SYSTEM_PROMPT):
            assert "Python names/docstrings and Markdown chunks only" in prompt
            assert "a Qdrant miss does not mean the code is absent" in prompt

    def test_semantic_tool_describes_focused_corpus(self) -> None:
        tool = create_enhanced_semantic_search_tool(repo_path="/tmp/repo")
        assert (
            "Python API names/docstrings and Markdown documentation" in tool.description
        )
