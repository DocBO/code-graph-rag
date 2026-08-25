# Changelog

## [Unreleased]

### 📖 Clarify focused Qdrant embedding scope (2026-08-25)

**Status**: COMPLETED
**Scope**: Root README
**Verification**: Markdown review and `git diff --check`

#### Changes

- Documented that Qdrant embeds Python API names/docstrings and chunked Markdown, while Memgraph retains full source-structure coverage.

#### Migration / Operational Notes

- None.

### 🧾 Label Markdown matches by source path (2026-08-25)

**Status**: COMPLETED
**Scope**: Control-panel semantic-result header
**Verification**: Live `/api/semantic` query for `datenManagement_ldm`; control-panel production build

#### Changes

- Markdown `File` matches now use their returned source path as the primary header label instead of `unknown · File`.

#### Migration / Operational Notes

- None.

### 📍 Show semantic-result source files (2026-08-25)

**Status**: COMPLETED
**Scope**: Qdrant semantic-result metadata, MCP retrieval, control panel
**Verification**: 12 focused MCP/semantic-search tests passed; control-panel production build; Ruff check and formatting; `git diff --check`

#### Changes

- Semantic result cards now use the Qdrant-stored source path when graph location lookup cannot resolve a Markdown `File` node.

#### Migration / Operational Notes

- Existing Markdown vectors already contain their paths; no re-embedding is required.

### 🧭 Focus Qdrant embeddings on Python APIs and Markdown (2026-08-25)

**Status**: COMPLETED
**Scope**: Qdrant embedding generation and incremental updates
**Verification**: `uv run pytest tests/test_frontend_semantic_search.py codebase_rag/tests/test_semantic_search.py -v` (12 passed); Ruff check and formatting; `git diff --check`

#### Changes

- Qdrant now embeds Python class/function/method names with available docstrings and bounded Markdown chunks; Python bodies and non-Python assets are excluded. Memgraph ingestion is unchanged.

#### Migration / Operational Notes

- Regenerate embeddings with the existing `realtime_updater.py --only-embedding` action (or a full update) to replace vectors created by the previous strategy.

## 2026-08-21

### Control panel: MCP activity indicator (working vs stalled) ✅
- **MCP server logging** (`codebase_rag/mcp/server.py`) — HTTP transport middleware now emits explicit request lifecycle lines (`REQ <id> START ...` and `REQ <id> END status=... dur_ms=...`) so downstream tools can track real in-flight MCP work.
- **Backend status telemetry** (`control_panel/backend/main.py`) — MCP handle now tracks active request IDs, last request/response/activity timestamps, and exposes `activity` (`idle` / `busy` / `stalled` plus process-state fallbacks) in `/api/status`.
- **Frontend visibility** (`control_panel/frontend/src/App.tsx`, `control_panel/frontend/src/App.css`, `control_panel/frontend/src/types.ts`) — MCP card now shows an activity badge (`WORKING`, `IDLE`, `STALLED`, etc.), active request count, and "last MCP work" age so heavy processing vs likely stalls is visible while agents run.
- **Control panel docs** (`control_panel/README.md`) — usage/API sections now describe the new MCP activity telemetry fields and dashboard indicator semantics.

### Root README: control-center overview ✅
- Replaced the upstream-scale technical overview and embedded film link with a
  concise guide to this fork's control panel, real-time watchers, unified MCP
  endpoint, Qdrant semantic database, and local startup workflow.
- Added explicit attribution and links to the upstream Graph-Code RAG repository
  for parser, graph, CLI, language-support, and core implementation details.

## 2026-08-12

### Control panel: live-updating log tails ✅
- **Frontend** (`control_panel/frontend/src/App.tsx`) — opened repo/MCP log panels now poll their `/logs` endpoints every 2s (`refreshOpenLogs`), so the displayed tail stays current instead of freezing at the moment the panel was opened. Auto-scroll now only pins to the bottom while the user is already at the bottom (`stickToBottom` tracked via `onScroll`), so polling never yanks the viewport away while the user scrolls back through history.

### Control panel: global "Stop all" action ✅
- **Frontend** (`control_panel/frontend/src/App.tsx`, `api.ts`, `App.css`) — a red **Stop all** button in the topbar stops every process. It asks for confirmation, disables itself with a `Stopping…` label, and calls the new `/api/shutdown` endpoint. Styled with a new `.btn-stopall` class (red accent).
- **Backend** (`control_panel/backend/main.py`) — `RepoManager.stop_all()` stops all registered watchers, any running embedding-only jobs, and the MCP server. New `POST /api/shutdown` endpoint runs it, then terminates the control panel API process itself (SIGTERM after a 1s delay so the HTTP response is flushed first). Returns a summary: `{watchers, embeddings, mcp, api}`.
- **Docs** — `control_panel/README.md` API table + description.

### Control panel: "Only embeddings" action button on the watcher tile ✅
- **Frontend** (`control_panel/frontend/src/App.tsx`, `api.ts`, `types.ts`) — the repo card now has an **Only embeddings** button (violet accent) that regenerates all semantic embeddings without file ingestion. While it runs the button shows `Embedding…` and is disabled; the tile badge shows `UPDATING` (Pass 4 start/end log lines are now parsed by the backend update classifier).
- **Backend** (`control_panel/backend/main.py`) — new `POST /api/repos/{path}/embedding` endpoint backed by `RepoManager.start_embedding_only()`: spawns `realtime_updater.py --only-embedding` as a tracked subprocess with log streaming into the repo's watcher log tail, and exposes `embedding_in_progress` in the watcher status payload. Rejects with 409 if a regeneration is already running.
- **CLI** (`realtime_updater.py`) — new `--only-embedding` flag: one-shot mode that cleans the Qdrant collection and runs Pass 4 (`GraphUpdater._generate_semantic_embeddings`) from the existing graph, then exits (no file watching).
- **Docs** — `control_panel/README.md` API table + description.

### Embedder rate limiter + 429 retry (watcher Pass 4) ✅
- **Root cause** — `_embed_external_batch` POSTed without throttling; a 429 from the external embedder raised `EmbeddingError` and Pass 4 discarded the entire 200-item chunk (`[Pass 4] Failed chunk at ...`), leaving the semantic database with only a subset of the code.
- **Shared token-bucket rate limiter** (`codebase_rag/embedder.py`) — `EmbedRateLimiter` spaces external embedder requests to `EMBED_RATE_LIMIT_RPM` (default 60/min, i.e. 1 request/second), shared across watcher Pass 4, MCP `start_updater`, CLI `--only-embedding`, and agent tools so parallel paths never flood the endpoint.
- **429/5xx retry with backoff** — transient 429/500/502/503/504 responses are retried up to `EMBED_MAX_RETRIES` (default 3) using the server's `Retry-After` header when present, else exponential backoff from `EMBED_RETRY_BACKOFF` (default 2.0s). A 429 that exhausts retries now raises a dedicated "rate limit exceeded" error instead of a generic one.
- **Per-item fallback in Pass 4** (`codebase_rag/graph_updater.py`) — if a batch embed still fails, the chunk is re-embedded item-by-item so only genuinely failing items are skipped instead of the whole chunk; per-item failures are logged and the remaining embeddings are still stored.
- **Config** — new `EMBED_RATE_LIMIT_RPM`, `EMBED_MAX_RETRIES`, `EMBED_RETRY_BACKOFF` settings (`codebase_rag/config.py`), documented in `.env.example`.
- **Tests** — `codebase_rag/tests/test_embedder.py`: limiter spacing/throttle, `Retry-After` parsing (seconds + HTTP-date), success path, 429→retry→success, and 429 retry exhaustion raising `EmbeddingError`. 8 passed.

## 2026-08-11

### MCP Compatibility: `query_codegraph` Alias + HTTP Error Mitigation ✅
- **Added `query_codegraph` MCP alias tool** — forwards to `query_codebase` with identical schema (`question`, optional `repo_path`, optional `search_depth`) and response contract.
- **Why** — some clients requested `query_codegraph` and failed at runtime; alias support avoids hard failures from legacy/typo tool naming.
- **Observed runtime condition** — control panel status showed MCP HTTP endpoint unavailable (`state=error`, `adopted process exited unexpectedly`, `127.0.0.1:8765` connection refused), which can independently surface as HTTP MCP errors.

### Control Panel: Query Depth Qualifier in Dashboard ✅
- **Added depth selector to Query Codebase card** — dashboard query UI now includes `search_depth` (`shallow`/`normal`/`deep`) and forwards it to backend `/api/query`.
- **Backend `/api/query` accepts depth qualifier** — `QueryRequest` now supports `search_depth` (default `normal`) and passes it to `GraphCodeMCPContext.query_codebase`.
- **Response parity** — `/api/query` now returns the effective `search_depth` along with `repo_path`, `question`, and `response`.
- **Docs updated** — `control_panel/README.md` usage/API section documents the new dashboard depth qualifier.

### MCP: Agent Search Depth for `query_codebase` ✅
- **Added `search_depth` parameter** to `query_codebase` with three modes: `shallow`, `normal` (default), and `deep`.
- **Depth-aware agent execution** — MCP now injects an explicit retrieval-depth directive into the read-only agent run so clients can tune speed vs. thoroughness.
- **Response contract extended** — `query_codebase` responses now include the effective `search_depth` used for the run.
- **Validation** — invalid values are rejected with a clear error listing allowed modes.
- **Tests/docs updated** — MCP schema/dispatch tests now cover `search_depth`; `docs/mcp-tools.md` updated with parameter and return fields.

### IMPROVEMENT_MCP items 1-4, 6-8 (all remaining, item 5 dismissed) ✅
- **Item 1 — Read-only agent for `query_codebase`** — `initialize_services_and_agent(..., read_only=True)` excludes the mutation-capable tools (`file_writer`, `file_editor`, `shell_command`) and uses the new `RAG_READ_ONLY_SYSTEM_PROMPT`; `query_codebase` now runs read-only while `optimize_code` and the CLI loops keep the full tool set.
- **Item 2 — Explicit tool-selection rules** — both orchestrator prompts now carry a `TOOL SELECTION RULES` block: graph tool for structural facts, semantic tools for intent discovery, `get_source_by_id`/file readers after semantic matches, and graph follow-up via qualified names/IDs.
- **Item 3 — Prompt tool-name alignment** — replaced the stale `semantic_code_search` references with the actual registered tool names (`semantic_search_by_intent`, `semantic_search_functions`, `get_source_by_id`).
- **Item 4 — Evidence-backed answers** — prompts now require a source reference (repo-relative path, qualified symbol, line range) for every implementation claim and forbid inferring behavior from names/scores alone.
- **Item 6 — Structured MCP response** — `query_codebase` now returns `sources[]` (qualified_name/filename/start_line/end_line, deduplicated from `GraphData` rows and `CodeSnippet` returns) plus a `retrieval` block (`used_graph`, `used_semantic_search`, `index_status` fresh/stale/no_metadata); output schema updated.
- **Item 7 — Semantic-search failures distinguishable** — new `SemanticSearchOutcome` (`status` in `ok`/`no_match`/`no_dependencies`/`failed`, `matches`, `message`) exposed via `semantic_code_search_outcome[_async]`; the old list-returning functions still work. `semantic_search_functions` and `semantic_search_by_intent` now report the actual failure condition instead of a generic "no matches". Prompts tell the model to report no-match vs infra failure distinctly.
- **Item 8 — Bounded Cypher traversal & LIMITs** — both Cypher prompts now mandate a `LIMIT` on every query, forbid unbounded variable-length paths (`[*]`, `[*0..]`), and require bounded depths (`[*..3]`) unless arbitrary reachability is explicitly requested.
- **Tests** — new `codebase_rag/tests/test_runtime.py` (read-only vs full tool sets, read-only prompt), `codebase_rag/tests/test_semantic_search.py` (outcome statuses), plus updated `test_mcp_server.py` (schema, response contract, metadata extraction, read_only flag).

### Prompt/Docs Alignment Follow-up ✅
- **Prompt retrieval-rule consistency** — adjusted both orchestrator prompts so semantic-first guidance applies to intent questions without concrete symbol/file names, matching the explicit tool-selection rules for structural graph queries.
- **Prompt tool-name cleanup** — replaced stale `edit_existing_file` mention with the actual modifying tool `replace_code_surgically`.
- **IMPROVEMENT_MCP contract update** — updated the early `query_codebase` response example and response-contract section text to reflect the implemented `sources[]` and `retrieval` fields.

## 2026-08-09

### Control Panel: Quick Semantic Retrieval Debug Panel ✅
- **Added `/api/semantic` backend endpoint** — runs the same `GraphCodeMCPContext.quick_semantic_retrieval` flow used by the MCP tool against a registered repo, returning `{repo_path, search_phrase, top_n, matches[]}` with `qualified_name`, `type`, `score`, `filename`, `start_line`, `end_line`, and `snippet`.
- **Added Quick Semantic Retrieval debug card to the UI** — a dedicated panel (repo selector, search phrase, top-N input) that renders raw vector matches with similarity scores and expandable code snippets. Matches at score ≥ 0.4 are highlighted green, so an empty/weak result is immediately visible when debugging why a phrase returns few or no matches.
- **Verified** — `/api/semantic` returns SkillExecutor match (score 0.462) against elysia; frontend `tsc && vite build` clean; dev server transforms the updated `App.tsx`.

### Control Panel: Live Memgraph Health Check ✅
- **Added live Memgraph liveness probe** — backend `/api/status` now returns a `memgraph` object (`{at, alive, error}`) computed from a short TCP connect to the Bolt port (`MEMGRAPH_HOST:MEMGRAPH_PORT`), cached for ~2s so the polling dashboard stays cheap.
- **UI-visible indicator** — the topbar MEMGRAPH chip now shows a status lamp plus `ALIVE`/`DOWN` text; the chip and state turn red when Memgraph is unreachable, and a `chip-mg-err` style highlights the failure. This surfaces the exact failure mode (e.g. Memgraph OOM-killed) that previously only manifested as slow/empty `query_codebase` and `quick_semantic_retrieval` responses.
- **Fast & safe** — uses a raw socket probe with a 2s timeout rather than the full Bolt driver, so the status endpoint never blocks and reflects real reachability.
- **Verified** — backend `/api/status` returns `alive: true` when Memgraph is up and `alive: false` (`Connection refused`) against a closed port; frontend `tsc && vite build` clean.

### Fix: `changes.total` stays stale after autoupdate / UI full scan ✅
- **Fixed `ingest_status` reporting stale changes after updates** — `realtime_updater.py` never refreshed `.graphcode_ingest.json` after a successful incremental autoupdate or the initial/UI-triggered full scan (`GraphUpdater.run()` does not write metadata itself; only the CLI `update-graph` and MCP `start_updater` did).
- **Root cause** — `summarize_ingest_status` computes `changes.total` by diffing the current file index against the stored metadata. Because metadata was never refreshed on these paths, `changes.total` stayed > 0 even after the graph was current, so `ingest_status`/`start_updater` kept reporting a stale index.
- **Fix** — `write_ingest_metadata` is now called after a successful incremental update in `_process_pending_changes` and after the initial full scan in `start_watcher` (covering CLI startup and UI-triggered full updates).
- **Test added** — verifies a successful incremental update refreshes ingest metadata; patched `write_ingest_metadata` across `test_realtime_updater.py` so tests never touch the real repo.

### MCP Tool: `start_updater` ✅
- **Added `start_updater` MCP tool** — runs a one-shot full graph update for a repo so agents can re-sync the knowledge graph when `ingest_status` reports a stale index.
- **Stale-aware** — checks ingest metadata via `summarize_ingest_status`; if there are no pending changes and `force` is false, it returns `started=false` with reason `index_fresh` and performs no update. Otherwise it runs `GraphUpdater.run()` (same path as the CLI `update-graph` command) and refreshes ingest metadata on success.
- **Parameters** — optional `repo_path` (defaults to the server's configured repo) and `force` (boolean, default `false`).
- **Returns** — `repo_path`, `started`, `reason` (`stale`/`forced`/`index_fresh`), `last_ingest`, `changes` (added/deleted/modified/total), `metadata_path`.
- **Docs & tests** — documented in `docs/mcp-tools.md` section 6; added tests covering tool registration, dispatch, fresh-index skip, and stale-index run.

## 2026-08-08

### Markdown Renderer Fix: Overlapping List Markers ✅
- **Fixed overlapping `<ol>` markers** — `renderListItem` already emits a `<li>`, but `renderBlocks` wrapped it in a second `<li>`, producing nested `<li>` (invalid HTML). Browsers then drew duplicate markers at the same position (e.g. "1" overlapping "2"). List items are now wrapped in `Fragment` instead.
- **Verified** — `tsc && vite build` clean; rendered list HTML has flat `<li>` elements with correct sequential numbers.

### Markdown Renderer Fix: Bullet Undefined Crash ✅
- **Fixed runtime crash** — `UL_RE` had only one capture group, so `parseList` read `m[2]` as `undefined` for bullet items and `renderInline` crashed with `Cannot read properties of undefined (reading 'length')`. Both `UL_RE` and `OL_RE` now capture marker + content as two groups.
- **Verified** — bullets, nested bullet continuations, and numbered lists all parse with defined content; `tsc && vite build` clean.

### Markdown Renderer Fix: Ordered Lists ✅
- **Fixed ordered-list rendering** — consecutive numbered items (with indented continuation lines and nested bullets) are now grouped into a single `<ol>` with the correct `start` number, instead of each item becoming its own list that renumbered everything to `1.`.
- **Robust list parsing** — `parseList` consumes indented continuation lines (even after blank lines) into the owning item, keeps nested `-`/`*` bullets, and stops at headings/code fences; trailing paragraphs after a list are no longer absorbed.
- **Verified** — parser unit-tested against the "How moved files are handled" example: items 1-3 render as one list with correct numbers, nested bullets preserved, trailing paragraph separate.

### Control Panel: RAG Query Card ✅
- **Added Query Codebase (RAG) card to the dashboard** — separate card with a repo selector, question textarea, and *Run query* button; results are rendered as markdown (headings, lists, inline code, code fences, links) with a **Copy** button.
- **Backend `/api/query` endpoint** — runs the `query_codebase` RAG flow (`GraphCodeMCPContext.query_codebase`) against a registered repo and returns the agent's markdown answer; backend now adds the project root to `sys.path` so `codebase_rag` is importable from `control_panel/backend`.
- **Lightweight dependency-free markdown renderer** (`Markdown.tsx`) — headings, paragraphs, ul/ol, inline `code`/`**bold**`/`*italic*`/links, and fenced code blocks with language label.
- **Verified** — frontend `tsc && vite build` clean; `/api/query` returns markdown answers for the elysia repo (via direct API and through the Vite proxy).

### MCP Tool: `get_watched_repos` ✅
- **Added `get_watched_repos` MCP tool** — returns which repositories are registered with the control panel and whether each has an active real-time watcher running, so agents can quickly check if their repo is being watched or is stopped.
- **Primary source: control panel** — queries `GET {CONTROL_PANEL_URL}/api/status` (new `CONTROL_PANEL_URL` setting, default `http://127.0.0.1:8008`) and returns per-repo `watcher_state`, `watcher_pid`, `update_in_progress`, `last_update_at`, plus `watched_paths`.
- **`/proc` fallback** — when the control panel is unreachable, scans `/proc` for live `realtime_updater.py` processes (deduplicated per repo, one entry per `uv run` wrapper + python child pair) so agents still get a running/stopped answer.
- **Docs updated** — `docs/mcp-tools.md` section 5; verified tool is listed by the live MCP server (`get_status`, `ingest_status`, `query_codebase`, `quick_semantic_retrieval`, `get_watched_repos`).

### Quick Test Subset: `make test-quick` Target ✅
- **Added `test-quick` Makefile target** — runs only the system/core, Python, and TypeScript tests, skipping all other language suites (JavaScript, Rust, Go, Scala, Java, C++, Lua) for a fast feedback loop.
- **Selection** — collects `codebase_rag/tests/test_*.py` excluding `test_<language>_` prefixes and the Rust language file `test_rust.py`.
- **Verified** — 413 passed, 1 skipped in ~56s.

### Watcher Conflict Fix: Duplicate-Watcher Dedup + Transaction-Conflict Retry ✅
- **Root cause identified** — `uvicorn --reload` re-imports the control panel backend on every reload, re-creating `RepoManager` and losing the handle to still-running `realtime_updater.py` subprocesses. The dashboard then showed them as stopped; clicking Start spawned a *second* watcher for the same repo, so two processes wrote the same files concurrently and Memgraph aborted one with `Cannot resolve conflicting transactions` (seen as `Graph update failed... retrying after debounce`).
- **Backend reconciles orphaned processes on startup** (`_adopt_running_processes`) — after a reload the backend finds live watcher/MCP process groups (via `/proc` pgrep grouped by process-group id), stops stale duplicates, and **re-spawns watchers it cannot track** (stdout pipe belonged to the dead instance) so update-progress tracking keeps working. MCP server is adopted directly (stateless).
- **Start endpoints refuse duplicates** — `POST /api/repos/{path}/watch/start` and `/api/mcp/start` detect a live leftover process for the same repo/port and stop duplicates + adopt the newest instead of spawning a second writer.
- **Memgraph transaction-conflict retry** — `graph_service._execute_query/_execute_batch/_execute_batch_with_return` now retry `Cannot resolve conflicting transactions` (3 attempts, backoff) instead of only connection errors.
- **Visible tracebacks** — `realtime_updater.py` log format now includes `{exception}` so failed updates show the full cause instead of only the summary line.
- **Verified** — 915 tests pass; watcher lifecycle (start→running→stop, adopted stop, restart after reload) and both repos' updates complete with no conflicts.

### Control Panel: Watcher Dashboard + Unified MCP Manager ✅
- **Added `control_panel/` full-stack stack** — FastAPI backend (`:8008`) + React/Vite dashboard (`:3003`) for managing Graph-Code RAG watchers and the unified MCP server.
- **Runs in the project's uv environment** — `fastapi` and `uvicorn[standard]` added to `pyproject.toml`; backend is launched with `uv run uvicorn main:app` (no separate backend venv).
- **Persisted repo registry** — `POST /api/repos` adds an absolute repo path (with debounce, batch size, `--no-update` toggle), persisted to `backend/data/repos.json`; DELETE deregisters and stops any running watcher.
- **Per-repo watcher lifecycle** — Start/stop spawns `realtime_updater.py` subprocesses (`uv run`) with process-group SIGINT/SIGKILL cleanup; "Start + full scan" omits `--no-update` to run the initial ingestion. Start/stop responses now always reflect the registered watcher handle.
- **Update-in-progress detection** — Watcher log lines are parsed (`Starting graph update` / `Graph update completed` / `Initial scan complete`) to drive `update_in_progress`, last-update timestamp, duration, and error state in the API.
- **Unified MCP server** — One HTTP MCP instance (`:8765/mcp`) serves all registered repos since tools accept `repo_path` per call; start/stop/status/log endpoints plus default-repo selection in the UI.
- **Fixed subprocess monitor race** — `_start_monitor` now spawns a real daemon thread instead of blocking `proc.wait()` in the request handler, eliminating the `AttributeError: 'NoneType' object has no attribute 'start'` crash after an MCP server exit.
- **Dashboard status lamps** — Green = watcher active, pulsing amber = update running, red = error; per-repo log viewer, MCP log viewer, and 2.5s status polling.
- **Smoke-tested** — Repo add/list/start(no-update)/full-scan-start/stop/delete, repeated MCP start→running→stop cycles, frontend `tsc && vite build` clean, backend ruff clean.

### Regression Fixes — Graph Ingestion and Test Stability (2026-08-08)

**Status**: COMPLETED
**Scope**: config.py, graph_updater.py, structure_processor.py, tests/conftest.py, test_graph_service_calls_failure_logging.py
**Verification**: `uv run pytest` 915 passed, 0 failed

#### Changes

- Removed `"tests"` from `BASE_IGNORE_PATTERNS` in config.py — legitimate test packages in analyzed repos were being excluded unconditionally
- Removed blanket dotfile/dotfolder exclusion (`part.startswith(".")`) from both `graph_updater.py` and `structure_processor.py` — `.gitignore`, `.env`, `.github/` and similar project artifacts are now tracked correctly
- Added autouse conftest fixture to reset `IGNORE_PATTERNS` across all test modules referencing it (`from X import IGNORE_PATTERNS` binding fix)
- Fixed `test_calls_failure_logging_multiple_batches`: added `extra_params` parameter to mock to match new `_execute_batch_with_return` signature
- Fixed `test_calls_failure_logging_single_batch`: removed stale sample-logging assertion no longer present in production code

#### Migration / Operational Notes

- `INGEST_IGNORE_DIRS` in `.env` contained filenames (`.gitignore`, `.env`, `uv.lock`) and loose directory names (`docs`, `assets`) that shouldn't be ignore patterns; review and prune to only directory names that should be excluded from scanning.


### Unit Test Coverage Expansion (2026-08-08)

**Status**: COMPLETED
**Scope**: tests/
**Verification**: `uv run pytest` 167 passed, 1 skipped (0 failures), `uv run ruff check` clean

#### Changes

- Added 12 new test files (167 tests) targeting previously untested core modules
- `test_schemas.py` (10 tests) — `GraphData`, `CodeSnippet`, `ShellCommandResult` validation, coercion, defaults
- `test_config.py` (18 tests) — `ModelConfig`, `_parse_ignore_dirs`, `parse_model_string`, `resolve_batch_size`, default fallback
- `test_prompts.py` (16 tests) — schema completeness, required node labels/relationships, cypher prompt constraints, strategy directives
- `test_language_config.py` (15 tests) — Python/TypeScript `FQNConfig` name extraction, file-to-module conversion, `get_language_config` lookup
- `test_llm_service.py` (10 tests) — `_clean_cypher_response` edge cases (markdown, semicolons, backticks, whitespace), `LLMGenerationError`, `create_context_synthesizer`
- `test_fqn_resolver.py` (10 tests) — `resolve_fqn_from_ast` with real tree-sitter ASTs for Python (class methods, nested classes, top-level) and TypeScript (namespaces, methods, top-level), `find_function_source_by_fqn`, `extract_function_fqns`
- `test_source_extraction.py` (15 tests) — `extract_source_lines` (relative paths, invalid ranges, missing files), `validate_source_location`, `extract_source_with_fallback`
- `test_dependencies.py` (13 tests) — `_check_dependency` caching, `check_dependencies`, `get_missing_dependencies`, convenience functions
- `test_code_retrieval.py` (6 tests) — `CodeRetriever.find_code_snippet` (not-found, partial data, source extraction, exceptions), tool factory
- `test_shell_command.py` (25 tests) — `_is_dangerous_command`, `_requires_confirmation` for all categories, allowlist validation, `ShellCommander.execute` (allowlist, confirmation, real subprocess via `echo`/`pwd`/`ls`)
- `test_file_reader.py` (9 tests) — `FileReader.read_file` (traversal prevention, symlink guard, binary extension blocking), `FileReadResult`
- `test_file_writer.py` (8 tests) — `FileWriter.create_file` (parent dirs, overwrite, traversal prevention, empty content), `FileCreationResult`

#### Migration / Operational Notes

- None.


### Realtime Graph-Qdrant File Correlation ✅
- **Added file-scoped Qdrant cleanup before re-embedding** - Realtime embedding refresh now removes existing vectors for changed files first, then regenerates current chunks to prevent stale vectors after edits, deletions, and chunk-count shrink.
- **Persisted source file metadata per chunk** - Embedding payloads now include `file_path`, enabling exact correlation between repository files and vector points.
- **Added Qdrant delete helper for local + HTTP backends** - Introduced a shared deletion path that removes vectors by `file_path` filter in both client and HTTP modes.
- **Fixed rename/move update coverage in watcher** - File move events now queue both source and destination paths, so old-file vectors are pruned and new-file vectors are regenerated in the same debounce cycle.
- **Expanded realtime updater regression tests** - Added assertions for embedding refresh across create/modify/delete/unsupported flows and a dedicated move-event test for source+destination correlation.

### MCP Semantic Snippet Retrieval ⚡
- **Added `quick_semantic_retrieval` MCP tool** - New semantic-only retrieval path for fast snippet lookup without full agent orchestration.
- **Snippet-focused response contract** - Tool now returns semantic matches with snippet text, filename, and start/end line metadata when available.
- **Chunk-preserving retrieval output** - `quick_semantic_retrieval` now returns matched semantic chunks (or chunk-sized fallback slices) instead of full class/function bodies.
- **Consistent repository context in MCP responses** - All MCP tool responses now include `repo_path` to make active repository context explicit for clients.
- **MCP tooling docs updated** - README and MCP documentation now include usage and schema-level behavior for quick semantic retrieval.

## 2026-08-07

### Realtime Watcher Stability & MCP Startup Wiring 🔧
- **Fixed watcher crash on dropped Memgraph sessions** - The realtime debounce worker now recovers from missing/closed connections by auto-reconnecting instead of terminating with `ConnectionError: Not connected to Memgraph`.
- **Hardened debounce processing loop** - Real-time change processing now keeps queued files on failure and retries after the debounce interval, preventing silent loss of incremental updates.
- **Thread-safe pending change handling** - Added synchronized access for queued file changes to avoid race conditions between watchdog event dispatch and debounce processing.
- **Startup argument wiring cleanup** - Unified startup now separates Memgraph connection args from MCP HTTP transport args to avoid ambiguous `--host/--port` forwarding in HTTP mode.
- **Added explicit wiring diagnostics** - Launcher, updater, and MCP startup now print effective Memgraph endpoint and MCP transport targets to make configuration mismatches immediately visible in logs.

## 2026-01-19

- **Added Collection Cleanup Utility** - Created `utils/delete_all_collections.py` to quickly remove all repository-specific vector collections from Qdrant, facilitating easier troubleshooting of dimension mismatches.

## 2026-01-14

### Iterative Retrieval & Deep Context Awareness 🧠
- **Implemented Iterative Semantic Seed Strategy** - Added an automated retry loop (up to 3 rounds) that uses the LLM to identify "Missing Concepts" when context is insufficient, triggering recursive searches to fill knowledge gaps.
- **Expanded Semantic Coverage to Classes** - Pass 4 ingestion now includes `Class` nodes in the vector database, allowing the RAG engine to find high-level architectural components via natural language.
- **Optimized Nested Symbol Resolution** - Integrated variable-length Cypher paths (`-[:DEFINES|CONTAINS*..5]->`) into retrieval queries to correctly locate source files for methods or classes nested deeply within modules.
- **Restored Search Visibility** - Re-introduced detailed telemetry for keyword-based seed discovery and graph expansion counts, providing clear logs for how the iterative rounds traverse the codebase.
- **Configurable Retrieval Depth** - Exposed `max_retries` as a parameter in the `query_codebase` MCP tool to allow users to control the trade-off between search depth and latency.

## 2026-01-09

### Type Inference Recursion & Phase 4 Optimization 🔧
- **Fixed Infinite Recursion in Type Inference** - Implemented a `visited` set guard in `TypeInferenceEngine` to prevent infinite loops during self-assignment analysis (e.g., `x = self.x()`).
- **Restored & Optimized Phase 4 (Semantic Embeddings)** - Re-enabled and optimized semantic embedding generation using batch processing for both Local and Cloud providers, significantly reducing ingestion time.
- **Enhanced Ingestion Memory Efficiency** - Introduced module-level instance variable caching and batch upserts to Qdrant to handle large repositories like `addibase` without OOM.
- **Cleaned Debug Instrumentation** - Removed verbose log statements and manual flushing added during the hang investigation for cleaner production output.
- **Strict Repository Isolation** - Standardized `repo_path` resolution using absolute paths with home expansion (`~`) and enforced `_repo_path` filtering across all Memgraph queries. Updated LLM prompts with mandatory isolation rules and automated parameter injection in the database driver.

### Connection & Hangs Fixed 🔧
- **Fixed cursor iteration hang** - Replaced `cursor.fetchall()` with `cursor.fetchone()` loop in all query execution methods (`_execute_query`, `_execute_batch_with_return`, `execute_read_query`) to prevent memory issues and timeouts with large result sets.
- **Fixed connection close hang** - Added 5-second timeout to `conn.close()` in `__exit__()` to prevent indefinite hangs when Memgraph is slow to finalize connections on large repositories.
- **Disabled batch embedding generation** - Batch embedding generation at ingestion time causes hangs on large repositories with thousands of functions. Embeddings are now generated on-demand during semantic search queries instead, improving initial ingestion performance.
- **Enhanced logging** - Added detailed logging throughout graph flushing, relationship processing, and embedding generation phases with stdout/stderr flushing to help identify bottlenecks.

## 2025-12-29

### Semantic Search & Qdrant Consistency Fix 🔍
- **Keyword Fallback for Semantic Seed Strategy** - Added a keyword-based seed discovery to `/semantic-seed-strategy`. If semantic search fails to find relevant nodes (e.g., due to stale embeddings), the strategy now looks for capitalized words in the question and finds matching nodes by name in Memgraph.
- **Fixed `/semantic-seed-strategy` inconsistency** - Resolved issues where semantic search would fail due to missing collections or path mismatches.
- **Automatic Collection Creation** - Qdrant collections are now automatically created on-demand during search if they don't exist.
- **Path Normalization** - Added `.expanduser()` to path resolution to handle `~` in repository paths consistently across ingestion and search.
- **Settings Synchronization** - The `settings.TARGET_REPO_PATH` is now explicitly updated during initialization to ensure all services use the same repository context.
- **Improved Error Resilience** - Added `_ensure_collection_exists()` helper to `vector_store.py` to prevent crashes when searching new repositories.

### Graph Ingestion & Relationship Fixes 🕸️
- **Expanded File Exclusion** - Added `.md` and `.txt` files to the global ignore list. These files are now skipped during both initial ingestion and real-time updates to focus exclusively on code structure.
- **Dotfile and Dotfolder Exclusion** - Updated `realtime_updater.py`, `graph_updater.py`, and `structure_processor.py` to ignore any files or directories starting with a dot (e.g., `.git`, `.vscode`, `.gitignore.swp`). This prevents noise from hidden files and temporary editor files from triggering unnecessary graph updates.
- **Real-time Semantic Updates** - `realtime_updater.py` now updates semantic embeddings in Qdrant for changed files, ensuring that `/semantic-seed-strategy` and other semantic tools stay in sync with code changes without requiring a full database refill.
- **Event Filtering in Real-time Updater** - `realtime_updater.py` now filters out non-modifying events like `closed_no_write` and ignores binary/media files (images, audio, etc.) as well as database journal files (`.db-journal`, `.sqlite-wal`, etc.) to reduce noise and redundant processing.
- **Configurable Debouncing** - Added `--debounce` CLI argument to `realtime_updater.py` to allow custom buffering delays (defaults to 20 seconds).
- **Fixed `realtime_updater.py` Debouncing** - Added 20-second buffering for file changes to prevent race conditions and redundant processing.
- **Improved Real-time Consistency** - `realtime_updater.py` now re-runs structure identification and definition processing before recalculating function calls, resolving "nodes may not exist" warnings for `CALLS` relationships.
- **Fixed CALLS relationship failures** - Resolved "nodes may not exist" warnings during ingestion by ensuring consistent repository isolation.
- **Fixed Unique Constraint Violations** - Resolved `mgclient.DatabaseError: Unable to commit due to unique constraint violation on :Project(name)` in `realtime_updater.py` and MCP server.
- **Absolute Path Normalization** - Standardized `MemgraphIngestor` to always resolve `repo_path` to an absolute path, ensuring consistent repository isolation.
- **Repo-Aware Real-time Updater** - Updated `realtime_updater.py` to use repository-specific filters for all deletion and re-calculation queries.
- **Repo-Aware Database Operations** - Updated `clean_database` and `export_graph_to_dict` in `graph_service.py` to respect repository isolation.
- **Built-in Node Creation** - Added automatic creation of nodes for built-in functions (e.g., `setTimeout`) when they are called.

### MCP Server Improvements 🔌
- **Improved Edit Confirmation Prompt** - The post-edit confirmation prompt now explicitly lists the files that were modified, created, or updated, providing better context for the user's decision.
- **Refined Edit Detection** - Updated `is_edit_operation_request` to use word boundaries, preventing false positives from class names like `ListEditor`.
- **Fixed `query_codebase` default strategy** - The `query_codebase` MCP tool now correctly uses `semantic-seed-strategy` by default.
- **Direct Strategy Execution** - Updated MCP server to call `run_semantic_seed_strategy` directly instead of passing slash commands to the agent.
- **Improved MCP Schema** - Added explicit default value for `strategy` in the MCP tool definition.

## 2025-11-30

### Connection Pool & Hang Fix - Read-Only Query Helper 🔌
- **Fixed 16-second hang after semantic search** - Eliminated connection pool exhaustion
  - Previous issue: semantic_search created its own MemgraphIngestor with `with` context
  - When context exited, connection closed, leaving main ingestor in broken state
  - Next query would hang trying to use dead connection
  
- **Added `execute_read_query()` helper** for lightweight read-only operations
  - Simple function in `graph_service.py` for queries that don't need ingestion machinery
  - Creates temporary connection, executes query immediately, closes cleanly
  - No buffering, no context managers, no side effects
  - Includes proper error handling and logging for Cypher syntax errors
  
- **Refactored semantic_search.py**
  - `semantic_code_search()` now uses `execute_read_query()` instead of MemgraphIngestor
  - `semantic_code_search_async()` now uses `execute_read_query()` instead of MemgraphIngestor
  - `get_function_source_code()` now uses `execute_read_query()` instead of MemgraphIngestor
  - All functions maintain repo_path filtering and parameter passing
  
- **Result**: No more connection conflicts, queries execute immediately without hanging

### Changes
- Modified `codebase_rag/services/graph_service.py`
  - Added `execute_read_query()` function for simple read-only Cypher queries
  - Returns list of result dictionaries (same format as MemgraphIngestor)
  - Includes error detection for Cypher syntax issues
  
- Rewrote `codebase_rag/tools/semantic_search.py`
  - Removed all `with MemgraphIngestor(...)` context managers
  - Updated both sync and async versions to use `execute_read_query()`
  - Simplified code and eliminated connection management complexity

### Robust Cypher Query Generation & Error Handling 🛡️
- **Fixed LLM-Generated Query Syntax Errors** - Made system resilient to LLM producing invalid Cypher
  - Fixed critical bug: `_clean_cypher_response()` was **adding** semicolons (Cypher doesn't support them!)
  - Now properly **removes** trailing semicolons from LLM output (common SQL carryover from training data)
  - Validates cleaned queries start with MATCH clause
  - Additional semicolon removal as safety net during validation
  
- **Improved Error Messages**
  - `_execute_query()` detects syntax errors and provides helpful hints
  - Query tool returns user-friendly error messages suggesting rephrasing
  - Logs helpful guidance about Cypher syntax when errors occur
  
- **Enhanced System Prompts**
  - Explicitly states "**NO SEMICOLONS**" at the top of both prompts
  - All code examples show queries without semicolons
  - Emphasizes Cypher syntax differences from SQL
  - Critical rules moved to the beginning
  
- **Edge Case Handling**
  - Handles markdown code blocks (``​` cypher ... ``​`)
  - Strips 'cypher' keyword if present
  - Removes backticks and other formatting artifacts
  - Graceful degradation when LLM generates slightly malformed queries

### Changes
- Modified `codebase_rag/services/llm.py`
  - Rewrote `_clean_cypher_response()` to remove (not add) semicolons
  - Enhanced `CypherGenerator.generate()` with validation and error handling
  
- Modified `codebase_rag/services/graph_service.py`
  - Updated `_execute_query()` to detect and explain Cypher syntax errors
  
- Modified `codebase_rag/tools/codebase_query.py`
  - Enhanced error handling with helpful messages for users
  
- Modified `codebase_rag/prompts.py`
  - Updated both CYPHER_SYSTEM_PROMPT and LOCAL_CYPHER_SYSTEM_PROMPT
  - Added explicit "NO SEMICOLONS" warning
  - Updated all examples to be semicolon-free

### Relative Path Resolution in Source Extraction 📂
- **Fixed Embedding Generation Failures** - Resolved relative paths during source code extraction
  - `extract_source_lines()` now accepts optional `repo_path` parameter
  - Automatically resolves relative paths (e.g., "arc_agi/io.py") to absolute using repo root
  - `extract_source_with_fallback()` propagates repo_path through to line-based extraction
  - `validate_source_location()` also supports path resolution
  - Updated `_extract_source_code()` in graph_updater to pass repo_path
  - Updated semantic_search tools to pass repo_path when extracting sources

- Fixes "Source file not found" warnings that occurred during embedding generation
- Enables successful completion of Pass 4 (embedding generation) for all functions

### Changes
- Modified `codebase_rag/utils/source_extraction.py`
  - Added `repo_path` parameter to `extract_source_lines()`
  - Added `repo_path` parameter to `extract_source_with_fallback()`
  - Added `repo_path` parameter to `validate_source_location()`
  - Implemented logic: `if not file_path.is_absolute() and repo_path: resolved_path = Path(repo_path) / file_path`

- Modified `codebase_rag/graph_updater.py`
  - Updated `_extract_source_code()` call to `extract_source_with_fallback()` with `repo_path=self.repo_path`

- Modified `codebase_rag/tools/semantic_search.py`
  - Updated `get_function_source_code()` to pass `repo_path=effective_repo_path` to both functions

## 2025-11-20

### Stable Point IDs in Qdrant (qualified_name based) 🎯
- **Synchronized Qdrant & Memgraph Identity** - Both databases now use qualified_name as primary identity
  - Qdrant point IDs generated from `hash(qualified_name)` instead of `hash(qualified_name + line_numbers)`
  - Function moves update existing vector (upsert replaces) instead of creating new one
  - Function renames create new vector with different ID (fresh embedding needed)
  - Memgraph's unique constraint on `qualified_name` perfectly aligned with Qdrant's point ID strategy
  - Eliminates orphaned vectors when functions change location

### Changes
- Added `get_stable_point_id(qualified_name)` function to `codebase_rag/vector_store.py`
  - Uses MD5 hash of qualified_name only (no line numbers)
  - Returns 31-bit integer for Qdrant point ID
  - Consistent across re-ingestions as long as qualified_name unchanged

- Updated `store_embedding()` in both local and HTTP implementations
  - Changed from `id=node_id` to `id=get_stable_point_id(qualified_name)`
  - Still stores `node_id` in payload for Memgraph cross-reference
  - Updated docstrings explaining the new strategy

### Migration Note
- Requires `--clean` flag on first ingestion with new code due to ID change
- After cleaning, vectors will be re-embedded with new IDs
- No data migration needed, old vectors will be orphaned but ignored

### Unified Clean Flag for Memgraph & Qdrant 🧹
- **Consistent Database Cleanup** - `--clean` flag now cleans both Memgraph and Qdrant
  - `--clean` deletes all nodes from Memgraph AND all vectors from Qdrant collection
  - Ensures both databases start fresh when re-ingesting a repository
  - Per-repository isolation: only cleans the specific repo's Qdrant collection
  - Gracefully handles cases where Qdrant is not available

### Changes
- Added `clean_collection(repo_path)` function to `codebase_rag/vector_store.py`
  - Works with both local Qdrant client and HTTP-based remote Qdrant
  - Supports per-repository collection cleaning via repo_path parameter
  - Logs success/failure of cleanup operations
  - Stub implementation for when Qdrant is not installed

- Updated `codebase_rag/main.py`
  - `--clean` flag now also calls `clean_collection(repo_path=target_repo_path)`
  - Shows "Cleaning databases..." message to indicate both are being cleaned
  - Gracefully handles cleanup errors without blocking the update process

### Tool Initialization with Repo Path Context ⚙️
- **Proper Repo Path Precedence in Semantic Tools** - Tools now correctly respect injected `repo_path` instead of hardcoding environment variable
  - Module-level `_repo_path_context` pattern for storing repo_path in tool creators
  - Tool creators accept `repo_path` parameter and set context for nested functions
  - Fallback chain in all functions: `provided_param > _repo_path_context > None`
  - `runtime.py` passes `repo_path` to all semantic tool creators
  - Ensures CLI `--repo-path` and MCP injection take precedence over `TARGET_REPO_PATH`

### Changes
- Updated `codebase_rag/tools/semantic_search.py`
  - Added module-level `_repo_path_context: str | None = None` storage
  - `semantic_code_search()` now accepts `repo_path` parameter
  - `semantic_code_search_async()` now accepts `repo_path` parameter
  - `get_function_source_code()` now accepts `repo_path` parameter
  - `create_semantic_search_tool()` now accepts `repo_path` and sets module context
  - `create_get_function_source_tool()` now accepts `repo_path` and sets module context
  - All functions use fallback chain with effective_repo_path variable

- Updated `codebase_rag/tools/enhanced_semantic_search.py`
  - `create_enhanced_semantic_search_tool()` now accepts `repo_path` parameter
  - Sets module context in semantic_search module for nested async calls

- Updated `codebase_rag/runtime.py`
  - `create_semantic_search_tool(repo_path=repo_path)` - passes repo_path from context
  - `create_enhanced_semantic_search_tool(repo_path=repo_path, console=console)` - order updated
  - `create_get_function_source_tool(repo_path=repo_path)` - passes repo_path from context

### Memgraph Repository-Specific Node Tagging 🏷️
- **Full Repo Isolation in Memgraph** - Both vector store AND graph database now support multi-repo isolation
  - All nodes automatically tagged with `_repo_path` property during ingestion
  - All graph queries automatically filtered by `_repo_path` to ensure isolation
  - Semantic search results validated to belong to current repo
  - Backward compatible: Default `repo_path="."` skips filtering for single-repo setups

### Changes
- Updated `codebase_rag/services/graph_service.py`
  - Added `repo_path` parameter to `MemgraphIngestor.__init__()`
  - Modified `ensure_node_batch()` to automatically add `_repo_path` to all node properties
  - Added `_get_repo_filter(node_var)` helper method to generate repo WHERE clause fragments
  - Normalizes repo_path to absolute path for consistency

- Updated `codebase_rag/main.py`
  - All `MemgraphIngestor` instantiations now pass `repo_path` parameter
  - Updated in: `main_async()`, `start()`, `export()`, `optimize()` commands

- Updated `codebase_rag/tools/semantic_search.py`
  - Both `semantic_code_search()` and `semantic_code_search_async()` pass `repo_path` to `MemgraphIngestor`
  - Cypher queries now include repo filter: `WHERE id(n) IN [...] AND n._repo_path = $repo_path`
  - Results are verified to belong to current repo before returning

- Created `utils/test_memgraph_repo_tagging.py` - Tests repo path normalization and filter generation

### Repository-Specific Vector Collections 🔧
- **Multi-Repository Support** - Each repository now has its own Qdrant collection
  - Collections named as `code_embeddings_{repo_path_hash}` (e.g., `code_embeddings_8e336968`)
  - Allows multiple repositories to share the same Qdrant instance without conflicts
  - Hash-based naming ensures deterministic, unique collection names
  - Seamlessly integrates with existing ingestion pipeline

### Changes
- Updated `codebase_rag/vector_store.py`
  - Added `get_collection_name(repo_path)` function for deterministic collection naming
  - Fixed Qdrant HTTP API endpoint for collection creation (PUT `/collections/{name}`)
  - Updated `store_embedding()` to accept optional `repo_path` parameter
  - Updated `search_embeddings()` to accept optional `repo_path` parameter
  - Both functions now use repo-specific collections automatically

- Updated `codebase_rag/tools/semantic_search.py`
  - Both `semantic_code_search()` and `semantic_code_search_async()` now pass `repo_path` to `search_embeddings()`
  - Uses `settings.TARGET_REPO_PATH` for collection lookup

- Updated `codebase_rag/graph_updater.py`
  - `store_embedding()` calls now include `repo_path=self.repo_path`
  - Ensures embeddings are stored in correct repo-specific collection during ingest

- Created `utils/test_collection_naming.py` - Validates deterministic collection naming
- Created `utils/test_repo_specific_collections.py` - End-to-end test of repo-specific storage and search

### Major Feature: Qdrant Semantic Search in CLI Query Mode 🎉
- **Semantic Search Integration** - CLI query mode now uses Qdrant vector database
  - Search for code by natural language intent (e.g., "find authentication functions")
  - Complements existing Memgraph graph queries
  - New tool: `semantic_search_by_intent` for intent-based code search
  - Hybrid search: Combine semantic (Qdrant) + structural (Memgraph) queries

- **Async/Await Support for Embeddings** ✅ (Fixed asyncio.run() error)
  - Added `embed_code_async()` for use in async contexts
  - Added `embed_code_batch_async()` for batch processing in async contexts
  - Added `semantic_code_search_async()` for async semantic search
  - Fixes: "asyncio.run() cannot be called from a running event loop" error
  - Works seamlessly with pydantic_ai tools and event loops

- **Enhanced Semantic Search Tool** - New `enhanced_semantic_search.py` with:
  - Better error messaging and configuration feedback
  - Rich console output for results
  - Integration with Memgraph for detailed node information
  - Support for external embedders (no local dependencies needed)

## 2025-11-18

### Features
- **Batch Embedding Processing**: Implemented batch API calls for 3.7x faster embeddings
  - Processes up to 100 embeddings per API call instead of one at a time
  - Reduces latency significantly (from 1.8/sec to ~6-7/sec)
  - Expected to reduce 909-function ingest time from ~500s to ~130s

- **Semantic Embedding Progress Logging**: Added real-time metrics during embedding generation
  - Shows processing rate (embeddings/second)
  - Displays count of embedded, failed, and skipped functions
  - Reports total time taken
  - Logs progress at regular intervals

### Fixes
- **Embedder Integration**: Fixed OpenRouter API endpoint construction to append `/embeddings`
- **External Embedder Support**: Updated dependency checks to recognize external embedder configuration
- **Vector Store HTTP Support**: Added HTTP-based Qdrant access for remote instances without Python client
- **Dynamic Vector Dimensions**: Made embedding dimensions configurable via `EMBED_DIMENSION` env variable

### Configuration
- Updated `EMBED_MODEL` to `google/gemini-embedding-001` (3072 dimensions)
- Updated `EMBED_DIMENSION=3072`
- Embeddings now work with external APIs without requiring torch/transformers

### Testing
- Created `utils/test_embedder_smoke.py` - Tests embedder with OpenRouter API
- Created `utils/test_vector_store_smoke.py` - Tests Qdrant connectivity
- Created `utils/test_semantic_search_smoke.py` - Tests full semantic search pipeline
- Created `utils/test_batch_embedding.py` - Verifies batch embeddings are 3.7x faster

## 2025-11-18

### Features
- **Batch Embedding Processing**: Implemented batch API calls for 3.7x faster embeddings
  - Processes up to 100 embeddings per API call instead of one at a time
  - Reduces latency significantly (from 1.8/sec to ~6-7/sec)
  - Expected to reduce 909-function ingest time from ~500s to ~130s

- **Semantic Embedding Progress Logging**: Added real-time metrics during embedding generation
  - Shows processing rate (embeddings/second)
  - Displays count of embedded, failed, and skipped functions
  - Reports total time taken
  - Logs progress at regular intervals

### Fixes
- **Embedder Integration**: Fixed OpenRouter API endpoint construction to append `/embeddings`
- **External Embedder Support**: Updated dependency checks to recognize external embedder configuration
- **Vector Store HTTP Support**: Added HTTP-based Qdrant access for remote instances without Python client
- **Dynamic Vector Dimensions**: Made embedding dimensions configurable via `EMBED_DIMENSION` env variable

### Configuration
- Updated `EMBED_MODEL` to `google/gemini-embedding-001` (3072 dimensions)
- Updated `EMBED_DIMENSION=3072`
- Embeddings now work with external APIs without requiring torch/transformers

### Testing
- Created `utils/test_embedder_smoke.py` - Tests embedder with OpenRouter API
- Created `utils/test_vector_store_smoke.py` - Tests Qdrant connectivity
- Created `utils/test_semantic_search_smoke.py` - Tests full semantic search pipeline
- Created `utils/test_batch_embedding.py` - Verifies batch embeddings are 3.7x faster
