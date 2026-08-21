# Graph-Code RAG Control Panel

A local control panel for the [Graph-Code RAG](../../README.md) watcher stack.

It manages a **repository list** (persisted in `backend/data/repos.json`), starts
and stops a **per-repo real-time watcher** (the `realtime_updater.py` process),
and runs **one unified MCP server** over HTTP. The MCP server accepts
`repo_path` per tool call, so a single instance serves every registered repo.

```
┌─────────────┐   spawns    ┌─────────────────────────────┐
│ FastAPI API │────────────▶│ realtime_updater.py <repo>  │  per repo
│  :8008      │             └─────────────────────────────┘
│             │   spawns    ┌─────────────────────────────┐
│             │────────────▶│ codebase_rag.main mcp --    │  one instance
│             │             │   transport http :8765      │
└──────┬──────┘             └─────────────────────────────┘
       │
┌──────▼──────┐
│ React Vite │  dashboard on :3003 (polls /api/status)
└─────────────┘
```

## Quick Start

```bash
chmod +x start_dev.sh
./start_dev.sh
```

- Frontend dashboard: http://localhost:3003
- Backend API + Swagger: http://localhost:8008/docs

Start Memgraph first (`docker-compose up -d` in the repo root) — watchers and the
MCP server connect to `localhost:7687` (override with `MEMGRAPH_HOST` /
`MEMGRAPH_PORT`).

The backend runs inside the **project's uv environment** — `fastapi` and
`uvicorn[standard]` are declared in the root `pyproject.toml` (`uv sync` to
install them).

## Usage

1. **Register a repo**: paste an absolute path into the form and click *Add repo*.
   Optional fields control the watcher debounce, batch size, and whether the
   initial full scan is skipped (`--no-update`).
2. **Start a watcher**: *Start watcher* begins watching for file changes only
   (`--no-update`); *Start + full scan* performs an initial ingestion first.
3. **Stop / Remove**: *Stop watcher* SIGINTs the process group and cleans up.
   *Remove* deregisters the repo (and stops its watcher).
4. **Unified MCP server**: pick the default repo and start the single HTTP MCP
   server (`:8765/mcp`). Tools take `repo_path` per call, so all repos are
   reachable through this one server.

The dashboard polls `/api/status` every 2.5 s and shows:
- which repos have an **active watcher** (green lamp)
- when an **update is running** (pulsing lamp + `UPDATING` badge, parsed from
  watcher log lines)
- MCP server **activity state** (`WORKING` / `IDLE` / `STALLED`) with active
   request count and last-work timestamp
- last-update time and duration, per-repo log tails, and MCP server state

A **Query Codebase (RAG)** card runs `query_codebase` against a selected repo:
pick the repo, choose depth (`shallow`/`normal`/`deep`), type a question, and
the agent's markdown answer is rendered in place with a **Copy** button.

## API

| Method | Path                              | Description                          |
| ------ | --------------------------------- | ------------------------------------ |
| GET    | `/api/status`                     | Repos + MCP + config snapshot        |
| GET    | `/api/repos`                      | List registered repos                |
| POST   | `/api/repos`                      | Register a repo                      |
| DELETE | `/api/repos/{path}`               | Deregister a repo                    |
| POST   | `/api/repos/{path}/watch/start`   | Start watcher (`full_scan` optional) |
| POST   | `/api/repos/{path}/watch/stop`    | Stop watcher                         |
| POST   | `/api/repos/{path}/embedding`     | Regenerate all embeddings (no ingest)|
| GET    | `/api/repos/{path}/logs`          | Watcher log tail                     |
| POST   | `/api/shutdown`                   | Stop all watchers, MCP, and the API  |
| POST   | `/api/mcp/start`                  | Start the unified MCP server         |
| POST   | `/api/mcp/stop`                   | Stop the MCP server                  |
| GET    | `/api/mcp/logs`                   | MCP server log tail                  |
| POST   | `/api/query`                      | Run `query_codebase` RAG on a repo   |

`POST /api/query` accepts `repo_path`, `question`, and optional
`search_depth` (`shallow`/`normal`/`deep`, default `normal`).

`GET /api/status` now includes MCP activity telemetry under `mcp`:
- `activity`: `idle`, `busy`, `stalled`, or process-state values (`starting`, `stopping`, `error`, `stopped`)
- `active_requests`: count of in-flight MCP request methods (`POST`/`PUT`/`PATCH`/`DELETE`)
- `last_activity_at`: epoch timestamp of the latest non-keepalive MCP log event

`POST /api/repos/{path}/embedding` spawns `realtime_updater.py --only-embedding`
as a tracked subprocess: it cleans the Qdrant collection and regenerates all
semantic embeddings from the current graph, without ingesting files or touching
the watcher. The `Only embeddings` button on the repo card triggers it and the
tile shows `UPDATING` while it runs (progress parsed from the Pass 4 log lines).

`POST /api/shutdown` (topbar **Stop all** button) stops every watcher, any
running embedding job, and the MCP server, then exits the control panel API
process itself. The response is sent before the API terminates so the client
sees the result.

`{path}` is the URL-encoded absolute repo path.

## Configuration

| Env var          | Default            | Purpose                       |
| ---------------- | ------------------ | ----------------------------- |
| `CONTROL_PORT`   | `8008`             | Backend API port              |
| `MEMGRAPH_HOST`  | `localhost`        | Memgraph host                 |
| `MEMGRAPH_PORT`  | `7687`             | Memgraph port                 |
| `MCP_HOST`       | `127.0.0.1`        | MCP server bind host          |
| `MCP_PORT`       | `8765`             | MCP server port               |
| `MCP_PATH`       | `/mcp`             | MCP HTTP path                 |
| `FRONTEND_PORT`  | `3003`             | Vite dev server port          |

## Notes

- No authentication — the panel is meant to run on localhost only.
- The backend launches child processes with `uv run` from the project root, so
  `uv` must be on `PATH`.
- The backend itself is started with `uv run` too; `fastapi` and
  `uvicorn[standard]` live in the root `pyproject.toml`.
- `repos.json` (registered repo list) is stored in `backend/data/`.
- The dashboard runs with `uvicorn --reload`, which re-creates the backend on
  code changes. On startup the backend reconciles orphaned watcher/MCP
  processes left by the previous instance: stale duplicates are stopped and
  watchers are re-spawned so update-progress tracking stays accurate. Starting
  a watcher/MCP when one already runs for that repo adopts the existing process
  instead of spawning a second writer (which would cause Memgraph
  transaction conflicts).
