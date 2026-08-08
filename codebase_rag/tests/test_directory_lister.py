from pathlib import Path

from codebase_rag.tools.directory_lister import DirectoryLister


def test_directory_lister_rejects_outside_path_without_raising(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    lister = DirectoryLister(str(project_root))

    result = lister.list_directory_contents("/semantic-seed-strategy")

    assert (
        result == "Error: Access denied: Cannot access files outside the project root."
    )
