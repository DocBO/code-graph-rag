# `query_codebase` MCP connection

The `query_codebase` endpoint is implemented as an **MCP tool**, not as a separate REST handler named `/query_codebase`.

## Startup path

The main CLI entry point is `main.py`, which invokes the Typer application:

```python
if __name__ == "__main__":
    from codebase_rag.main import app
    app()
```

The `mcp` command in `codebase_rag/main.py` starts either:

- **stdio transport** through `serve_mcp_stdio(...)`
- **Streamable HTTP transport** through `serve_mcp_http(...)`

For HTTP, the documented endpoint is:

```text
http://127.0.0.1:8765/mcp
```

The MCP client sends a protocol request to that endpoint, specifying the tool name `query_codebase`. The server dispatches it through `GraphCodeMCPServer._call_tool`.

## Request flow

The runtime flow is:

```text
MCP client
  │
  ├─ stdio transport
  │    └─ serve_mcp_stdio()
  │
  └─ HTTP transport
       └─ serve_mcp_http()
            └─ StreamableHTTPSessionManager
                 └─ GraphCodeMCPServer
                      ├─ list_tools()
                      └─ call_tool("query_codebase", arguments)
                           └─ GraphCodeMCPContext.query_codebase()
                                ├─ resolve repository path
                                ├─ create MemgraphIngestor
                                ├─ initialize_services_and_agent()
                                ├─ create the RAG agent
                                ├─ agent.run(question)
                                └─ return response
```

Relevant sources:

- `codebase_rag/main.py`: CLI `mcp` command and transport selection
- `codebase_rag/mcp/server.py`: MCP server, schemas, dispatch, and HTTP/stdio wiring
- `codebase_rag/runtime.py`: RAG agent and tool initialization
- `codebase_rag/services/llm.py`: orchestrator agent creation

The MCP schema for `query_codebase` accepts:

```json
{
  "question": "How is authentication implemented?",
  "repo_path": "/optional/repository/path"
}
```

`question` is required; `repo_path` is optional.

The dispatcher performs:

```python
result = await self.context.query_codebase(
    question=args.get("question", ""),
    repo_path=args.get("repo_path"),
)
```

Then it returns:

```json
{
  "repo_path": "...",
  "question": "...",
  "response": "...",
  "sources": [
    {
      "qualified_name": "...",
      "filename": "...",
      "start_line": 10,
      "end_line": 35
    }
  ],
  "retrieval": {
    "used_graph": true,
    "used_semantic_search": true,
    "index_status": "fresh"
  }
}
```

The behavior is covered by `codebase_rag/tests/test_mcp_server.py`.

---

# How `query_codebase` uses the graph and vector databases

## Memgraph: structural knowledge

Memgraph stores the parsed codebase as a knowledge graph. The documented schema includes nodes such as:

- `Project`
- `Package`
- `Folder`
- `File`
- `Module`
- `Class`
- `Function`
- `Method`
- `ExternalPackage`

And relationships such as:

- `CONTAINS_FILE`
- `CONTAINS_MODULE`
- `DEFINES`
- `DEFINES_METHOD`
- `CALLS`
- `IMPORTS`
- `INHERITS`
- `IMPLEMENTS`
- `DEPENDS_ON_EXTERNAL`

Memgraph is used for questions that require exact structure or relationships, for example:

- Which methods belong to a class?
- Which functions call another function?
- Which modules define a symbol?
- What files are under a directory?
- Which packages does the project depend on?

The lower-level graph tool is:

```text
create_query_tool()
  └─ query_codebase_knowledge_graph()
       ├─ CypherGenerator.generate()
       └─ MemgraphIngestor.fetch_all()
```

This tool translates natural language into Cypher and executes it against Memgraph.

There is also a separate MCP tool named `graph_query`. It returns the generated Cypher and raw graph results. By contrast, `query_codebase` invokes the full RAG agent and returns a synthesized answer.

## Qdrant: intent-based retrieval

Qdrant is used for semantic search over code embeddings.

The semantic search flow in `codebase_rag/tools/semantic_search.py` is:

```text
natural-language search
  └─ embed_code_async()
       └─ Qdrant search_embedding_matches()
            └─ retrieve node IDs and similarity scores
                 └─ Memgraph lookup by node ID
                      └─ return qualified name, type, and score
```

Qdrant stores payload metadata including:

```python
{
    "node_id": node_id,
    "qualified_name": qualified_name,
    "chunk_text": chunk_text,
    "file_path": file_path,
}
```

Qdrant collections are repository-specific. The collection name is derived from a hash of the absolute repository path, for example:

```text
code_embeddings_<repo-hash>
```

Qdrant can operate in two modes:

- Local on-disk storage at `./.qdrant_code_embeddings`
- Remote Qdrant configured with `QDRANT_HOST`, `QDRANT_PORT`, and `QDRANT_API_KEY`

Semantic search is useful for questions such as:

- Find code that handles authentication
- Where is configuration loading implemented?
- Find error-handling functions
- Find database-related operations

The semantic result does not contain the complete source by itself. It uses the returned Memgraph node ID to find source location metadata and, when needed, retrieve source code from the repository.

## Hybrid retrieval

The intended division is:

| Question type | Primary store |
|---|---|
| Exact symbol, file, class, or relationship | Memgraph |
| Functional intent or conceptual similarity | Qdrant |
| Semantic discovery plus structural context | Qdrant followed by Memgraph |
| Complete implementation | Memgraph metadata plus filesystem source retrieval |

`initialize_services_and_agent()` registers both:

- `create_query_tool(...)`
- `create_semantic_search_tool(...)`
- `create_enhanced_semantic_search_tool(...)`
- `create_get_source_tool(...)`

Therefore, `query_codebase` delegates the decision to the orchestrator model. It does not itself explicitly execute both databases in a fixed sequence.

---

# Ingestion and synchronization

`GraphUpdater` is responsible for ingesting parsed code into Memgraph and generating embeddings. The knowledge graph results show these relevant operations:

- `GraphUpdater._generate_semantic_embeddings`
- `GraphUpdater._prepare_embedding_chunks`
- `GraphUpdater.update_embeddings_for_files`
- `vector_store.batch_store_embeddings`
- `vector_store.delete_embeddings_for_files`

The update path is intended to keep the stores synchronized:

1. Parse changed files.
2. Update Memgraph nodes and relationships.
3. Delete vectors associated with changed files.
4. Generate new embeddings.
5. Store replacement vectors in the repository-specific Qdrant collection.
6. Write ingest metadata.

The MCP `start_updater` tool checks ingest metadata first and avoids a full update when the index is fresh. It can also force a rebuild and clean the Qdrant collection before regeneration.

---

# Prompt and guidance improvements

The current prompts provide a useful foundation, but several changes would make the system more reliable.

## 1. Separate the two query modes explicitly

The current orchestrator prompt describes both graph and semantic retrieval, but the operational distinction should be more explicit.

Recommended guidance:

```text
Choose tools according to the question:

- Use graph_query/query_codebase_knowledge_graph for exact structural facts:
  classes, methods, files, modules, callers, callees, imports, inheritance,
  dependencies, and directory membership.

- Use semantic_search_by_intent or semantic_search_functions for intent-based
  discovery:
  "where is authentication handled?", "find retry logic", or
  "show code related to caching".

- After semantic search, use get_source_by_id or file-reading tools to inspect
  the actual implementation.

- For relationship questions involving semantic matches, first find candidate
  symbols semantically, then query Memgraph using their qualified names or IDs.
```

This avoids leaving the model to infer the retrieval strategy.

## 2. Correct the tool-name terminology

The prompts refer to names such as:

```text
semantic_code_search
query_codebase_knowledge_graph
read_file_content
```

However, the RAG agent internally registers names including:

- `semantic_search_functions`
- `semantic_search_by_intent`
- `get_source_by_id`
- the graph query tool created by `create_query_tool`

The external MCP wrapper exposes:

- `query_codebase`
- `graph_query`
- `quick_semantic_retrieval`

The guidance should distinguish **MCP tool names** from **internal agent tool names**. Otherwise, a model may try to call a tool that is not registered in its current context.

A better wording would be:

```text
When operating inside the RAG agent, use the registered semantic-search and
graph-query tools by their exposed tool names. Do not assume that MCP tool names
and internal agent tool names are identical.
```

## 3. Remove contradictory “semantic-first” guidance

The prompt says semantic search must always be used first for:

- entry points
- startup
- error handling
- authentication
- validation
- any question about functionality

That is too broad.

For example:

- “What does `GraphCodeMCPContext.query_codebase` call?” is structural and should use the graph directly.
- “Where is the `mcp` CLI command defined?” is an exact code-location question and should use graph/file retrieval.
- “How is authentication implemented?” is a good semantic-search candidate.

Recommended decision rule:

```text
Use semantic search first only when the user describes behavior without naming
a concrete symbol, file, or relationship.

Use graph lookup first when the user names a known symbol, asks for callers/callees,
requests a class or method listing, or asks about file/module structure.
```

## 4. Add repository-isolation instructions to every retrieval path

The Cypher prompt correctly emphasizes `_repo_path = $repo_path`, but the same rule should appear in the orchestrator guidance:

```text
Always preserve the active repository scope. Never combine results from multiple
repositories. Treat repo_path as mandatory retrieval context even when the user
does not mention it.
```

This is particularly important because:

- Memgraph may contain multiple repositories.
- Qdrant uses repository-specific collections.
- `quick_semantic_retrieval` performs a follow-up Memgraph lookup using `_repo_path`.

## 5. Require evidence-backed answers

The current prompt says to use only retrieved information, but it could require concrete evidence:

```text
For every implementation claim, include at least one source reference:
repository-relative file path, qualified symbol name, and line range when
available.

Do not infer behavior solely from a symbol name or semantic-search score.
Retrieve and inspect the source before describing implementation details.
```

This would reduce answers based only on graph metadata or embedding similarity.

## 6. Define “no result” behavior more precisely

The current tools sometimes return empty results when semantic dependencies are unavailable. The prompt should distinguish:

- no matching code
- embeddings not generated
- semantic dependencies not installed
- database failure
- stale index

Suggested policy:

```text
If semantic retrieval returns no results, determine whether the result means:
(a) no match,
(b) embeddings are unavailable,
(c) semantic dependencies are missing, or
(d) the vector service failed.

Report the actual condition when the tool provides it. Do not present an
infrastructure failure as evidence that the code does not exist.
```

This is important because `semantic_code_search` catches exceptions and returns an empty list, which can hide the difference between “no match” and “search failed.”

## 7. Add freshness checks for code questions

The MCP server already exposes:

- `ingest_status`
- `start_updater`

The orchestrator guidance should use them:

```text
Before answering repository-wide implementation questions, check whether the
index has pending changes. If changes are present, use start_updater unless the
user explicitly requests analysis of the indexed snapshot.
```

This is especially relevant when the real-time watcher is not running.

## 8. Restrict mutation-capable tools for `query_codebase`

`query_codebase` initializes the full standard agent, including:

- file writer
- file editor
- shell command execution
- document analysis
- retrieval tools

That means a tool described as “Query Codebase (RAG)” is backed by an agent that also has modification and command-execution capabilities.

This creates a mismatch between the endpoint’s name and its capabilities. Improvements could include:

### Preferred design

Create a read-only agent for `query_codebase` with only:

- graph query
- code retrieval
- file reader
- directory listing
- document analysis
- semantic search
- source retrieval

Use a separate MCP tool for edits or optimization.

### Minimum prompt safeguard

```text
For query_codebase, answer the question only. Do not modify files, create files,
execute shell commands, or run optimization workflows unless the MCP request
explicitly identifies an approved mutation operation.
```

Prompt restrictions are weaker than removing the tools from the agent, so tool-level separation would be preferable.

## 9. Avoid broad optimization guidance in the query agent

The current system includes an optimization prompt that asks the agent to propose changes and gives it editing tools. That workflow is appropriate for `optimize_code`, but it should not be implicitly available during ordinary `query_codebase` requests.

The MCP server already distinguishes `optimize_code`; the internal agent configuration should preserve that separation.

## 10. Improve the Cypher prompt’s schema consistency

The Cypher prompt says it targets “Neo4j Cypher,” while the application uses Memgraph. The prompt should refer consistently to Memgraph and document supported query patterns.

Also, the prompt currently says every matched node variable must have `_repo_path` filtering. That should be made unambiguous for relationship queries:

```text
For every node variable in MATCH, apply repository isolation either directly
in WHERE or through an equivalent condition. This includes both endpoints of
relationships and nodes introduced by variable-length paths.
```

The prompt should also discourage unbounded variable-length paths because they can produce very large result sets:

```text
Use bounded relationship depths unless the user explicitly requests arbitrary
reachability. Always apply a reasonable LIMIT for exploratory queries.
```

## 11. Improve response contracts

This item is implemented. `query_codebase` now includes structured evidence in addition to the free-form `response`:

```json
{
  "repo_path": "...",
  "question": "...",
  "response": "...",
  "sources": [
    {
      "qualified_name": "...",
      "filename": "...",
      "start_line": 10,
      "end_line": 35
    }
  ],
  "retrieval": {
    "used_graph": true,
    "used_semantic_search": true,
    "index_status": "fresh"
  }
}
```

This would make answers easier for MCP clients to validate and display.

---

# Highest-priority improvements

I would prioritize these changes:

1. **Create a read-only agent for `query_codebase`.** ✅ Implemented 2026-08-11 — `initialize_services_and_agent(..., read_only=True)` excludes file writer/editor/shell tools and uses `RAG_READ_ONLY_SYSTEM_PROMPT`; `query_codebase` runs read-only, while `optimize_code` and CLI loops keep full tools.
2. **Make the graph-versus-vector tool-selection rules explicit.** ✅ Implemented 2026-08-11 — both orchestrator prompts carry a `TOOL SELECTION RULES` block (graph for structural facts, semantic tools for intent, source tools after matches, graph follow-up via qualified names).
3. **Align prompt tool names with the actual registered tool names.** ✅ Implemented 2026-08-11 — stale `semantic_code_search` replaced with `semantic_search_by_intent` / `semantic_search_functions` / `get_source_by_id`.
4. **Require file/symbol/line evidence before implementation claims.** ✅ Implemented 2026-08-11 — prompts require at least one source reference per implementation claim and forbid inference from names/scores alone.
5. **Check ingest freshness before repository-wide answers.** (dismissed)
6. **Expose retrieval metadata and source citations in the MCP response.** ✅ Implemented 2026-08-11 — `query_codebase` returns `sources[]` (deduplicated from GraphData/CodeSnippet returns) and a `retrieval` block (`used_graph`, `used_semantic_search`, `index_status`); output schema updated.
7. **Make semantic-search failures distinguishable from empty search results.** ✅ Implemented 2026-08-11 — `SemanticSearchOutcome` (`ok`/`no_match`/`no_dependencies`/`failed`) via `semantic_code_search_outcome[_async]`; agent tools report the actual condition; prompts instruct the model to report infra failures distinctly from "no match".
8. **Add bounded graph traversal and mandatory result limits to the Cypher guidance.** ✅ Implemented 2026-08-11 — Cypher prompts mandate `LIMIT` on every query, forbid unbounded variable-length paths, and require bounded depths unless arbitrary reachability is requested.

The current architecture already supports hybrid retrieval; the main weaknesses are that the orchestration decision is left largely to the model, the query endpoint has more privileges than its name suggests, and the prompt terminology does not consistently match the actual MCP and internal tool names.

---

## Follow-up: Agent Search Depth Modes (Implemented 2026-08-11)

To tune speed vs. investigation breadth in the agentic path, `query_codebase` now accepts:

- `search_depth: "shallow"` — minimal, fast retrieval.
- `search_depth: "normal"` — balanced retrieval (default).
- `search_depth: "deep"` — broader multi-step retrieval with richer evidence.

`quick_semantic_retrieval` remains non-agentic and continues to be tuned via `top_n`.