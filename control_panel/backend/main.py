"""
Control panel backend for Graph-Code RAG.

Manages a persisted repository list, per-repo real-time watcher subprocesses
(``realtime_updater.py``) and a single unified MCP server (HTTP transport).
All endpoints are unauthenticated and intended for localhost only.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shlex
import signal
import socket
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Literal

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = Path(__file__).resolve().parent / "data"
REPOS_FILE = DATA_DIR / "repos.json"

# Make the Graph-Code package importable from this backend (it lives in the
# project root, not in control_panel/backend where uvicorn runs).
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

MEMGRAPH_HOST = os.environ.get("MEMGRAPH_HOST", "localhost")
MEMGRAPH_PORT = int(os.environ.get("MEMGRAPH_PORT", "7687"))
MCP_HOST = os.environ.get("MCP_HOST", "127.0.0.1")
MCP_PORT = int(os.environ.get("MCP_PORT", "8765"))
MCP_PATH = os.environ.get("MCP_PATH", "/mcp")

DEFAULT_DEBOUNCE = 30
DEFAULT_BATCH_SIZE = 2000
LOG_LIMIT = 400
# An MCP server that neither binds its port nor prints a startup line within
# this many seconds is killed and marked "error" instead of leaving the
# dashboard stuck on "starting". Watchers use no timeout because a full-scan
# watcher legitimately stays "starting" for the whole initial ingestion.
MCP_START_TIMEOUT = float(os.environ.get("MCP_START_TIMEOUT", "120"))

app = FastAPI(title="Graph-Code RAG Control Panel")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3003",
        "http://127.0.0.1:3003",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------
# Models
# --------------------------------------------------------------------------


class RepoConfig(BaseModel):
    path: str
    debounce: int = Field(default=DEFAULT_DEBOUNCE, ge=1)
    batch_size: int | None = Field(default=DEFAULT_BATCH_SIZE, ge=1)
    no_update: bool = True


class AddRepoRequest(BaseModel):
    path: str
    debounce: int = Field(default=DEFAULT_DEBOUNCE, ge=1)
    batch_size: int | None = Field(default=DEFAULT_BATCH_SIZE, ge=1)
    no_update: bool = True


class StartWatcherRequest(BaseModel):
    full_scan: bool = False
    debounce: int | None = Field(default=None, ge=1)
    batch_size: int | None = Field(default=None, ge=1)


class McpStartRequest(BaseModel):
    repo_path: str | None = None


class QueryRequest(BaseModel):
    repo_path: str
    question: str
    search_depth: Literal["shallow", "normal", "deep"] = "normal"


class SemanticSearchRequest(BaseModel):
    repo_path: str
    search_phrase: str
    top_n: int = 5


# --------------------------------------------------------------------------
# Runtime state
# --------------------------------------------------------------------------


class WatcherHandle:
    """Tracks one watcher subprocess plus parsed runtime status."""

    def __init__(self) -> None:
        self.proc: subprocess.Popen[str] | None = None
        self.adopted_pid: int | None = None
        self.state = "stopped"  # stopped | starting | running | stopping | error
        self.update_in_progress = False
        self.last_update_at: float | None = None
        self.last_update_duration: float | None = None
        self.last_error: str | None = None
        self.logs: deque[str] = deque(maxlen=LOG_LIMIT)
        self._reader: threading.Thread | None = None
        self._monitor: threading.Thread | None = None

    def pid(self) -> int | None:
        if self.proc is not None:
            return self.proc.pid
        return self.adopted_pid

    def status(self) -> dict[str, Any]:
        return {
            "pid": self.pid(),
            "state": self.state,
            "update_in_progress": self.update_in_progress,
            "last_update_at": self.last_update_at,
            "last_update_duration": self.last_update_duration,
            "last_error": self.last_error,
            "log_count": len(self.logs),
        }


class McpHandle:
    def __init__(self) -> None:
        self.proc: subprocess.Popen[str] | None = None
        self.adopted_pid: int | None = None
        self.state = "stopped"  # stopped | starting | running | stopping | error
        self.repo_path: str | None = None
        self.last_error: str | None = None
        self.logs: deque[str] = deque(maxlen=LOG_LIMIT)
        self._reader: threading.Thread | None = None
        self._monitor: threading.Thread | None = None

    def pid(self) -> int | None:
        if self.proc is not None:
            return self.proc.pid
        return self.adopted_pid

    def status(self) -> dict[str, Any]:
        return {
            "pid": self.pid(),
            "state": self.state,
            "repo_path": self.repo_path,
            "url": f"http://{MCP_HOST}:{MCP_PORT}{MCP_PATH}",
            "last_error": self.last_error,
            "log_count": len(self.logs),
        }


# --------------------------------------------------------------------------
# Process helpers
# --------------------------------------------------------------------------


_UPDATE_START_PATTERNS = (
    re.compile(r"Starting graph update"),
    re.compile(r"Performing initial full codebase scan"),
)
_UPDATE_END_PATTERNS = (
    re.compile(r"Graph update completed"),
    re.compile(r"Initial scan complete"),
)
_UPDATE_FAIL_PATTERN = re.compile(r"Graph update failed")


def _classify_update_line(line: str) -> str | None:
    """Return 'start', 'end' or 'fail' for update-progress lines, else None."""
    if any(p.search(line) for p in _UPDATE_START_PATTERNS):
        return "start"
    if _UPDATE_FAIL_PATTERN.search(line):
        return "fail"
    if any(p.search(line) for p in _UPDATE_END_PATTERNS):
        return "end"
    return None


class _LineReader(threading.Thread):
    """Reads a subprocess stdout pipe, tailing lines into a deque."""

    def __init__(
        self,
        proc: subprocess.Popen[str],
        logs: deque[str],
        tag: str,
        on_line: Any = None,
    ) -> None:
        super().__init__(daemon=True)
        self.proc = proc
        self.logs = logs
        self.tag = tag
        self.on_line = on_line

    def run(self) -> None:
        assert self.proc.stdout is not None
        for raw in self.proc.stdout:
            line = raw.rstrip("\n")
            self.logs.append(f"{self.tag}: {line}" if self.tag else line)
            if self.on_line:
                self.on_line(line)


def _spawn(
    cmd: list[str],
    env: dict[str, str] | None = None,
) -> subprocess.Popen[str]:
    """Spawn a process in its own session (so we can SIGINT the whole group)."""
    full_env = os.environ.copy()
    full_env["MEMGRAPH_HOST"] = MEMGRAPH_HOST
    full_env["MEMGRAPH_PORT"] = str(MEMGRAPH_PORT)
    if env:
        full_env.update(env)
    return subprocess.Popen(
        cmd,
        cwd=str(PROJECT_ROOT),
        env=full_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        start_new_session=True,
    )


def _stop_group(proc: subprocess.Popen[str]) -> None:
    """SIGINT the process group, escalating to SIGKILL."""
    if proc.poll() is not None:
        return
    pgid = os.getpgid(proc.pid)
    try:
        os.killpg(pgid, signal.SIGINT)
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(pgid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        proc.wait(timeout=5)
    except (ProcessLookupError, PermissionError):
        pass


def _live_watcher_pids(repo_path: str) -> list[int]:
    """Return all pids running realtime_updater.py for repo_path."""
    try:
        out = subprocess.run(
            ["pgrep", "-f", "realtime_updater.py"],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return []
    pids: list[int] = []
    for pid_str in out.stdout.split():
        try:
            pid = int(pid_str)
        except ValueError:
            continue
        try:
            cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\x00")
        except OSError:
            continue
        args = [a.decode(errors="replace") for a in cmdline if a]
        if any("realtime_updater.py" in a for a in args) and repo_path in args:
            pids.append(pid)
    return pids


def _live_mcp_pids() -> list[int]:
    """Return all pids running the graph-code MCP server."""
    try:
        out = subprocess.run(
            ["pgrep", "-f", "codebase_rag.main"],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return []
    pids: list[int] = []
    for pid_str in out.stdout.split():
        try:
            pid = int(pid_str)
        except ValueError:
            continue
        try:
            cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\x00")
        except OSError:
            continue
        args = [a.decode(errors="replace") for a in cmdline if a]
        has_module = any("codebase_rag.main" in a for a in args)
        has_mcp = any(a in ("mcp", "-m") or "mcp" in a for a in args)
        if has_module and has_mcp:
            pids.append(pid)
    return pids


def _group_leaders(pids: list[int]) -> list[int]:
    """Collapse pids into process-group leaders (one per spawned process).

    Each watcher/MCP server is started via ``_spawn`` (start_new_session=True),
    so the ``uv run`` wrapper is the session/group leader and its python child
    shares that group. Sorting by pid yields oldest->newest group leaders.
    """
    groups: set[int] = set()
    for pid in pids:
        try:
            groups.add(os.getpgid(pid))
        except (ProcessLookupError, PermissionError):
            continue
    return sorted(groups)


def _find_live_watcher_group(repo_path: str) -> int | None:
    """Return the process-group id of the newest live watcher for repo_path."""
    leaders = _group_leaders(_live_watcher_pids(repo_path))
    return leaders[-1] if leaders else None


def _find_live_mcp_group() -> int | None:
    """Return the process-group id of the newest live MCP server."""
    leaders = _group_leaders(_live_mcp_pids())
    return leaders[-1] if leaders else None


def _stop_group_id(pgid: int) -> None:
    """SIGINT a process group by id, escalating to SIGKILL."""
    try:
        os.killpg(pgid, signal.SIGINT)
    except (ProcessLookupError, PermissionError):
        return
    deadline = time.time() + 8
    while time.time() < deadline:
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.2)
    try:
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def _stop_adopted_pid(pid: int) -> None:
    """SIGINT an adopted (not child) process group, then SIGKILL if needed."""
    try:
        pgid = os.getpgid(pid)
    except (ProcessLookupError, PermissionError):
        return
    _stop_group_id(pgid)


def _start_monitor(
    proc: subprocess.Popen[str],
    handle: WatcherHandle | McpHandle,
    on_exit: Any,
    start_timeout: float = 0.0,
) -> threading.Thread:
    """Spawn a daemon thread that watches a process and updates handle state on exit.

    While the handle is in "starting" the thread polls for an early exit (the
    process died before reaching "running", e.g. a spawn that never printed its
    readiness line) and, when ``start_timeout`` > 0, escalates a hang to
    "error" so the dashboard never stays stuck on "starting" forever.
    """

    def _watch() -> None:
        deadline = time.time() + start_timeout if start_timeout > 0 else float("inf")
        while handle.state == "starting":
            rc = proc.poll()
            if rc is not None:
                handle.proc = None
                handle.state = "error"
                handle.last_error = f"process exited with code {rc}"
                on_exit(handle)
                return
            if time.time() > deadline:
                handle.proc = None
                handle.state = "error"
                handle.last_error = f"startup timed out after {int(start_timeout)}s"
                _stop_group(proc)
                on_exit(handle)
                return
            time.sleep(0.5)
        proc.wait()
        handle.proc = None
        if handle.state == "stopping":
            handle.state = "stopped"
        else:
            handle.state = "error"
            handle.last_error = f"process exited with code {proc.returncode}"
            on_exit(handle)

    thread = threading.Thread(target=_watch, daemon=True)
    thread.start()
    return thread


def _start_adopted_monitor(
    pgid: int,
    handle: WatcherHandle | McpHandle,
    on_exit: Any = None,
) -> threading.Thread:
    """Spawn a daemon thread that watches an adopted (non-child) process group.

    Adopted processes have no Popen handle, so liveness is polled via the
    process group. An unexpected exit moves the handle to "error" (with a
    readable message); a stop issued through the control panel leaves it
    "stopped".
    """

    def _watch() -> None:
        while True:
            if handle.state != "running":
                handle.adopted_pid = None
                if handle.state == "stopping":
                    handle.state = "stopped"
                return
            try:
                os.killpg(pgid, 0)
            except (ProcessLookupError, PermissionError):
                handle.adopted_pid = None
                if handle.state == "stopping":
                    handle.state = "stopped"
                else:
                    handle.state = "error"
                    handle.last_error = "adopted process exited unexpectedly"
                    if on_exit:
                        on_exit(handle)
                return
            time.sleep(1)

    thread = threading.Thread(target=_watch, daemon=True)
    thread.start()
    return thread


# --------------------------------------------------------------------------
# Memgraph liveness probe
# --------------------------------------------------------------------------


_MEMGRAPH_PROBE_LOCK = threading.Lock()
_MEMGRAPH_PROBE_CACHE: dict[str, Any] = {"at": 0.0, "alive": False, "error": None}


def _probe_memgraph_liveness(
    host: str | None = None,
    port: int | None = None,
    timeout: float = 2.0,
) -> dict[str, Any]:
    """Return a lightweight liveness probe result for the Memgraph Bolt port.

    Uses a short TCP connect so the dashboard can show whether Memgraph is
    actually reachable without pulling in the full Bolt driver or blocking the
    status endpoint. Results are cached for a short interval to keep the
    probe cheap while the UI polls every few seconds.
    """
    host = host or MEMGRAPH_HOST
    port = port or MEMGRAPH_PORT
    now = time.time()
    with _MEMGRAPH_PROBE_LOCK:
        if now - _MEMGRAPH_PROBE_CACHE["at"] < 2.0:
            return dict(_MEMGRAPH_PROBE_CACHE)
        try:
            with socket.create_connection((host, port), timeout=timeout):
                alive = True
            error = None
        except Exception as exc:  # noqa: BLE001 - surface any connection failure
            alive = False
            error = str(exc)
        _MEMGRAPH_PROBE_CACHE.update(
            {"at": time.time(), "alive": alive, "error": error}
        )
        return dict(_MEMGRAPH_PROBE_CACHE)


# --------------------------------------------------------------------------
# Repository manager
# --------------------------------------------------------------------------


class RepoManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._repos: dict[str, RepoConfig] = {}
        self._watchers: dict[str, WatcherHandle] = {}
        self.mcp = McpHandle()
        self._load()
        self._adopt_running_processes()

    def _adopt_running_processes(self) -> None:
        """Reconcile watcher/MCP processes left running by a previous backend
        instance (e.g. after uvicorn --reload re-created this module).

        Without this the dashboard shows them as stopped and a new start
        spawns a duplicate process — two watchers then write the same files
        concurrently and Memgraph aborts one with a transaction conflict.

        Watchers are re-spawned (not adopted): the previous instance owned
        their stdout pipe, so adoption would leave the dashboard without
        update-progress tracking. The MCP server is stateless and does not
        stream update progress, so it can be adopted directly.
        """
        for key, cfg in self._repos.items():
            groups = _group_leaders(_live_watcher_pids(cfg.path))
            if not groups:
                continue
            for group in groups:
                _stop_group_id(group)
            try:
                handle = self.start_watcher(key)
                handle.logs.append(
                    "[watcher] re-spawned after backend restart "
                    "(previous instance was reloaded)"
                )
            except HTTPException:
                continue

        mcp_groups = _group_leaders(_live_mcp_pids())
        if mcp_groups:
            for stale in mcp_groups[:-1]:
                _stop_group_id(stale)
            self.mcp.proc = None
            self.mcp.last_error = None
            self.mcp.adopted_pid = mcp_groups[-1]
            self.mcp.state = "running"
            self.mcp.logs.append(
                f"[mcp] adopted existing MCP server (pgid={mcp_groups[-1]}, "
                f"stopped {len(mcp_groups) - 1} stale duplicate(s))"
            )
            self.mcp._monitor = _start_adopted_monitor(mcp_groups[-1], self.mcp)

    # -- persistence ------------------------------------------------------

    def _load(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if REPOS_FILE.exists():
            try:
                raw = json.loads(REPOS_FILE.read_text())
                for item in raw:
                    cfg = RepoConfig(**item)
                    key = str(Path(cfg.path).expanduser().resolve())
                    self._repos[key] = cfg
            except (json.JSONDecodeError, TypeError):
                pass

    def _save(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        data = [cfg.model_dump() for cfg in self._repos.values()]
        REPOS_FILE.write_text(json.dumps(data, indent=2))

    # -- repo CRUD --------------------------------------------------------

    def list_repos(self) -> list[dict[str, Any]]:
        with self._lock:
            out = []
            for path, cfg in self._repos.items():
                handle = self._watchers.get(path) or WatcherHandle()
                out.append(self._repo_status(cfg, handle))
            return sorted(out, key=lambda r: r["path"].lower())

    def add_repo(self, req: AddRepoRequest) -> dict[str, Any]:
        path = str(Path(req.path).expanduser().resolve())
        if not Path(path).is_dir():
            raise HTTPException(400, f"Not a directory: {path}")
        with self._lock:
            if path in self._repos:
                raise HTTPException(409, f"Repo already registered: {path}")
            cfg = RepoConfig(
                path=path,
                debounce=req.debounce,
                batch_size=req.batch_size,
                no_update=req.no_update,
            )
            self._repos[path] = cfg
            self._save()
            return self._repo_status(cfg, WatcherHandle())

    def remove_repo(self, path: str) -> dict[str, Any]:
        key = str(Path(path).expanduser().resolve())
        self.stop_watcher(key)
        with self._lock:
            if key not in self._repos:
                raise HTTPException(404, f"Unknown repo: {path}")
            del self._repos[key]
            self._watchers.pop(key, None)
            self._save()

        # Removing a repo should also purge its per-repo data (graph nodes in
        # Memgraph and vectors in Qdrant) so a stale index never resurfaces.
        return {"deleted": key, "cleanup": self._cleanup_repo_databases(key)}

    def _cleanup_repo_databases(self, repo_path: str) -> dict[str, str]:
        """Best-effort removal of per-repo data from Memgraph and Qdrant."""
        cleanup: dict[str, str] = {}

        try:
            from codebase_rag.services.graph_service import MemgraphIngestor

            with MemgraphIngestor(
                host=MEMGRAPH_HOST,
                port=MEMGRAPH_PORT,
                repo_path=repo_path,
                connect_retries=1,
            ) as ingestor:
                ingestor.clean_database()
            cleanup["memgraph"] = "cleaned"
        except Exception as exc:
            logger.warning("Failed to clean Memgraph data for %s: %s", repo_path, exc)
            cleanup["memgraph"] = f"error: {exc}"

        try:
            from codebase_rag.vector_store import clean_collection

            clean_collection(repo_path)
            cleanup["qdrant"] = "cleaned"
        except Exception as exc:
            logger.warning("Failed to clean Qdrant data for %s: %s", repo_path, exc)
            cleanup["qdrant"] = f"error: {exc}"

        return cleanup

    def get_repo(self, path: str) -> tuple[RepoConfig, WatcherHandle]:
        key = str(Path(path).expanduser().resolve())
        with self._lock:
            cfg = self._repos.get(key)
            if cfg is None:
                raise HTTPException(404, f"Unknown repo: {path}")
            return cfg, (self._watchers.get(key) or WatcherHandle())

    def _repo_status(self, cfg: RepoConfig, handle: WatcherHandle) -> dict[str, Any]:
        return {
            "path": cfg.path,
            "name": Path(cfg.path).name or cfg.path,
            "debounce": cfg.debounce,
            "batch_size": cfg.batch_size,
            "no_update": cfg.no_update,
            "watcher": handle.status(),
        }

    # -- watcher lifecycle ------------------------------------------------

    def start_watcher(
        self,
        path: str,
        full_scan: bool = False,
        debounce: int | None = None,
        batch_size: int | None = None,
    ) -> WatcherHandle:
        key = str(Path(path).expanduser().resolve())
        cfg, _ = self.get_repo(key)

        def _on_exit(h: WatcherHandle) -> None:
            if h.update_in_progress:
                h.update_in_progress = False

        with self._lock:
            handle = self._watchers.get(key) or WatcherHandle()
            if handle.proc and handle.proc.poll() is None:
                raise HTTPException(409, f"Watcher already running for {key}")
            # A live watcher left over from a previous backend process (e.g.
            # after uvicorn --reload restarted the module) must not be started
            # a second time — that produces concurrent writers and Memgraph
            # transaction conflicts. Stop stale duplicates and adopt the newest.
            groups = _group_leaders(_live_watcher_pids(cfg.path))
            if groups:
                for stale in groups[:-1]:
                    _stop_group_id(stale)
                handle.proc = None
                handle.update_in_progress = False
                handle.last_error = None
                handle.adopted_pid = groups[-1]
                handle.state = "running"
                self._watchers[key] = handle
                handle.logs.append(
                    f"[watcher] adopted existing watcher (pgid={groups[-1]}, "
                    f"stopped {len(groups) - 1} stale duplicate(s))"
                )
                handle._monitor = _start_adopted_monitor(groups[-1], handle, _on_exit)
                return handle
            self._watchers[key] = handle

        effective_debounce = debounce or cfg.debounce
        effective_batch = batch_size or cfg.batch_size
        no_update = not full_scan and cfg.no_update

        cmd = [
            "uv",
            "run",
            "python",
            str(PROJECT_ROOT / "realtime_updater.py"),
            cfg.path,
            "--host",
            MEMGRAPH_HOST,
            "--port",
            str(MEMGRAPH_PORT),
            "--debounce",
            str(effective_debounce),
        ]
        if effective_batch:
            cmd += ["--batch-size", str(effective_batch)]
        if no_update:
            cmd.append("--no-update")

        try:
            proc = _spawn(cmd)
        except FileNotFoundError as exc:
            handle.state = "error"
            handle.last_error = f"uv not found: {exc}"
            raise HTTPException(500, handle.last_error)

        handle.proc = proc
        handle.state = "starting"
        handle.update_in_progress = full_scan
        handle.last_error = None
        handle.logs.append(f"[watcher] starting: {shlex.join(cmd)}")

        handle._reader = _LineReader(
            proc,
            handle.logs,
            "watcher",
            on_line=lambda line: self._tick_watcher(key, line),
        )
        handle._reader.start()
        handle._monitor = _start_monitor(proc, handle, _on_exit)

        return handle

    def stop_watcher(self, path: str) -> None:
        cfg, handle = self.get_repo(path)
        proc = handle.proc
        if proc is None and handle.adopted_pid is None:
            if handle.state not in ("starting", "running"):
                return
        handle.state = "stopping"
        handle.update_in_progress = False
        if proc is not None:
            _stop_group(proc)
        elif handle.adopted_pid is not None:
            _stop_adopted_pid(handle.adopted_pid)
            handle.adopted_pid = None
            handle.state = "stopped"

    # -- log parsing (called by readers) ----------------------------------

    def _tick_watcher(self, path: str, line: str) -> None:
        handle = self._watchers.get(path)
        if handle is None:
            return
        kind = _classify_update_line(line)
        if kind == "start":
            handle.update_in_progress = True
            handle.last_update_at = time.time()
        elif kind == "end":
            if handle.last_update_at:
                handle.last_update_duration = time.time() - handle.last_update_at
            handle.update_in_progress = False
        elif kind == "fail":
            handle.last_error = line
            handle.update_in_progress = False
        if handle.state == "starting" and (
            "Watching for changes" in line or "File watcher is now active" in line
        ):
            handle.state = "running"

    def _tick_mcp(self, line: str) -> None:
        mcp = self.mcp
        if mcp.state == "starting" and (
            "Uvicorn running on" in line or "Application startup complete" in line
        ):
            mcp.state = "running"


# --------------------------------------------------------------------------
# Managers (singletons)
# --------------------------------------------------------------------------


manager = RepoManager()


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------


@app.get("/")
def root() -> dict[str, Any]:
    return {
        "service": "graph-code-rag-control",
        "docs": "/docs",
        "project_root": str(PROJECT_ROOT),
    }


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"status": "ok"}


@app.get("/api/status")
def status() -> dict[str, Any]:
    memgraph = _probe_memgraph_liveness()
    return {
        "repos": manager.list_repos(),
        "mcp": manager.mcp.status(),
        "memgraph": memgraph,
        "config": {
            "project_root": str(PROJECT_ROOT),
            "memgraph": {"host": MEMGRAPH_HOST, "port": MEMGRAPH_PORT},
            "mcp": {"host": MCP_HOST, "port": MCP_PORT, "path": MCP_PATH},
            "default_debounce": DEFAULT_DEBOUNCE,
            "default_batch_size": DEFAULT_BATCH_SIZE,
        },
    }


@app.get("/api/repos")
def list_repos() -> list[dict[str, Any]]:
    return manager.list_repos()


@app.post("/api/repos", status_code=201)
def add_repo(req: AddRepoRequest) -> dict[str, Any]:
    return manager.add_repo(req)


@app.delete("/api/repos/{path:path}")
def delete_repo(path: str) -> dict[str, Any]:
    return manager.remove_repo(path)


@app.get("/api/repos/{path:path}/logs")
def repo_logs(path: str, limit: int = 200) -> list[str]:
    _, handle = manager.get_repo(path)
    return list(handle.logs)[-limit:]


@app.post("/api/repos/{path:path}/watch/start")
def start_watcher(path: str, req: StartWatcherRequest) -> dict[str, Any]:
    manager.get_repo(path)
    handle = manager.start_watcher(
        path,
        full_scan=req.full_scan,
        debounce=req.debounce,
        batch_size=req.batch_size,
    )
    return handle.status()


@app.post("/api/repos/{path:path}/watch/stop")
def stop_watcher(path: str) -> dict[str, Any]:
    manager.stop_watcher(path)
    _, handle = manager.get_repo(path)
    return handle.status()


# -- unified MCP server -----------------------------------------------------


@app.post("/api/mcp/start")
def mcp_start(req: McpStartRequest) -> dict[str, Any]:
    mcp = manager.mcp
    if mcp.proc and mcp.proc.poll() is None:
        raise HTTPException(409, "MCP server already running")
    # Reconcile with any live MCP server instead of trying to start a second
    # one on the same port: adopt the newest group (or keep the already-adopted
    # one) and stop stale duplicates. Applies even when the handle still holds
    # an adopted_pid from a previous run or reload.
    mcp_groups = _group_leaders(_live_mcp_pids())
    if mcp_groups:
        keep = (
            mcp.adopted_pid
            if mcp.adopted_pid is not None and mcp.adopted_pid in mcp_groups
            else mcp_groups[-1]
        )
        for stale in mcp_groups:
            if stale != keep:
                _stop_group_id(stale)
        mcp.proc = None
        mcp.last_error = None
        mcp.adopted_pid = keep
        mcp.state = "running"
        mcp.logs.append(
            f"[mcp] adopted existing MCP server (pgid={keep}, "
            f"stopped {len(mcp_groups) - 1} stale duplicate(s))"
        )
        mcp._monitor = _start_adopted_monitor(keep, mcp)
        return mcp.status()

    repo_path = req.repo_path
    if repo_path is None:
        repos = manager.list_repos()
        repo_path = repos[0]["path"] if repos else None
    if repo_path is None:
        raise HTTPException(400, "No repos registered and no repo_path provided")

    cmd = [
        "uv",
        "run",
        "python",
        "-m",
        "codebase_rag.main",
        "mcp",
        "--repo-path",
        repo_path,
        "--transport",
        "http",
        "--host",
        MCP_HOST,
        "--port",
        str(MCP_PORT),
        "--path",
        MCP_PATH,
    ]

    try:
        proc = _spawn(cmd)
    except FileNotFoundError as exc:
        mcp.state = "error"
        mcp.last_error = f"uv not found: {exc}"
        raise HTTPException(500, mcp.last_error)

    mcp.proc = proc
    mcp.state = "starting"
    mcp.repo_path = repo_path
    mcp.last_error = None
    mcp.logs.append(f"[mcp] starting: {shlex.join(cmd)}")

    def _on_exit(h: McpHandle) -> None:
        pass

    mcp._reader = _LineReader(
        proc,
        mcp.logs,
        "mcp",
        on_line=manager._tick_mcp,
    )
    mcp._reader.start()
    mcp._monitor = _start_monitor(proc, mcp, _on_exit, start_timeout=MCP_START_TIMEOUT)
    return mcp.status()


@app.post("/api/mcp/stop")
def mcp_stop() -> dict[str, Any]:
    mcp = manager.mcp
    if mcp.proc is None and mcp.adopted_pid is None:
        if mcp.state not in ("starting", "running"):
            return mcp.status()
    mcp.state = "stopping"
    if mcp.proc is not None:
        _stop_group(mcp.proc)
    elif mcp.adopted_pid is not None:
        _stop_adopted_pid(mcp.adopted_pid)
        mcp.adopted_pid = None
        mcp.state = "stopped"
    return mcp.status()


@app.get("/api/mcp/logs")
def mcp_logs(limit: int = 200) -> list[str]:
    return list(manager.mcp.logs)[-limit:]


# -- RAG query (query_codebase) -----------------------------------------------


@app.post("/api/query")
def run_query(req: QueryRequest) -> dict[str, Any]:
    """Run the RAG query_codebase flow against a registered repo.

    Returns the agent's markdown answer plus the repo path that produced it.
    """
    manager.get_repo(req.repo_path)
    try:
        import asyncio

        from codebase_rag.mcp.server import GraphCodeMCPContext

        context = GraphCodeMCPContext(
            repo_path=str(Path(req.repo_path).expanduser().resolve()),
            batch_size=DEFAULT_BATCH_SIZE,
        )
        result = asyncio.run(
            context.query_codebase(
                question=req.question,
                search_depth=req.search_depth,
            )
        )
        return {
            "repo_path": result.get("repo_path", req.repo_path),
            "question": req.question,
            "search_depth": result.get("search_depth", req.search_depth),
            "response": result.get("response", ""),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f"Query failed: {exc}") from exc


# -- Quick semantic retrieval (quick_semantic_retrieval) ------------------------


@app.post("/api/semantic")
def run_semantic(req: SemanticSearchRequest) -> dict[str, Any]:
    """Run the quick_semantic_retrieval flow against a registered repo.

    Returns semantic snippet matches with filename/line metadata and scores,
    useful for debugging why a search phrase returns few or no matches.
    """
    manager.get_repo(req.repo_path)
    try:
        import asyncio

        from codebase_rag.mcp.server import GraphCodeMCPContext

        context = GraphCodeMCPContext(
            repo_path=str(Path(req.repo_path).expanduser().resolve()),
            batch_size=DEFAULT_BATCH_SIZE,
        )
        result = asyncio.run(
            context.quick_semantic_retrieval(
                search_phrase=req.search_phrase,
                top_n=req.top_n,
            )
        )
        return {
            "repo_path": result.get("repo_path", req.repo_path),
            "search_phrase": req.search_phrase,
            "top_n": req.top_n,
            "matches": result.get("matches", []),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f"Semantic search failed: {exc}") from exc


if __name__ == "__main__":
    port = int(os.environ.get("CONTROL_PORT", "8008"))
    uvicorn.run(app, host="0.0.0.0", port=port)
