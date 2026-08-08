# Graph-Code MCP Server Tools

The Graph-Code MCP (Model Context Protocol) server exposes the following tools for interacting with the codebase knowledge graph and RAG system. These tools can be used over stdio or HTTP (SSE) transports.

All tool responses include `repo_path` so clients can always see which repository context produced the result.

## Available Tools

### 1. `quick_semantic_retrieval`
**Title:** Quick Semantic Retrieval  
**Description:** Fast semantic-only retrieval of matched semantic chunks (not full symbol bodies) with filename and line metadata. This path does not run the full RAG agent flow.

**Parameters:**
- `search_phrase` (string, required): Semantic phrase to search for.
- `top_n` (integer, optional): Max number of matches (default: 5, min: 1, max: 50).

**Returns:**
- `repo_path`, `search_phrase`, `top_n`, `matches[]`
- Each match includes: `qualified_name`, `type`, `score`, `filename`, `start_line`, `end_line`, `snippet` (chunk text)

**Example:** "JWT token validation middleware"


### 2. `query_codebase`
**Title:** Query Codebase (RAG)  
**Description:** Query the codebase using the standard agent search and answer flow. The agent can combine graph queries, source retrieval, and semantic tools as needed.

**Parameters:**
- `question` (string, required): Question about codebase functionality/implementation.

**Returns:**
- `repo_path`, `question`, `response` (string: synthesized answer)

**Example:** \"How does user authentication work?\"


### 3. `get_status`
**Title:** Get Server Status  
**Description:** Current configuration (repo, Memgraph, providers).  

**Parameters:** None  

**Returns:**
- `repo_path`, `batch_size`, `memgraph`, `orchestrator`, `cypher`

### 4. `ingest_status`
**Title:** Ingest Status  
**Description:** Last ingest time and changes since then.  

**Parameters:**
- `repo_path` (string, optional): Repo to check.

**Returns:**
- `repo_path`, `last_ingest`, `changes` (added/deleted/modified/total), `metadata_path`

### 5. `get_watched_repos`
**Title:** Get Watched Repositories  
**Description:** Return which repositories are registered with the control panel and whether each has an active real-time watcher running. Lets agents quickly check if their repo is being ingested/watched or is stopped.

**Parameters:** None  

**Returns:**
- `source`: `"control_panel"` (live status via `CONTROL_PANEL_URL`, default `http://127.0.0.1:8008`) or `"proc_scan"` (fallback: `/proc` scan of `realtime_updater.py` processes when the control panel is unreachable)
- `control_panel`: `{url, reachable, mcp?, error?}`
- `repos[]`: each with `path`, `name`, `watcher_state`, `watcher_pid`, `update_in_progress`, `last_update_at`
- `watched_paths[]`: paths currently being watched

**Example output:**
```json
{
  "source": "control_panel",
  "control_panel": {"url": "http://127.0.0.1:8008", "reachable": true},
  "repos": [
    {
      "path": "/home/oliver/gitlab/addibase/elysia",
      "name": "elysia",
      "watcher_state": "running",
      "watcher_pid": 144318,
      "update_in_progress": false,
      "last_update_at": 1786204764.2
    }
  ],
  "watched_paths": ["/home/oliver/gitlab/addibase/elysia"]
}
```

## Startup

Use the unified startup script to launch both the MCP server and real-time watcher:

```bash
# Start MCP server + real-time updater for a repository
uv run python start_mcp_with_watcher.py ~/path/to/repo

# With custom Memgraph settings
uv run python start_mcp_with_watcher.py ~/path/to/repo --host localhost --port 7687 --batch-size 1000

# With custom debounce delay for real-time updates and no initial update
uv run python start_mcp_with_watcher.py ~/path/to/repo --debounce 30 --transport http --no-update --batch-size 2000
```

The script automatically:
1. Starts the MCP server on stdio (default) or HTTP (with `--transport http`)
2. Launches the real-time updater in the background
3. Keeps both services synchronized

**Advanced options:**
- `--transport http`: Use HTTP transport instead of stdio (requires `--host`, `--port`, `--path`)
- `--host`: HTTP server host (default: `127.0.0.1`)
- `--port`: HTTP server port (default: `8765`)
- `--path`: HTTP endpoint path (default: `/mcp`)
- `--batch-size`: Memgraph batch size (default: from settings)
- `--debounce`: Real-time updater debounce delay in seconds (default: `20`)

For manual startup of individual components:
- **MCP Server only:** `uv run python -m codebase_rag.main mcp --repo-path /path/to/repo`
- **Real-time updater only:** `uv run python realtime_updater.py /path/to/repo`

See [`codebase_rag/mcp/server.py`](codebase_rag/mcp/server.py) for implementation details.
