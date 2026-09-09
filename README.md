<div align="center">
  <picture>
    <source srcset="assets/logo-dark-any.png" media="(prefers-color-scheme: dark)">
    <source srcset="assets/logo-light-any.png" media="(prefers-color-scheme: light)">
    <img src="assets/logo-dark.png" alt="Graph-Code logo" width="480">
  </picture>
</div>

# Graph-Code RAG Control Center

This repository is a local, multi-repository control center for Graph-Code RAG.
Use its web dashboard to register repositories, keep each knowledge graph current
with a real-time watcher, and expose all registered repositories through one MCP
server.

It is built on [vitali87/code-graph-rag](https://github.com/vitali87/code-graph-rag).
That upstream repository remains the reference for Graph-Code's parser, graph
schema, language support, CLI workflows, and implementation details.

## What This Fork Adds

- A React control panel for managing multiple local repositories.
- Per-repository real-time watchers with optional initial full scans.
- A unified HTTP MCP server; every tool accepts an optional `repo_path`.
- Memgraph for code-structure graphs and Qdrant for semantic code embeddings.
- Dashboard access to codebase queries, semantic retrieval, embedding refreshes,
  process status, and live log tails.

## Start Here

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- Docker and Docker Compose
- Node.js and npm
- Model-provider and embedding credentials in `.env`

### Run The Control Center

From the repository root:

```bash
uv sync --extra treesitter-full
cp .env.example .env
# Configure your model, embedding, and optional Qdrant settings in .env.
docker compose up -d
cd control_panel
chmod +x start_dev.sh
./start_dev.sh
```

Open:

- Dashboard: http://localhost:3003
- API and Swagger UI: http://localhost:8008/docs
- Memgraph Lab: http://localhost:3000

The start script runs the FastAPI backend and Vite frontend together. Leave that
terminal open while using the dashboard. The panel starts watchers and the MCP
server as managed child processes. Qdrant uses a local on-disk collection by
default; configure `QDRANT_HOST` when using a remote Qdrant service.

## Daily Workflow

1. Add an absolute repository path in the dashboard.
2. Start it with **Start + full scan** to build its graph and semantic index.
3. Keep **Start watcher** running while the repository changes.
4. Start the unified MCP server from the dashboard.
5. Configure your MCP client with `http://127.0.0.1:8765/mcp`.

The MCP server serves every registered repository. Pass `repo_path` to target a
specific one; otherwise the selected default repository is used.

### Available MCP Tools

- `get_watched_repos`: registered repositories and watcher states.
- `get_status`: MCP configuration and service status.
- `ingest_status`: index freshness and pending changes.
- `quick_semantic_retrieval`: fast semantic code matches with source locations.
- `query_codebase` and `query_codegraph`: evidence-backed codebase answers.

For parameters and response contracts, see [docs/mcp-tools.md](docs/mcp-tools.md).

## Data Services

- **Memgraph** stores repository structure and relationships, such as files,
  symbols, imports, and calls. It is required and defaults to `localhost:7687`.
- **Qdrant** stores semantic embeddings used by quick semantic retrieval and
  semantic context for codebase queries. Configure a remote instance with
  `QDRANT_HOST`, `QDRANT_PORT`, and `QDRANT_API_KEY`; without a host, Graph-Code
  uses a local on-disk Qdrant collection. Its corpus is deliberately focused:
  Python class, function, and method names with available docstrings, plus
  chunked Markdown; implementation bodies and other source-file contents remain
  available through Memgraph rather than being embedded in Qdrant.

## Operations Notes

- Memgraph must be reachable before starting a watcher or MCP service.
- The dashboard is designed for localhost use and does not provide authentication.
- Repository registrations are stored at `control_panel/backend/data/repos.json`.
- Use **Only embeddings** to rebuild Qdrant semantic embeddings without
  re-ingesting source files.
- Use **Stop all** to stop all watchers, embedding jobs, the MCP service, and the
  control panel backend.

For control-panel API endpoints and environment variables, see
[control_panel/README.md](control_panel/README.md).

## Upstream Graph-Code RAG

This fork retains the underlying Graph-Code RAG system. Consult the
[upstream README](https://github.com/vitali87/code-graph-rag#readme) for:

- Supported languages and Tree-sitter setup.
- Ingestion, CLI, export, optimization, and graph-schema details.
- Provider configuration options and parser architecture.
- Contributing to the core Graph-Code RAG project.

## Development

```bash
make test-quick
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for development conventions and the
[upstream project](https://github.com/vitali87/code-graph-rag) for the core
technical documentation.
