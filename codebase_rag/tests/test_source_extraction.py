from __future__ import annotations

from pathlib import Path

from codebase_rag.utils.source_extraction import (
    extract_source_lines,
    extract_source_with_fallback,
    validate_source_location,
)


class TestExtractSourceLines:
    def test_extracts_specific_lines(self, tmp_path: Path) -> None:
        file = tmp_path / "test.py"
        file.write_text("line1\nline2\nline3\nline4\nline5\n")
        result = extract_source_lines(file, 2, 4)
        assert result == "line2\nline3\nline4"

    def test_extracts_single_line(self, tmp_path: Path) -> None:
        file = tmp_path / "test.py"
        file.write_text("a\nb\nc\n")
        result = extract_source_lines(file, 1, 1)
        assert result == "a"

    def test_returns_none_for_missing_file(self, tmp_path: Path) -> None:
        result = extract_source_lines(tmp_path / "nonexistent.py", 1, 5)
        assert result is None

    def test_returns_none_for_invalid_range_start_zero(self, tmp_path: Path) -> None:
        file = tmp_path / "test.py"
        file.write_text("content\n")
        result = extract_source_lines(file, 0, 1)
        assert result is None

    def test_returns_none_for_invalid_range_reversed(self, tmp_path: Path) -> None:
        file = tmp_path / "test.py"
        file.write_text("content\n")
        result = extract_source_lines(file, 5, 1)
        assert result is None

    def test_returns_none_for_range_exceeding_length(self, tmp_path: Path) -> None:
        file = tmp_path / "test.py"
        file.write_text("line1\nline2\n")
        result = extract_source_lines(file, 1, 100)
        assert result is None

    def test_resolves_relative_path_with_repo_path(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        file = repo / "src/main.py"
        file.parent.mkdir(parents=True)
        file.write_text("hello\nworld\n")
        result = extract_source_lines(Path("src/main.py"), 1, 2, repo_path=str(repo))
        assert result == "hello\nworld"


class TestValidateSourceLocation:
    def test_valid_location(self) -> None:
        valid, path_obj = validate_source_location("/tmp/test.py", 1, 10)
        assert valid is True
        assert path_obj == Path("/tmp/test.py")

    def test_missing_file_path(self) -> None:
        valid, path_obj = validate_source_location(None, 1, 10)
        assert valid is False
        assert path_obj is None

    def test_missing_start_line(self) -> None:
        valid, path_obj = validate_source_location("/tmp/test.py", None, 10)
        assert valid is False

    def test_missing_end_line(self) -> None:
        valid, path_obj = validate_source_location("/tmp/test.py", 1, None)
        assert valid is False

    def test_relative_path_resolved_with_repo_path(self) -> None:
        valid, path_obj = validate_source_location(
            "src/main.py", 1, 10, repo_path="/home/user/repo"
        )
        assert valid is True
        assert path_obj == Path("/home/user/repo/src/main.py")

    def test_absolute_path_ignores_repo_path(self) -> None:
        valid, path_obj = validate_source_location(
            "/absolute/path/file.py", 1, 10, repo_path="/home/user/repo"
        )
        assert valid is True
        assert path_obj == Path("/absolute/path/file.py")

    def test_invalid_path_returns_false(self) -> None:
        valid, path_obj = validate_source_location("", 1, 10)
        assert valid is False


class TestExtractSourceWithFallback:
    def test_falls_back_to_extract_source_lines(self, tmp_path: Path) -> None:
        file = tmp_path / "test.py"
        file.write_text("line1\nline2\nline3\n")
        result = extract_source_with_fallback(file, 1, 3)
        assert result == "line1\nline2\nline3"

    def test_uses_ast_extractor_when_provided(self, tmp_path: Path) -> None:
        file = tmp_path / "test.py"
        file.write_text("def foo(): pass\n")

        def fake_extractor(qn: str, fp: Path) -> str:
            return "def foo(): pass"

        result = extract_source_with_fallback(
            file, 1, 1, qualified_name="foo", ast_extractor=fake_extractor
        )
        assert result == "def foo(): pass"

    def test_falls_back_when_ast_returns_none(self, tmp_path: Path) -> None:
        file = tmp_path / "test.py"
        file.write_text("line1\nline2\n")

        def fake_extractor(qn: str, fp: Path) -> str | None:
            return None

        result = extract_source_with_fallback(
            file, 1, 2, qualified_name="foo", ast_extractor=fake_extractor
        )
        assert result == "line1\nline2"

    def test_falls_back_when_ast_raises(self, tmp_path: Path) -> None:
        file = tmp_path / "test.py"
        file.write_text("line1\nline2\n")

        def failing_extractor(qn: str, fp: Path) -> str:
            raise RuntimeError("boom")

        result = extract_source_with_fallback(
            file, 1, 2, qualified_name="foo", ast_extractor=failing_extractor
        )
        assert result == "line1\nline2"
