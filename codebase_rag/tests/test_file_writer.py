from __future__ import annotations

from pathlib import Path

import pytest

from codebase_rag.tools.file_writer import (
    FileCreationResult,
    FileWriter,
    create_file_writer_tool,
)


@pytest.fixture
def file_writer(tmp_path: Path) -> FileWriter:
    return FileWriter(project_root=str(tmp_path))


class TestFileWriter:
    @pytest.mark.asyncio
    async def test_creates_new_file(
        self, file_writer: FileWriter, tmp_path: Path
    ) -> None:
        result = await file_writer.create_file("new_file.py", "print('hello')")
        assert result.success is True
        assert result.error_message is None
        created = tmp_path / "new_file.py"
        assert created.exists()
        assert created.read_text() == "print('hello')"

    @pytest.mark.asyncio
    async def test_overwrites_existing_file(
        self, file_writer: FileWriter, tmp_path: Path
    ) -> None:
        existing = tmp_path / "existing.py"
        existing.write_text("old content")
        result = await file_writer.create_file("existing.py", "new content")
        assert result.success is True
        assert existing.read_text() == "new content"

    @pytest.mark.asyncio
    async def test_creates_parent_directories(
        self, file_writer: FileWriter, tmp_path: Path
    ) -> None:
        result = await file_writer.create_file("deep/nested/path/file.py", "content")
        assert result.success is True
        created = tmp_path / "deep" / "nested" / "path" / "file.py"
        assert created.exists()
        assert created.read_text() == "content"

    @pytest.mark.asyncio
    async def test_directory_traversal_prevented(self, file_writer: FileWriter) -> None:
        result = await file_writer.create_file("../outside.py", "bad")
        assert result.success is False
        assert "outside of project root" in (result.error_message or "")

    @pytest.mark.asyncio
    async def test_empty_content(self, file_writer: FileWriter, tmp_path: Path) -> None:
        result = await file_writer.create_file("empty.py", "")
        assert result.success is True
        created = tmp_path / "empty.py"
        assert created.exists()
        assert created.read_text() == ""


class TestCreateFileWriterTool:
    def test_creates_tool_object(self, file_writer: FileWriter) -> None:
        tool = create_file_writer_tool(file_writer)
        assert tool is not None
        assert callable(tool.function)


class TestFileCreationResult:
    def test_success_result(self) -> None:
        result = FileCreationResult(file_path="test.py", success=True)
        assert result.success is True
        assert result.error_message is None

    def test_error_result(self) -> None:
        result = FileCreationResult(
            file_path="test.py", success=False, error_message="permission denied"
        )
        assert result.success is False
        assert result.error_message == "permission denied"
