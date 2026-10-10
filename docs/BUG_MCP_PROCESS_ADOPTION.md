# Bug: control panel adopts unrelated processes as the MCP server

**Component:** `control_panel/backend/main.py` (MCP lifecycle)
**Versions observed:** `graph-code-mcp` 1.21.1, control panel 0.1.0
**Date observed:** 2026-10-10
**Priority:** High — **Effort:** Small

## Summary

`_live_mcp_pids()` decides whether a graph-code MCP server is already running by matching
process **command lines**: `pgrep -f codebase_rag.main`, then `has_module = any("codebase_rag.main" in a …)`
and `has_mcp = any(… "mcp" in a …)`. Any shell, editor or tool process whose command line happens to
mention both strings is misidentified as a live MCP server. `POST /api/mcp/start` then takes the
"adopt existing" branch, reports `state: running` with the unrelated process's pid, and **never
starts a server**. When the unrelated process exits, the handle flips to `state: error`,
`last_error: "adopted process exited unexpectedly"`.

The result is an MCP endpoint that is reported healthy but is not listening at all.

## Impact

- `POST /api/mcp/start` can return success (`state: running`) while starting nothing; port 8765 stays dead.
- The panel subsequently reports an error for a server that was never started, and the watcher/status
  view becomes misleading.
- `POST /api/mcp/stop` (`_stop_adopted_pid`) and the adopt monitor call `os.killpg()` on the adopted
  pid's **process group**, which is not necessarily one the panel spawned — it can signal unrelated work.
- The failure is hard to attribute, because the adopt branch attaches no log reader, so the adopted
  process's stdout/stderr is never captured (see *Missing diagnostics*).

## Reproduction (observed)

1. Ensure no MCP server is running: `ss -ltn | grep 8765` shows nothing, no `codebase_rag.main`
   python process exists.
2. From a shell whose command line contains **both** `codebase_rag.main` (e.g. as a `pgrep -af` or
   `ps | grep` argument) **and** the substring `mcp` (e.g. because the same command also calls
   `/api/mcp/start`), issue:
   `POST /api/mcp/start {"repo_path": "/home/oliver/gitlab/re-mes-app"}`

**Actual**

- Response: `{"pid": 980521, "state": "running", "repo_path": null, …}`
- Log: `[mcp] adopted existing MCP server (pgid=980521, stopped 0 stale duplicate(s))`
- `ss -ltn | grep 8765` → **not listening**; pid 980521 is the caller's own shell
- Moments later the handle becomes `state: error`, `last_error: "adopted process exited unexpectedly"`

**Expected:** the panel spawns `uv run python -m codebase_rag.main mcp --repo-path … --port 8765`
(the `mcp_start` spawn branch) and 8765 begins listening.

A second POST from a second such shell reproduced it identically with `pgid=980792`. A POST from a
shell with a clean command line (no `codebase_rag.main` substring) started a real server correctly,
confirming the trigger.

## Evidence

`control_panel/backend/main.py:428-453` — the faulty predicate:

```python
out = subprocess.run(["pgrep", "-f", "codebase_rag.main"], capture_output=True, text=True)
...
args = [a.decode(errors="replace") for a in cmdline if a]
has_module = any("codebase_rag.main" in a for a in args)
has_mcp = any(a in ("mcp", "-m") or "mcp" in a for a in args)
if has_module and has_mcp:
    pids.append(pid)
```

`pgrep -f` matches the whole command line; for a shell, the entire `bash -c '…'` script is a single
argument. So `bash -c '… pgrep -af "codebase_rag.main" … /api/mcp/start …'` satisfies both
predicates. Neither `_live_mcp_pids` nor its caller excludes shell wrappers, the panel's own process
tree, or the requesting process.

`control_panel/backend/main.py:1312-1336` — the adopt branch returns early and never reaches the
spawn code at 1338-1394.

`control_panel/backend/main.py:578-586` — the monitored group disappears, so the state becomes:

```python
handle.state = "error"
handle.last_error = "adopted process exited unexpectedly"
```

`control_panel/backend/main.py:503-509` — `_stop_adopted_pid` resolves `os.getpgid(pid)` and calls
`_stop_group_id(pgid)`, i.e. signals a group the panel may not own.

## Proposed fix

Prefer an authoritative liveness probe over process-name matching:

- Probe `http://127.0.0.1:8765/mcp` with a JSON-RPC `initialize` and adopt only when the response
  identifies the expected server — `serverInfo.name == "graph-code-mcp"` (observed: `{"name":
  "graph-code-mcp", "version": "1.21.1"}`). This is what actually distinguishes a running server from
  a process that merely mentions it, and it needs no `pgrep` heuristics.
- At minimum, if process matching is kept:
  - ignore shell/interpreter wrappers (`argv[0]` ending in `sh`, `bash`, `bwrap`, …);
  - require an argument **equal to** `codebase_rag.main` rather than a substring of one argument;
  - require the process to be a python/uv interpreter invocation;
  - exclude the panel's own process tree and the process serving the current request.

## Missing diagnostics (same area, worth fixing together)

The adopt branch creates no `_LineReader`, so `mcp.logs` never receives the adopted process's
stdout/stderr. In the original incident the MCP log held a single line —
`[mcp] adopted existing MCP server (pgid=18664, stopped 0 stale duplicate(s))` — with no crash output,
so the reason that server died could not be determined at all. Adopted processes should have their
output captured just like spawned ones.

## Acceptance criteria

- [ ] With no real server running, `POST /api/mcp/start` spawns one even when the calling shell's
      command line contains both trigger strings.
- [ ] `state: running` implies 8765 answered an `initialize` probe; a phantom pid is never reported
      as running.
- [ ] Adoption and stopping never signal a process group the panel did not spawn.
- [ ] A failed or duplicate adoption leaves a distinguishable line in `mcp.logs`.

## Related files

- `control_panel/backend/main.py`: `_live_mcp_pids` (428-453), `_group_leaders` (456-469),
  `_stop_adopted_pid` (503-509), `_start_adopted_monitor` (558-594), `mcp_start` (1303-1394),
  `mcp_stop` (1396-1412)
