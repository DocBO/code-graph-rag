"""Discover, verify and stop the processes the control panel manages.

The panel must never mistake a process that merely *mentions* a managed program —
a shell running ``pgrep``/``grep``, a sandbox wrapper, an editor buffer — for a
live MCP server or watcher (see ``docs/BUG_MCP_PROCESS_ADOPTION.md``). MCP
liveness is decided by an ``initialize`` round-trip against the configured
endpoint, and process inspection is used only to attribute the answering server
to a pid so it can be reported, monitored and stopped. Watcher matches use exact
arguments instead of substrings.

Signals are sent to a single pid, never to a process group: an adopted server is
by definition not a child of the panel, and its group may contain unrelated work.

The module has no import-time side effects, so it can be imported (and tested)
without constructing the panel's ``RepoManager``.
"""

from __future__ import annotations

import json
import os
import signal
import socket
import sys
import time
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MCP_SERVER_NAME = "graph-code-mcp"

WATCHER_SCRIPT_NAME = "realtime_updater.py"

_PROTOCOL_VERSION = "2025-06-18"
_PROBE_CLIENT_NAME = "graph-code-control-panel"

# argv[0] names that *wrap* another command. A wrapper's own command line may
# contain the module or script name (``bash -c '… codebase_rag.main …'``) without
# being the program, so it is never treated as one.
_WRAPPER_ARGV0 = frozenset(
    {
        "sh",
        "bash",
        "dash",
        "zsh",
        "ksh",
        "fish",
        "csh",
        "tcsh",
        "bwrap",
        "env",
        "timeout",
        "setsid",
        "nohup",
        "sudo",
        "doas",
        "script",
        "xargs",
        "watch",
        "pgrep",
        "pkill",
        "grep",
        "rg",
    }
)


@dataclass(frozen=True)
class McpServerProcesses:
    """The processes of one MCP server invocation, grouped by process group."""

    pgid: int
    pids: tuple[int, ...]

    @property
    def pid(self) -> int:
        """The newest process of the invocation.

        A single ``uv run python -m codebase_rag.main mcp …`` shows up as at
        least the ``uv`` wrapper plus the python child; the python child has the
        higher pid and is the process that owns the listening socket.
        """
        return self.pids[-1]


# --------------------------------------------------------------------------
# Process inspection
# --------------------------------------------------------------------------


def read_cmdline(pid: int) -> list[str]:
    """Return the NUL-separated argv of ``pid``, or [] when unreadable."""
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return []
    return [arg.decode("utf-8", "replace") for arg in raw.split(b"\x00") if arg]


def _has_module_flag(args: list[str], module: str) -> bool:
    return any(arg == "-m" and args[i + 1] == module for i, arg in enumerate(args[:-1]))


def _has_port(args: list[str], port: int) -> bool:
    wanted = str(port)
    for index, arg in enumerate(args):
        if arg == "--port" and index + 1 < len(args) and args[index + 1] == wanted:
            return True
        if arg == f"--port={wanted}":
            return True
    return False


def _option_value(args: list[str], option: str, default: str) -> str:
    for index, arg in enumerate(args):
        if arg == option and index + 1 < len(args):
            return args[index + 1]
        if arg.startswith(f"{option}="):
            return arg.split("=", 1)[1]
    return default


def is_mcp_server_invocation(
    args: list[str], port: int, host: str | None = None, path: str | None = None
) -> bool:
    """True only for a real ``… -m codebase_rag.main mcp … --port <port>`` call.

    Every predicate is an exact argument comparison. Matching substrings against
    a whole command line is what made the panel adopt the shell that issued the
    request: ``bash -c '… pgrep -f codebase_rag.main … /api/mcp/start …'``
    contains both trigger strings inside a single argument.
    """
    if not args:
        return False
    if Path(args[0]).name in _WRAPPER_ARGV0:
        return False
    # The ``mcp`` sub-command must stand alone — ``--path /mcp`` must not count.
    if "mcp" not in args:
        return False
    if not _has_module_flag(args, "codebase_rag.main"):
        return False
    # Restrict to servers serving *our* port so an unrelated stdio server, or one
    # for another port, is never reported or signalled.
    if _option_value(args, "--transport", "stdio").lower() != "http":
        return False
    if host is not None and _option_value(args, "--host", "127.0.0.1") != host:
        return False
    if path is not None and _option_value(args, "--path", "/mcp") != path:
        return False
    return _has_port(args, port)


def is_watcher_invocation(args: list[str], repo_path: str) -> bool:
    """True only for a real ``python <…>/realtime_updater.py <repo_path> …`` run.

    ``realtime_updater.py`` is matched as a whole path component and ``repo_path``
    as a whole argument. The previous check matched the script name as a substring
    anywhere in the command line, so a sandbox wrapper such as
    ``bwrap --bind <repo> <repo> -- bash -c 'grep realtime_updater.py'`` counted as
    a watcher — and the panel then SIGINTs the *group* of anything it finds.
    """
    if not args:
        return False
    if Path(args[0]).name in _WRAPPER_ARGV0:
        return False
    interpreter = 0
    if Path(args[0]).name == "uv":
        if len(args) < 4 or args[1:3] != ["run", "python"]:
            return False
        interpreter = 2
    elif not Path(args[0]).name.startswith(("python", "pypy")):
        return False
    script_index = interpreter + 1
    while script_index < len(args) and args[script_index] in ("-u", "-B", "-O", "-OO"):
        script_index += 1
    if (
        script_index >= len(args)
        or Path(args[script_index]).name != WATCHER_SCRIPT_NAME
    ):
        return False
    return script_index + 1 < len(args) and args[script_index + 1] == repo_path


def _parent_pid(pid: int) -> int:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return 0
    # comm is parenthesised and may itself contain spaces or ')', so parse only
    # the fields after the final ')'.
    try:
        return int(stat.rsplit(")", 1)[1].split()[1])
    except (IndexError, ValueError):
        return 0


def ancestor_pids(pid: int | None = None) -> set[int]:
    """Return ``pid`` (default: this process) plus all of its ancestors.

    Excluding the panel's own process tree keeps the panel — and the shell or
    request that triggered a start — from ever being adopted as a server.
    """
    current = os.getpid() if pid is None else pid
    seen = {current}
    for _ in range(64):
        parent = _parent_pid(current)
        if parent <= 0 or parent in seen:
            break
        seen.add(parent)
        current = parent
    return seen


def _candidate_argv(excluded: set[int]) -> Iterator[tuple[int, list[str]]]:
    """Yield ``(pid, argv)`` for every readable process not in ``excluded``."""
    try:
        entries = list(Path("/proc").iterdir())
    except OSError:
        return
    for entry in entries:
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pid in excluded:
            continue
        yield pid, read_cmdline(pid)


def list_mcp_server_pids(
    port: int,
    exclude: set[int] | None = None,
    host: str | None = None,
    path: str | None = None,
) -> list[int]:
    """Pids of verified MCP server invocations serving ``port``, oldest first.

    ``/proc`` is scanned directly rather than through ``pgrep -f``: pgrep matches
    the pattern against the command line of the *calling* shell too, which is the
    failure this function exists to avoid.
    """
    excluded = ancestor_pids() if exclude is None else set(exclude)
    return sorted(
        pid
        for pid, args in _candidate_argv(excluded)
        if is_mcp_server_invocation(args, port, host, path)
    )


def list_watcher_pids(repo_path: str, exclude: set[int] | None = None) -> list[int]:
    """Pids of verified ``realtime_updater.py`` runs for ``repo_path``, oldest first.

    The watcher's own repo path is a required *argument*; a process that merely
    mentions the script name somewhere in its command line is not a watcher.
    """
    excluded = ancestor_pids() if exclude is None else set(exclude)
    return sorted(
        pid
        for pid, args in _candidate_argv(excluded)
        if is_watcher_invocation(args, repo_path)
    )


def group_by_process_group(pids: list[int]) -> list[McpServerProcesses]:
    """Collapse pids into one entry per server (one per process group).

    The panel spawns every server with ``start_new_session=True``, so the ``uv``
    wrapper and its python child share a group and are one server, not two.
    """
    groups: dict[int, list[int]] = {}
    for pid in pids:
        try:
            pgid = os.getpgid(pid)
        except (ProcessLookupError, PermissionError):
            continue
        groups.setdefault(pgid, []).append(pid)
    return [
        McpServerProcesses(pgid=pgid, pids=tuple(sorted(group)))
        for pgid, group in sorted(groups.items())
    ]


# --------------------------------------------------------------------------
# Liveness
# --------------------------------------------------------------------------


def endpoint_open(host: str, port: int, timeout: float = 1.0) -> bool:
    """True when something accepts a TCP connection on ``host:port``."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def listener_pids(host: str, port: int) -> list[int]:
    """Resolve the answering TCP listener to local socket-owning processes."""
    try:
        with socket.create_connection((host, port), timeout=1.0) as connection:
            peer = connection.getpeername()
            address = peer[0]
            with socket.socket(connection.family, socket.SOCK_STREAM) as local_check:
                local_check.bind((address, 0, *peer[2:]))
    except OSError:
        return []
    inodes: set[str] = set()
    for table, family in (("tcp", socket.AF_INET), ("tcp6", socket.AF_INET6)):
        try:
            rows = Path(f"/proc/net/{table}").read_text().splitlines()[1:]
        except OSError:
            continue
        for row in rows:
            fields = row.split()
            raw_address, raw_port = fields[1].split(":")
            if fields[3] != "0A" or int(raw_port, 16) != port:
                continue
            packed = b"".join(
                int(raw_address[offset : offset + 8], 16).to_bytes(4, sys.byteorder)
                for offset in range(0, len(raw_address), 8)
            )
            bound_address = socket.inet_ntop(family, packed)
            if bound_address in (address, "0.0.0.0", "::", f"::ffff:{address}"):
                inodes.add(f"socket:[{fields[9]}]")
    owners: list[int] = []
    if not inodes:
        return owners
    for pid, _args in _candidate_argv(set()):
        try:
            descriptors = Path(f"/proc/{pid}/fd").iterdir()
            for descriptor in descriptors:
                try:
                    target = os.readlink(descriptor)
                except OSError:
                    continue
                if target in inodes:
                    owners.append(pid)
                    break
        except OSError:
            continue
    return sorted(owners)


def pid_alive(pid: int) -> bool:
    """True while ``pid`` exists and is not a zombie."""
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except (OSError, IndexError):
        state = None
    if state == "Z":
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _parse_jsonrpc(raw: str) -> dict[str, Any] | None:
    """Extract the JSON-RPC ``result`` from a JSON or SSE (``data:``) response."""
    candidates = [raw.strip()]
    candidates.extend(
        line[len("data:") :].strip()
        for line in raw.splitlines()
        if line.startswith("data:")
    )
    for candidate in candidates:
        if not candidate:
            continue
        try:
            decoded = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(decoded, dict):
            result = decoded.get("result")
            if isinstance(result, dict):
                return result
    return None


def _terminate_session(url: str, session_id: str, timeout: float) -> None:
    """Best-effort ``DELETE`` of the session an initialize probe created."""
    request = urllib.request.Request(
        url, method="DELETE", headers={"mcp-session-id": session_id}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout):
            pass
    except Exception:  # noqa: BLE001 - cleanup must never fail a probe
        return


def probe_mcp_server(
    host: str,
    port: int,
    path: str,
    timeout: float = 2.0,
) -> dict[str, Any]:
    """Ask the endpoint to identify itself with a JSON-RPC ``initialize``.

    Returns ``{"alive", "port_open", "server_name", "version", "error"}``. The
    caller compares ``server_name`` with :data:`MCP_SERVER_NAME`; a 200 response
    alone is not proof, since any HTTP service could be listening.
    """
    url = f"http://{host}:{port}{path}"
    result: dict[str, Any] = {
        "alive": False,
        "port_open": endpoint_open(host, port, timeout),
        "server_name": None,
        "version": None,
        "error": None,
    }
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": _PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": _PROBE_CLIENT_NAME, "version": "0.1.0"},
            },
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
    )
    session_id: str | None = None
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            # Read the session id before the body: if the body read fails we still
            # know which session to clean up.
            session_id = response.headers.get("mcp-session-id")
            raw = response.read().decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001 - any transport error means "unverified"
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result
    finally:
        if session_id:
            _terminate_session(url, session_id, timeout)

    payload = _parse_jsonrpc(raw)
    if payload is None:
        result["error"] = "endpoint did not return a JSON-RPC payload"
        return result
    info = payload.get("serverInfo")
    if not isinstance(info, dict):
        result["error"] = "endpoint returned no serverInfo"
        return result
    name = info.get("name")
    result["server_name"] = name if isinstance(name, str) else None
    version = info.get("version")
    result["version"] = version if isinstance(version, str) else None
    result["alive"] = result["server_name"] is not None
    return result


# --------------------------------------------------------------------------
# Shutdown
# --------------------------------------------------------------------------


def stop_pid(pid: int, timeout: float = 8.0) -> None:
    """SIGINT a single process, escalating to SIGKILL on that pid only.

    ``os.killpg`` is deliberately avoided. An adopted server is not a child of
    the panel and may share its process group with a shell, a terminal or other
    work the panel does not own — signalling the group would hit those too.

    The target's command line is captured up front and re-checked before the
    SIGKILL escalation, so a pid that has been recycled during the wait is left
    alone rather than killed.
    """
    expected_cmdline = read_cmdline(pid)
    try:
        os.kill(pid, signal.SIGINT)
    except (ProcessLookupError, PermissionError):
        return
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not pid_alive(pid):
            return
        if expected_cmdline and read_cmdline(pid) != expected_cmdline:
            return  # the pid was recycled: it is somebody else's process now
        time.sleep(0.2)
    try:
        os.kill(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
