from pathlib import Path

import pytest

from codebase_rag.tools.semantic_seed_strategy import run_semantic_seed_strategy
from codebase_rag.tools.slash_commands import get_help_text, parse_slash_command


def test_parse_slash_command_strips_token() -> None:
    command, remainder = parse_slash_command("/help show me commands")
    assert command == "/help"
    assert remainder == "show me commands"


def test_parse_slash_command_accepts_multiline_question() -> None:
    command, remainder = parse_slash_command(
        "/semantic-seed-strategy\nwhat is the Durchführung tab used for?"
    )
    assert command == "/semantic-seed-strategy"
    assert remainder == "what is the Durchführung tab used for?"


def test_parse_slash_command_ignores_unknown() -> None:
    command, remainder = parse_slash_command("/unknown do stuff")
    assert command is None
    assert remainder == "/unknown do stuff"


def test_help_text_lists_commands() -> None:
    help_text = get_help_text()
    assert "/help" in help_text
    assert "/semantic-seed-strategy" in help_text


@pytest.mark.asyncio
async def test_semantic_seed_strategy_expands_graph(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def fake_search(
        query: str, top_k: int, repo_path: str | None = None
    ) -> list[dict]:
        return [
            {
                "node_id": 1,
                "qualified_name": "pkg.mod.fn",
                "name": "fn",
                "type": "Function",
                "score": 0.8,
            }
        ]

    captured: dict[str, object] = {}
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    sample_file = repo_root / "sample.py"
    sample_file.write_text("def fn():\n    return 1\n\n")

    def fake_execute_read_query(
        *, host: str, port: int, query: str, params: dict
    ) -> list[dict]:
        if "RETURN id(seed)" in query:
            captured["query"] = query
            captured["params"] = params
            return [
                {
                    "seed_id": 1,
                    "seed_name": "pkg.mod.fn",
                    "neighbor_id": 2,
                    "neighbor_name": "pkg.mod.helper",
                    "neighbor_labels": ["Function"],
                    "relationship_types": ["CALLS"],
                }
            ]
        if "RETURN labels(n)" in query:
            return [
                {
                    "labels": ["Function"],
                    "qualified_name": "pkg.mod.fn",
                    "name": "fn",
                    "start_line": 1,
                    "end_line": 2,
                    "path": "sample.py",
                }
            ]
        return []

    class DummySynthesizer:
        async def run(self, prompt: str) -> object:
            class Result:
                output = "answer"

            return Result()

    def fake_factory() -> DummySynthesizer:
        return DummySynthesizer()

    monkeypatch.setattr(
        "codebase_rag.tools.semantic_seed_strategy.semantic_code_search_async",
        fake_search,
    )
    monkeypatch.setattr(
        "codebase_rag.tools.semantic_seed_strategy.execute_read_query",
        fake_execute_read_query,
    )

    result = await run_semantic_seed_strategy(
        "find helper", str(repo_root), synthesizer_factory=fake_factory
    )

    assert result == "answer"
    assert "*1..1" in str(captured["query"])
    assert captured["params"]["repo_path"] == str(repo_root)
