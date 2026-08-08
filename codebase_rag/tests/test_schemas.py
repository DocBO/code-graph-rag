from __future__ import annotations

import pytest

from codebase_rag.schemas import CodeSnippet, GraphData, ShellCommandResult


class TestGraphData:
    def test_format_results_accepts_list_of_dicts(self) -> None:
        data = GraphData(
            query_used="MATCH (n) RETURN n",
            results=[{"name": "foo", "value": 42}, {"name": "bar", "value": True}],
            summary="ok",
        )
        assert len(data.results) == 2
        assert data.results[0]["name"] == "foo"
        assert data.results[0]["value"] == 42
        assert data.results[1]["value"] is True

    def test_format_results_coerces_non_serializable_to_string(self) -> None:
        class Custom:
            def __str__(self) -> str:
                return "custom_str"

        data = GraphData(
            query_used="x",
            results=[{"obj": Custom()}],
            summary="coerced",
        )
        assert data.results[0]["obj"] == "custom_str"

    def test_format_results_returns_empty_list_for_non_list_input(self) -> None:
        data = GraphData(query_used="x", results="not_a_list", summary="nope")
        assert data.results == []

    def test_format_results_preserves_nested_structures(self) -> None:
        data = GraphData(
            query_used="x",
            results=[{"nested": {"key": [1, 2, 3]}}],
            summary="nested",
        )
        assert data.results[0]["nested"] == {"key": [1, 2, 3]}

    def test_extra_forbidden(self) -> None:
        with pytest.raises(Exception):
            GraphData(query_used="x", results=[], summary="s", extra_field=1)


class TestCodeSnippet:
    def test_defaults(self) -> None:
        snippet = CodeSnippet(
            qualified_name="foo.bar",
            source_code="def bar(): pass",
            file_path="/test/foo.py",
            line_start=1,
            line_end=3,
        )
        assert snippet.found is True
        assert snippet.error_message is None

    def test_not_found(self) -> None:
        snippet = CodeSnippet(
            qualified_name="missing",
            source_code="",
            file_path="",
            line_start=0,
            line_end=0,
            found=False,
            error_message="not found",
        )
        assert snippet.found is False
        assert snippet.error_message == "not found"

    def test_docstring_is_optional(self) -> None:
        snippet = CodeSnippet(
            qualified_name="a.b",
            source_code="pass",
            file_path="x",
            line_start=1,
            line_end=1,
        )
        assert snippet.docstring is None

        snippet_with_doc = CodeSnippet(
            qualified_name="a.b",
            source_code="pass",
            file_path="x",
            line_start=1,
            line_end=1,
            docstring="doc",
        )
        assert snippet_with_doc.docstring == "doc"


class TestShellCommandResult:
    def test_valid_result(self) -> None:
        result = ShellCommandResult(return_code=0, stdout="ok", stderr="")
        assert result.return_code == 0
        assert result.stdout == "ok"
        assert result.stderr == ""

    def test_error_result(self) -> None:
        result = ShellCommandResult(return_code=1, stdout="", stderr="cmd not found")
        assert result.return_code == 1
        assert result.stderr == "cmd not found"
