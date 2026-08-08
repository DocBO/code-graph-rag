from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from codebase_rag.schemas import CodeSnippet
from codebase_rag.tools.code_retrieval import CodeRetriever, create_code_retrieval_tool


@pytest.fixture
def mock_ingestor() -> MagicMock:
    return MagicMock()


@pytest.fixture
def code_retriever(tmp_path: Path, mock_ingestor: MagicMock) -> CodeRetriever:
    return CodeRetriever(project_root=str(tmp_path), ingestor=mock_ingestor)


class TestCodeRetriever:
    @pytest.mark.asyncio
    async def test_returns_not_found_when_no_results(
        self, code_retriever: CodeRetriever, mock_ingestor: MagicMock
    ) -> None:
        mock_ingestor.fetch_all.return_value = []
        result = await code_retriever.find_code_snippet("missing.func")
        assert isinstance(result, CodeSnippet)
        assert result.found is False
        assert result.error_message == "Entity not found in graph."

    @pytest.mark.asyncio
    async def test_returns_not_found_when_location_missing(
        self, code_retriever: CodeRetriever, mock_ingestor: MagicMock
    ) -> None:
        mock_ingestor.fetch_all.return_value = [
            {"path": None, "start": None, "end": None}
        ]
        result = await code_retriever.find_code_snippet("bad.location")
        assert result.found is False
        assert "missing location data" in (result.error_message or "")

    @pytest.mark.asyncio
    async def test_returns_not_found_when_path_only(
        self, code_retriever: CodeRetriever, mock_ingestor: MagicMock
    ) -> None:
        mock_ingestor.fetch_all.return_value = [
            {"path": "some/file.py", "start": None, "end": None}
        ]
        result = await code_retriever.find_code_snippet("partial.location")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_extracts_source_code_from_file(
        self, code_retriever: CodeRetriever, mock_ingestor: MagicMock, tmp_path: Path
    ) -> None:
        test_file = tmp_path / "test_code.py"
        test_file.write_text("line1\nline2\nline3\nline4\nline5\n")
        mock_ingestor.fetch_all.return_value = [
            {"path": "test_code.py", "start": 2, "end": 4, "docstring": "does stuff"}
        ]
        result = await code_retriever.find_code_snippet("test.code")
        assert result.found is True
        assert result.source_code.rstrip("\n") == "line2\nline3\nline4"
        assert result.file_path == "test_code.py"
        assert result.line_start == 2
        assert result.line_end == 4
        assert result.docstring == "does stuff"

    @pytest.mark.asyncio
    async def test_handles_exception_gracefully(
        self, code_retriever: CodeRetriever, mock_ingestor: MagicMock
    ) -> None:
        mock_ingestor.fetch_all.side_effect = RuntimeError("db down")
        result = await code_retriever.find_code_snippet("any.func")
        assert result.found is False
        assert "db down" in (result.error_message or "")


class TestCreateCodeRetrievalTool:
    def test_creates_tool_object(self, code_retriever: CodeRetriever) -> None:
        tool = create_code_retrieval_tool(code_retriever)
        assert tool is not None
        assert callable(tool.function)
