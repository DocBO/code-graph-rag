from __future__ import annotations

import pytest
from pydantic_ai.messages import ModelRequest, ToolReturnPart

from codebase_rag.mcp.server import _extract_retrieval_metadata
from codebase_rag.schemas import CodeSnippet, GraphData


@pytest.mark.parametrize("snippet_first", [False, True])
@pytest.mark.parametrize("graph_start", [None, 12])
def test_duplicate_citations_keep_the_complete_snippet_range(
    snippet_first: bool, graph_start: int | None
) -> None:
    graph = GraphData(
        query_used="MATCH (n) RETURN n",
        summary="ok",
        results=[
            {
                "qualified_name": "pkg.auth.login",
                "path": "src/auth.py",
                "start_line": graph_start,
            }
        ],
    )
    snippet = CodeSnippet(
        qualified_name="pkg.auth.login",
        file_path="src/auth.py",
        source_code="def login(): pass",
        line_start=10,
        line_end=22,
    )
    contents = [snippet, graph] if snippet_first else [graph, snippet]
    request = ModelRequest(
        parts=[
            ToolReturnPart(tool_name="lookup", tool_call_id=str(index), content=content)
            for index, content in enumerate(contents)
        ]
    )

    assert _extract_retrieval_metadata([request])["sources"] == [
        {
            "qualified_name": "pkg.auth.login",
            "filename": "src/auth.py",
            "start_line": 10,
            "end_line": 22,
        }
    ]
