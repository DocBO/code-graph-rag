"""Process discovery, identity probing and shutdown for the panel's processes.

Regression coverage for ``docs/BUG_MCP_PROCESS_ADOPTION.md``: the panel used to
decide "an MCP server/watcher is already running" by matching command-line
substrings against ``pgrep -f`` output, which matched the very shell issuing the
request.
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
from fake_mcp_server import FakeMcpServer

BACKEND_DIR = Path(__file__).resolve().parents[1] / "control_panel" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import panel_processes  # noqa: E402

# The command line the panel's own spawn produces (main.mcp_start).
_REAL_SERVER_ARGV = [
    "uv",
    "run",
    "python",
    "-m",
    "codebase_rag.main",
    "mcp",
    "--repo-path",
    "/home/oliver/gitlab/re-mes-app",
    "--transport",
    "http",
    "--host",
    "127.0.0.1",
    "--port",
    "8765",
    "--path",
    "/mcp",
]

# The observed phantom: a single shell argument carrying both trigger strings.
_PHANTOM_SHELL_ARGV = [
    "bash",
    "-c",
    "pgrep -af codebase_rag.main; curl -sS -X POST "
    "http://127.0.0.1:8008/api/mcp/start -d '{}'",
]

_PHANTOM_BWRAP_ARGV = [
    "bwrap",
    "--ro-bind",
    "/",
    "/",
    "--",
    "bash",
    "-c",
    "python -m codebase_rag.main mcp --port 8765",
]


def test_real_server_invocation_is_recognised() -> None:
    assert panel_processes.is_mcp_server_invocation(_REAL_SERVER_ARGV, 8765)
    # uv resolves `python` to an interpreter, so the child is matched too.
    assert panel_processes.is_mcp_server_invocation(
        ["/repo/.venv/bin/python", "-m", "codebase_rag.main", "mcp", "--port", "8765"],
        8765,
    )
    assert panel_processes.is_mcp_server_invocation(
        ["uv", "run", "python", "-m", "codebase_rag.main", "mcp", "--port=8765"],
        8765,
    )


@pytest.mark.parametrize(
    "argv",
    [_PHANTOM_SHELL_ARGV, _PHANTOM_BWRAP_ARGV],
    ids=["calling-shell", "sandbox-wrapper"],
)
def test_wrappers_are_never_the_server(argv: list[str]) -> None:
    """A wrapper whose command line contains the module is not a server."""
    assert not panel_processes.is_mcp_server_invocation(argv, 8765)


def test_the_removed_substring_predicate_is_what_matched_the_caller() -> None:
    """Pin the root cause: substring matching adopted the calling shell.

    This is the exact predicate ``_live_mcp_pids`` used before the fix. It is kept
    here (rather than only in the bug report) so a future "simplification" back to
    substring matching fails loudly.
    """

    def removed_predicate(args: list[str]) -> bool:
        has_module = any("codebase_rag.main" in arg for arg in args)
        has_mcp = any(arg in ("mcp", "-m") or "mcp" in arg for arg in args)
        return has_module and has_mcp

    assert removed_predicate(_PHANTOM_SHELL_ARGV)
    assert not panel_processes.is_mcp_server_invocation(_PHANTOM_SHELL_ARGV, 8765)


@pytest.mark.parametrize(
    ("argv", "port", "reason"),
    [
        (
            ["python", "-m", "codebase_rag.main", "mcp", "--port", "8766"],
            8765,
            "other port",
        ),
        (["python", "-m", "codebase_rag.main", "mcp"], 8765, "stdio, no port"),
        (
            ["python", "-m", "codebase_rag.main", "serve", "--port", "8765"],
            8765,
            "no mcp sub-command",
        ),
        (
            ["python", "codebase_rag.main", "mcp", "--port", "8765"],
            8765,
            "no -m flag",
        ),
        (
            ["python", "-m", "realtime_updater", "mcp", "--port", "8765"],
            8765,
            "wrong module",
        ),
        (
            ["python", "-m", "codebase_rag.main", "mcp", "--path", "/mcp"],
            8765,
            "path is not a port",
        ),
        ([], 8765, "empty argv"),
    ],
)
def test_near_misses_are_rejected(argv: list[str], port: int, reason: str) -> None:
    assert not panel_processes.is_mcp_server_invocation(argv, port), reason


def test_list_excludes_this_process_tree_and_only_returns_real_servers() -> None:
    pids = panel_processes.list_mcp_server_pids(8765)
    assert not set(pids) & panel_processes.ancestor_pids()
    for pid in pids:
        assert panel_processes.is_mcp_server_invocation(
            panel_processes.read_cmdline(pid), 8765
        )


def test_ancestors_include_this_process() -> None:
    ancestors = panel_processes.ancestor_pids()
    assert os.getpid() in ancestors
    assert all(pid > 0 for pid in ancestors)


# A real watcher invocation, as RepoManager.start_watcher builds it.
_WATCHER_REPO = "/home/oliver/gitlab/addibase"
_REAL_WATCHER_ARGV = [
    "uv",
    "run",
    "python",
    "/home/oliver/github/code-graph-rag/realtime_updater.py",
    _WATCHER_REPO,
    "--host",
    "localhost",
    "--port",
    "7687",
    "--debounce",
    "30",
    "--no-update",
]

# A sandbox wrapper that mentions the script and carries the repo path as a real
# argument — which is exactly how the panel's own command is launched here.
_PHANTOM_WATCHER_ARGV = [
    "bwrap",
    "--bind",
    _WATCHER_REPO,
    _WATCHER_REPO,
    "--",
    "bash",
    "-c",
    "grep -rn realtime_updater.py",
]


def test_real_watcher_invocation_is_recognised() -> None:
    assert panel_processes.is_watcher_invocation(_REAL_WATCHER_ARGV, _WATCHER_REPO)
    assert panel_processes.is_watcher_invocation(
        [
            "/repo/.venv/bin/python",
            "/repo/realtime_updater.py",
            _WATCHER_REPO,
            "--no-update",
        ],
        _WATCHER_REPO,
    )


def test_watcher_near_misses_are_rejected() -> None:
    assert not panel_processes.is_watcher_invocation(
        _PHANTOM_WATCHER_ARGV, _WATCHER_REPO
    )
    # right script, wrong repo: a watcher for another repo is not ours to stop
    assert not panel_processes.is_watcher_invocation(
        _REAL_WATCHER_ARGV, "/home/oliver/gitlab/other"
    )
    # repo path present, but only mentioned inside a wrapper argument
    assert not panel_processes.is_watcher_invocation(
        ["bash", "-c", f"cd {_WATCHER_REPO} && grep realtime_updater.py"],
        _WATCHER_REPO,
    )


def test_list_watcher_pids_only_returns_real_watchers() -> None:
    pids = panel_processes.list_watcher_pids(_WATCHER_REPO)
    assert not set(pids) & panel_processes.ancestor_pids()
    for pid in pids:
        assert panel_processes.is_watcher_invocation(
            panel_processes.read_cmdline(pid), _WATCHER_REPO
        )


@pytest.mark.parametrize("sse", [False, True], ids=["json", "sse"])
def test_probe_identifies_a_graph_code_server(sse: bool) -> None:
    server = FakeMcpServer(sse=sse)
    try:
        result = panel_processes.probe_mcp_server(
            "127.0.0.1", server.port, "/mcp", timeout=3.0
        )
    finally:
        server.close()

    assert result == {
        "alive": True,
        "port_open": True,
        "server_name": "graph-code-mcp",
        "version": "9.9.9",
        "error": None,
    }
    # The probe must not leave its session behind on the server.
    assert server.sessions == set()
    assert server.deleted == {"session-1"}


def test_probe_reports_a_foreign_server_under_its_own_name() -> None:
    server = FakeMcpServer(name="someone-elses-mcp")
    try:
        result = panel_processes.probe_mcp_server(
            "127.0.0.1", server.port, "/mcp", timeout=3.0
        )
    finally:
        server.close()

    assert result["alive"] is True
    assert result["server_name"] == "someone-elses-mcp"
    assert result["port_open"] is True


def test_probe_distinguishes_an_open_port_from_a_verified_server() -> None:
    """Something listening that is not an MCP server must not look alive."""
    server = FakeMcpServer(status=404)
    try:
        result = panel_processes.probe_mcp_server(
            "127.0.0.1", server.port, "/mcp", timeout=3.0
        )
    finally:
        server.close()

    assert result["port_open"] is True
    assert result["alive"] is False
    assert result["server_name"] is None
    assert result["error"]


def test_probe_reports_nothing_listening() -> None:
    result = panel_processes.probe_mcp_server(
        "127.0.0.1", _free_port(), "/mcp", timeout=0.5
    )
    assert result["port_open"] is False
    assert result["alive"] is False
    assert result["server_name"] is None
    assert result["error"]


_GROUP_SCRIPT = """
import os, signal, subprocess, sys, time

CHILD = (
    "import signal, sys, time; "
    "signal.signal(signal.SIGINT, lambda *_: sys.exit(0)); "
    "time.sleep(120)"
)

children = [subprocess.Popen([sys.executable, "-c", CHILD]) for _ in range(2)]
print(children[0].pid, children[1].pid, os.getpgrp(), flush=True)
for child in children:
    child.wait()
"""


def test_stop_pid_never_signals_the_process_group() -> None:
    """Criterion 3: stopping one adopted server must not hit its group siblings.

    Two processes deliberately share a session and process group. Stopping one by
    pid must leave the other (and the group leader) running; the previous
    ``_stop_adopted_pid`` implementation's ``os.killpg`` would take them all down.
    A python leader is used rather than ``bash`` because a non-interactive shell
    starts background jobs with SIGINT ignored, which would make the victim
    survive the SIGINT the panel actually sends.
    """
    leader = subprocess.Popen(
        [sys.executable, "-c", _GROUP_SCRIPT],
        start_new_session=True,
        stdout=subprocess.PIPE,
        text=True,
    )
    assert leader.stdout is not None
    try:
        victim, sibling, pgid = (
            int(value) for value in leader.stdout.readline().split()
        )
        assert pgid == leader.pid  # one session, one group
        assert os.getpgid(victim) == os.getpgid(sibling) == pgid
        victim_cmdline = panel_processes.read_cmdline(victim)

        panel_processes.stop_pid(victim, timeout=5.0)

        assert _wait_until_gone(victim, victim_cmdline), "the victim survived SIGINT"
        assert panel_processes.pid_alive(sibling), "a group sibling was signalled"
        assert panel_processes.pid_alive(leader.pid), "the group leader was signalled"
    finally:
        leader.stdout.close()
        try:
            os.killpg(os.getpgid(leader.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            leader.wait(timeout=5)
        except subprocess.TimeoutExpired:
            leader.kill()


def test_stop_pid_does_not_kill_a_recycled_pid(monkeypatch: pytest.MonkeyPatch) -> None:
    """A pid that changed identity while we waited must not get the SIGKILL.

    The process ignores SIGINT so the escalation path is reached. PID recycling
    cannot be produced on demand, so ``read_cmdline`` is stubbed to report a
    different command line on the second look — the one thing a test cannot
    arrange for real. The child announces itself once SIGINT is actually ignored,
    otherwise the very first signal of a race would kill it.
    """
    stubborn = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import signal, time; signal.signal(signal.SIGINT, signal.SIG_IGN);"
            " print('ready', flush=True); time.sleep(120)",
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    assert stubborn.stdout is not None
    real_read_cmdline = panel_processes.read_cmdline
    calls = {"count": 0}

    def fake_read_cmdline(pid: int) -> list[str]:
        calls["count"] += 1
        if pid == stubborn.pid and calls["count"] > 1:
            return ["some", "other", "process"]
        return real_read_cmdline(pid)

    monkeypatch.setattr(panel_processes, "read_cmdline", fake_read_cmdline)
    try:
        assert stubborn.stdout.readline().strip() == "ready"

        panel_processes.stop_pid(stubborn.pid, timeout=0.5)

        assert calls["count"] > 1, "the escalation path was never reached"
        assert panel_processes.pid_alive(stubborn.pid)
    finally:
        stubborn.stdout.close()
        stubborn.kill()
        stubborn.wait(timeout=5)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_until_gone(pid: int, cmdline: list[str], timeout: float = 5.0) -> bool:
    """True once the *identified* process is gone.

    A bare existence check is not enough: this environment recycles pids within
    milliseconds, so the number can already belong to an unrelated process by the
    time it is inspected. Identity (the command line) is compared instead —
    exactly what ``stop_pid`` does before escalating, and what the panel relies on
    to avoid signalling somebody else's process.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not panel_processes.pid_alive(pid):
            return True
        if cmdline and panel_processes.read_cmdline(pid) != cmdline:
            return True
        time.sleep(0.05)
    return False
