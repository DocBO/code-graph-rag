# Graph-Code MCP Server Tools

The Graph-Code MCP (Model Context Protocol) server exposes the following tools for interacting with the codebase knowledge graph and RAG system. These tools can be used over stdio or HTTP (SSE) transports.

## Available Tools

### 1. `query_codebase`
**Title:** Query Codebase (RAG)  
**Description:** Query the codebase using natural language with configurable RAG strategy. `semantic-seed-strategy` is the standard default, using semantic search to seed graph traversal and synthesis.  

**Parameters:**
- `question` (string, required): Question about codebase functionality/implementation.
- `strategy` (string, optional, default: `semantic-seed-strategy`): RAG retrieval strategy.

**Returns:**
- `question`, `strategy`, `response` (string: synthesized answer)

**Example:** \"How does user authentication work?\" (uses semantic-seed-strategy by default)


### 2. `get_status`
**Title:** Get Server Status  
**Description:** Current configuration (repo, Memgraph, providers).  

**Parameters:** None  

**Returns:**
- `repo_path`, `batch_size`, `memgraph`, `orchestrator`, `cypher`

### 3. `ingest_status`
**Title:** Ingest Status  
**Description:** Last ingest time and changes since then.  

**Parameters:**
- `repo_path` (string, optional): Repo to check.

**Returns:**
- `repo_path`, `last_ingest`, `changes` (added/deleted/modified/total), `metadata_path`

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

## Strategies

- **`semantic-seed-strategy`** (default for `query_codebase`): Semantic search for seed nodes, graph expansion via relationships, LLM synthesis. Ideal for functional/implementation questions.
