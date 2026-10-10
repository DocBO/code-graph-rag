# Bug: failed code lookups are published as valid source citations

**Component:** `codebase_rag/mcp/server.py` (`_extract_retrieval_metadata`)
**Versions observed:** `graph-code-mcp` 1.21.1
**Date observed:** 2026-10-10
**Priority:** Medium — **Effort:** Small

## Summary

`_extract_retrieval_metadata` builds the `sources` array returned in
`structuredContent`. Its `CodeSnippet` branch appends **every** snippet unconditionally, including
ones that represent a *failed* lookup. `CodeRetriever.find_code_snippet` returns
`found=False` with `file_path=""`, `line_start=0`, `line_end=0` on three separate failure paths, so a
lookup that found nothing is published to the caller as a citation of the form:

```json
{"qualified_name": "re-mes-app.backend-sales-order.python.dataModelsSalesOrder.SubSalesOrder.initialize",
 "filename": "", "start_line": 0, "end_line": 0}
```

The `GraphData` branch immediately above it *does* guard against exactly this. The two branches
disagree, which is the defect.

## Impact

- Citations that cannot be resolved: an agent instructed to verify a claim by reading the cited file
  receives an empty filename (`""`) and lines `0,0`. There is nothing to open and nothing to check
  the claim against — strictly worse than a wrong filename, which at least points somewhere.
- A failed lookup is indistinguishable from a real citation in the returned payload, so `sources`
  overstates how much of the answer is grounded.
- The diagnostic fields that would explain the failure (`found`, `error_message`) exist on the model
  but are discarded before the caller sees them.

## Reproduction (observed)

`query_codebase` on `/home/oliver/gitlab/re-mes-app`, `search_depth: normal`, question:

> In backend-sales-order, trace the backend flow when a sales order is created from an offer: which
> HTTP entry point handles it, which data models/collections are written, and does it call any other
> backend service or create specimens as a side effect?

The returned `structuredContent.sources` contained:

```json
{"qualified_name": "re-mes-app.backend-sales-order.python.dataModelsSalesOrder.SubSalesOrder.initialize",
 "filename": "", "start_line": 0, "end_line": 0}
```

The symbol does exist in the repository and in the graph — `<repo>/backend-sales-order/python/dataModelsSalesOrder/subSalesOrder.py:96-144`
— and the same question returned it with the correct filename in other runs. So this entry is a
lookup that failed, presented as a citation.

Two runs of the **same question at the same depth** minutes apart returned 110 and 52 sources
respectively (a third, `deep`, returned 27), which is consistent with failed lookups being counted as
sources. That count variance is a separate observation and is not proven to be caused by this bug.

## Root cause

`_extract_retrieval_metadata` — `codebase_rag/mcp/server.py:38-93`. The two branches:

```python
if isinstance(content, GraphData):                      # 57
    for row in content.results:
        qualified_name = row.get("qualified_name") or row.get("name")
        filename = row.get("path")
        if not qualified_name or not filename:          # 61  ← validates
            continue
        ...
elif isinstance(content, CodeSnippet):                  # 75
    key = (content.qualified_name, content.file_path)
    if key in seen:
        continue
    sources.append({                                    # 80  ← no validation
        "qualified_name": content.qualified_name,
        "filename": content.file_path,
        "start_line": content.line_start,
        "end_line": content.line_end,
    })
```

`CodeSnippet` (`codebase_rag/schemas.py:35-45`) carries `found: bool = True` and
`error_message: str | None`, and `CodeRetriever.find_code_snippet`
(`codebase_rag/tools/code_retrieval.py:18-86`) sets `found=False` together with
`file_path=""`, `line_start=0`, `line_end=0` and an `error_message` on **all three** failure paths:

- `34-43` — entity not found in graph (`"Entity not found in graph."`)
- `50-59` — graph entry missing location data (`"Graph entry is missing location data."`), with
  `file_path=file_path_str or ""`
- `76-86` — any exception, `error_message=str(e)`

None of `found`, `error_message`, or `source_code` is consulted before the citation is emitted.

**Which of the three paths fired in the observed run is undetermined** — and that is itself the bug:
the returned citation discards `found` and `error_message`, so the caller cannot tell a real citation
from a failed lookup, and neither could this investigation.

A plausible mechanism, **not confirmed**: the lookup query in `code_retrieval.py:22-28` resolves the
path through `OPTIONAL MATCH (m:Module)-[*]-(n) WHERE m._repo_path = $repo_path RETURN … m.path AS path`.
With `OPTIONAL MATCH` plus a filtering `WHERE`, `path` can be `None`, which selects the second failure
path (`50-59`) and yields `filename: ""` with `0,0`. Confirming this needs a run with `found` and
`error_message` logged.

**Disproven hypothesis, recorded so it is not re-chased:** the query references `$repo_path` while
`params = {"qn": qualified_name}` (`code_retrieval.py:29`) contains no `repo_path`, which looks like a
missing-parameter error. It is not: `MemgraphIngestor.fetch_all`
(`codebase_rag/services/graph_service.py:638-648`) injects `repo_path` automatically when absent.

## Proposed fix

1. In `_extract_retrieval_metadata`, do not emit a citation for a failed lookup — mirror the
   `GraphData` guard:

   ```python
   elif isinstance(content, CodeSnippet):
       if not content.found or not content.file_path:
           continue
   ```

2. If failed lookups should stay visible, emit them explicitly marked
   (`{"found": False, "error_message": content.error_message}`) so consumers can distinguish them
   from citations — but do not let them silently inflate `sources`.

## Related improvement in the same function

The `GraphData` branch hard-codes `"start_line": None, "end_line": None`
(`codebase_rag/mcp/server.py:71-72`), so graph-derived citations never carry a line range even though
the graph stores `n.start_line` / `n.end_line` (see `code_retrieval.py:26`). Observable symptom:
`quick_semantic_retrieval` returns entries such as `docs/ADAPTER_MAPPING_ORDER.md:None`. Populating
these from `row.get("start_line")` / `row.get("end_line")` would make graph citations as precise as
snippet ones.

## Acceptance criteria

- [ ] A failed `get_code_snippet` never appears in `sources` as a citation with an empty `filename`.
- [ ] `sources` entries either resolve to an existing path or are explicitly marked unresolved.
- [ ] Graph-derived citations carry `start_line`/`end_line` when the graph has them.

## Related files

- `codebase_rag/mcp/server.py`: `_extract_retrieval_metadata` (38-93); `GraphData` branch (57-74);
  `CodeSnippet` branch (75-87)
- `codebase_rag/tools/code_retrieval.py`: `find_code_snippet` (18-86)
- `codebase_rag/schemas.py`: `CodeSnippet` (35-45)
