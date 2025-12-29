# Graph-Code MCP Server Tools

The Graph-Code MCP (Model Context Protocol) server exposes the following tools for interacting with the codebase knowledge graph and RAG system. These tools can be used over stdio or HTTP (SSE) transports.

## Available Tools

### 1. `graph_ingest`
**Title:** Update Knowledge Graph  
**Description:** Parse a repository with Tree-sitter and refresh the Memgraph knowledge graph.  

**Parameters:**
- `repo_path` (string, optional): Repository path to ingest.
- `clean` (boolean, default: false): Drop existing nodes/relationships before ingest.
- `batch_size` (integer, optional): Memgraph batch size override.

**Returns:**
- `repo_path`, `cleaned`, `batch_size`, `duration_ms`

**Example:** Ingest current repo with clean slate.


### 2. `query_codebase`
**Title:** Query Codebase (RAG)  
**Description:** Query the codebase using natural language with configurable RAG strategy. `semantic-seed-strategy` is the standard default, using semantic search to seed graph traversal and synthesis.  

**Parameters:**
- `question` (string, required): Question about codebase functionality/implementation.
- `strategy` (string, optional, default: `semantic-seed-strategy`): RAG retrieval strategy.

**Returns:**
- `question`, `strategy`, `response` (string: synthesized answer)

**Example:** \"How does user authentication work?\" (uses semantic-seed-strategy by default)


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

## Usage

- **Stdio:** `python -m codebase_rag.mcp.server --repo-path /path/to/repo`
- **HTTP:** Supports Streamable HTTP (SSE) at configurable host/port/path.

See [`codebase_rag/mcp/server.py`](codebase_rag/mcp/server.py) for implementation details.

## Strategies

- **`semantic-seed-strategy`** (default for `query_codebase`): Semantic search for seed nodes, graph expansion via relationships, LLM synthesis. Ideal for functional/implementation questions.
