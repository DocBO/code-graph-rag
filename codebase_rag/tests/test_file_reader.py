from __future__ import annotations

from pathlib import Path

import pytest

from codebase_rag.tools.file_reader import (
    FileReader,
    FileReadResult,
    create_file_reader_tool,
)


@pytest.fixture
def file_reader(tmp_path: Path) -> FileReader:
    return FileReader(project_root=str(tmp_path))


class TestFileReader:
    @pytest.mark.asyncio
    async def test_reads_text_file(
        self, file_reader: FileReader, tmp_path: Path
    ) -> None:
        test_file = tmp_path / "hello.py"
        test_file.write_text("print('hello')")
        result = await file_reader.read_file("hello.py")
        assert result.error_message is None
        assert result.content == "print('hello')"
        assert result.file_path == "hello.py"

    @pytest.mark.asyncio
    async def test_file_not_found(self, file_reader: FileReader) -> None:
        result = await file_reader.read_file("nonexistent.py")
        assert result.error_message == "File not found."
        assert result.content is None

    @pytest.mark.asyncio
    async def test_directory_traversal_prevented(self, file_reader: FileReader) -> None:
        result = await file_reader.read_file("../outside.txt")
        assert result.error_message is not None
        assert "outside of project root" in result.error_message

    @pytest.mark.asyncio
    async def test_symlink_traversal_prevented(
        self, file_reader: FileReader, tmp_path: Path
    ) -> None:
        outside = tmp_path.parent / "outside.txt"
        outside.write_text("secret")
        symlink = tmp_path / "link.txt"
        symlink.symlink_to(outside)
        result = await file_reader.read_file("link.txt")
        assert result.error_message is not None
        assert "outside of project root" in result.error_message

    @pytest.mark.asyncio
    async def test_binary_extension_blocked(
        self, file_reader: FileReader, tmp_path: Path
    ) -> None:
        pdf = tmp_path / "doc.pdf"
        pdf.write_text("%PDF fake")
        result = await file_reader.read_file("doc.pdf")
        assert result.error_message is not None
        assert "binary file" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_png_blocked(self, file_reader: FileReader, tmp_path: Path) -> None:
        png = tmp_path / "img.png"
        png.write_text("\x89PNG fake")
        result = await file_reader.read_file("img.png")
        assert result.error_message is not None
        assert "binary file" in result.error_message.lower()


class TestCreateFileReaderTool:
    def test_creates_tool_object(self, file_reader: FileReader) -> None:
        tool = create_file_reader_tool(file_reader)
        assert tool is not None
        assert callable(tool.function)


class TestFileReadResult:
    def test_success_result(self) -> None:
        result = FileReadResult(file_path="test.py", content="code")
        assert result.error_message is None
        assert result.content == "code"

    def test_error_result(self) -> None:
        result = FileReadResult(file_path="test.py", error_message="not found")
        assert result.content is None
        assert result.error_message == "not found"
