<!-- OPENSPEC:START -->
# OpenSpec Instructions

These instructions are for AI assistants working in this project.

Always open `@/openspec/AGENTS.md` when the request:
- Mentions planning or proposals (words like proposal, spec, change, plan)
- Introduces new capabilities, breaking changes, architecture shifts, or big performance/security work
- Sounds ambiguous and you need the authoritative spec before coding

Use `@/openspec/AGENTS.md` to learn:
- How to create and apply change proposals
- Spec format and conventions
- Project structure and guidelines

Keep this managed block so 'openspec update' can refresh the instructions.

<!-- OPENSPEC:END -->

# Repository Guidelines

## Project Structure & Module Organization
Core logic lives in `codebase_rag/`, with parsers in `codebase_rag/parsers`, provider adapters in `codebase_rag/providers`, and helpers across `codebase_rag/services` and `codebase_rag/utils`. Tests live beside the code in `codebase_rag/tests`, mirroring package names for quick navigation. Reference assets in `assets/`, long-form docs in `docs/`, runnable snippets in `examples/`, and Tree-sitter sources in `grammars/`. Use `realtime_updater.py` or `make watch` when a repo needs continuous ingestion.

## Build, Test, and Development Commands
Run `uv sync` for Python-only work or `uv sync --extra treesitter-full` (same as `make install`) for multi-language parsing. `make dev` adds dev/test extras and installs hooks, while `make all` bootstraps everything plus a verification test run. Start Memgraph with `docker-compose up -d` before invoking `python -m codebase_rag.main start --repo-path /path/to/repo`. Use `make test` for the standard pytest pass or `make test-parallel` to accelerate with xdist.

## Coding Style & Naming Conventions
Target Python 3.12 with four-space indentation and snake_case modules/functions; reserve PascalCase for classes and keep Typer command names lowercase. Ruff enforces linting (line length 88, double quotes), so rely on `uv run ruff check .` and `uv run ruff format .` for consistency. Type hints are expected for new public APIs—validate with `uv run mypy codebase_rag` and finish with `pre-commit run --all-files` before pushing.

## Testing Guidelines
Pytest picks up `test_*.py` or `*_test.py` inside `codebase_rag/tests`, with classes beginning `Test` and functions `test_`. Cover parser edge cases plus CLI/Memgraph flows, but mark slow or networked tests so the default run remains fast. Execute `make test-parallel` before every PR and drop miniature fixtures under `codebase_rag/tests/data` when reproducing parsing issues.

## Commit & Pull Request Guidelines
Follow the Conventional Commit style already in history (`feat: …`, `fix: …`) and keep each commit focused on a single concern. PRs should link issues, summarize the modules touched, and list the validation commands you ran (`make test`, CLI repro). Include screenshots or logs when CLI UX changes and highlight risk areas so reviewers know where to look.

## Configuration & Security Tips
Copy `.env.example` to `.env`, set provider keys explicitly, and keep secrets out of version control. Ensure Memgraph matches the host/port passed to CLI flags or `make watch`, and confirm Ollama/cloud endpoints locally before launching RAG commands. Refresh Tree-sitter grammars with `git submodule update --init --recursive --depth 1` whenever parser code changes, and document any non-default ports, models, or env vars in your PR.
