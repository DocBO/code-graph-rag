"""The control panel's MCP adoption decision.

Regression coverage for ``docs/BUG_MCP_PROCESS_ADOPTION.md``. The panel backend
is imported with an isolated, empty repository list and a free MCP port so that
importing it cannot touch the real ``repos.json``, the real watchers or the real
server on port 8765.
"""

from __future__ import annotations

import importlib
import os
import socket
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fake_mcp_server import FakeMcpServer
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1] / "control_panel" / "backend"


@pytest.fixture()
def panel(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[Any, int]]:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "repos.json").write_text("[]")
    monkeypatch.setenv("GRAPHCODE_PANEL_DATA_DIR", str(data_dir))
    port = _free_port()
    monkeypatch.setenv("MCP_PORT", str(port))
    monkeypatch.setenv("MCP_HOST", "127.0.0.1")
    monkeypatch.setenv("MCP_PATH", "/mcp")
    monkeypatch.syspath_prepend(str(BACKEND_DIR))
    for module in ("main", "panel_processes"):
        sys.modules.pop(module, None)

    main = importlib.import_module("main")
    try:
        yield main, port
    finally:
        main.manager.mcp.state = "stopped"  # let the adopted monitor retire
        for module in ("main", "panel_processes"):
            sys.modules.pop(module, None)


def test_nothing_listening_is_not_adopted(panel: tuple[Any, int]) -> None:
    """A start must reach the spawn branch when no server answers the probe."""
    main, _port = panel
    handle = main.manager.mcp
    handle.logs.clear()

    assert main._adopt_mcp_server(handle, reason="existing") is False

    assert handle.state == "stopped"
    assert handle.adopted_pid is None
    assert any("nothing to adopt" in line for line in handle.logs)


def test_adoption_of_a_verified_server_reports_running(panel: tuple[Any, int]) -> None:
    main, port = panel
    handle = main.manager.mcp
    handle.logs.clear()
    server = FakeMcpServer(port=port, name="graph-code-mcp", version="1.21.1")
    try:
        assert main._adopt_mcp_server(handle, reason="existing") is True
    finally:
        server.close()

    assert handle.state == "running"
    assert handle.proc is None
    # The endpoint is a thread in this test process, so no local pid resolves;
    # that is exactly the external-server case and must be admitted in the log.
    assert handle.adopted_pid is None
    assert any(
        "adopted existing MCP server" in line and "probe=answered" in line
        for line in handle.logs
    )
    assert any("no locally resolvable pid" in line for line in handle.logs)


def test_a_foreign_server_on_the_port_is_refused(panel: tuple[Any, int]) -> None:
    main, port = panel
    handle = main.manager.mcp
    handle.logs.clear()
    server = FakeMcpServer(port=port, name="someone-elses-mcp")
    try:
        with pytest.raises(main.HTTPException) as excinfo:
            main._adopt_mcp_server(handle, reason="existing")
    finally:
        server.close()

    assert excinfo.value.status_code == 409
    assert handle.state == "stopped"
    assert any("refusing to adopt" in line for line in handle.logs)


def test_start_endpoint_adopts_a_verified_server(panel: tuple[Any, int]) -> None:
    main, port = panel
    server = FakeMcpServer(port=port, name="graph-code-mcp", version="1.21.1")
    try:
        # TestClient must be a context manager: without it the portal thread it
        # starts leaks a socketpair and an event loop, which pytest later reports
        # as an unraisable ResourceWarning (and fails an unrelated test under -W error).
        with TestClient(main.app) as client:
            # The MCP server is not bound to a repository, so starting it needs
            # no repo_path at all.
            response = client.post("/api/mcp/start", json={})
    finally:
        server.close()

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "running"
    assert body["pid"] is None
    assert body["last_error"] is None


def test_start_endpoint_refuses_a_foreign_server(panel: tuple[Any, int]) -> None:
    main, port = panel
    server = FakeMcpServer(port=port, name="someone-elses-mcp")
    try:
        with TestClient(main.app) as client:
            response = client.post("/api/mcp/start", json={})
    finally:
        server.close()

    assert response.status_code == 409
    assert "someone-elses-mcp" in response.json()["detail"]
    assert main.manager.mcp.proc is None


def test_mcp_status_no_longer_reports_a_default_repository(
    panel: tuple[Any, int],
) -> None:
    main, _port = panel
    with TestClient(main.app) as client:
        body = client.get("/api/status").json()

    assert "repo_path" not in body["mcp"]


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/api/query", {"question": "Where is auth handled?"}),
        ("/api/query", {"question": "Where is auth handled?", "repo_path": ""}),
        ("/api/query", {"question": "Where is auth handled?", "repo_path": "   "}),
        ("/api/semantic", {"search_phrase": "login handler"}),
        ("/api/semantic", {"search_phrase": "login handler", "repo_path": ""}),
    ],
)
def test_repo_scoped_api_rejects_a_missing_repository_with_the_cause(
    panel: tuple[Any, int], path: str, payload: dict[str, str]
) -> None:
    main, _port = panel
    with TestClient(main.app) as client:
        response = client.post(path, json=payload)

    assert response.status_code == 422
    assert "repo_path is required" in response.json()["detail"]


def test_stop_does_not_pretend_to_stop_an_unresolved_server(
    panel: tuple[Any, int],
) -> None:
    """Criterion 3: with no resolvable pid, stop must not signal anything."""
    main, port = panel
    server = FakeMcpServer(port=port, name="graph-code-mcp")
    try:
        assert main._adopt_mcp_server(main.manager.mcp) is True
        with TestClient(main.app) as client:
            response = client.post("/api/mcp/stop")
        assert response.status_code == 409
        assert "unmanaged" in response.json()["detail"]
        assert main.manager.mcp.state == "running"
        assert any(
            "not stoppable: no locally resolvable pid" in line
            for line in main.manager.mcp.logs
        )
    finally:
        server.close()


def test_adoption_selects_the_socket_owner_not_the_newest_candidate(
    panel: tuple[Any, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Simulate candidate discovery; use real socket ownership and forbid signals."""
    main, port = panel
    owner = os.getpid()
    decoy = owner + 1000000
    monkeypatch.setattr(
        main.panel_processes,
        "list_mcp_server_pids",
        lambda *args, **kwargs: [owner, decoy],
    )
    stopped: list[int] = []
    monkeypatch.setattr(main, "_stop_adopted_mcp_pid", stopped.append)
    server = FakeMcpServer(port=port)
    try:
        assert main._adopt_mcp_server(main.manager.mcp)
        assert main.manager.mcp.adopted_pid == owner
        assert stopped == []
    finally:
        server.close()


def test_adopted_startup_survives_three_missed_probes(
    panel: tuple[Any, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Compress the monitor clock instead of waiting for the 120-second grace."""
    main, _port = panel
    handle = main.McpHandle()
    handle.state = "starting"
    handle.adopted_pid = os.getpid()
    handle._adoption_token = object()
    probes = 0
    states: list[str] = []

    def probe(timeout: float) -> dict[str, Any]:
        nonlocal probes
        probes += 1
        return {"alive": probes > 3, "server_name": main.MCP_SERVER_NAME}

    def tick(seconds: float) -> None:
        states.append(handle.state)
        if handle.state == "running":
            handle._adoption_token = None

    monkeypatch.setattr(main, "_probe_mcp_server", probe)
    monkeypatch.setattr(main.time, "sleep", tick)
    monitor = main._start_adopted_mcp_monitor(handle)
    monitor.join(timeout=2)
    assert not monitor.is_alive()
    assert states == ["starting", "starting", "starting", "running"]
    assert handle.last_error is None


def test_ambiguous_socket_ownership_remains_unmanaged(
    panel: tuple[Any, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Simulate shared-socket owners without spawning competing real MCP servers."""
    main, port = panel
    monkeypatch.setattr(
        main.panel_processes, "list_mcp_server_pids", lambda *args, **kwargs: [11, 22]
    )
    monkeypatch.setattr(
        main.panel_processes, "listener_pids", lambda host, port: [11, 22]
    )
    server = FakeMcpServer(port=port)
    try:
        assert main._adopt_mcp_server(main.manager.mcp)
        assert main.manager.mcp.adopted_pid is None
        with TestClient(main.app) as client:
            response = client.post("/api/mcp/stop")
        assert response.status_code == 409
        assert main.manager.mcp.state == "running"
    finally:
        server.close()


def test_adopted_startup_uses_the_configured_timeout(
    panel: tuple[Any, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Advance a deterministic clock to exercise the grace deadline."""
    main, _port = panel
    handle = main.McpHandle()
    handle.state = "starting"
    handle.adopted_pid = os.getpid()
    handle._adoption_token = object()
    monkeypatch.setattr(main, "MCP_START_TIMEOUT", 15)
    clock = iter([0.0, 16.0])
    monkeypatch.setattr(main.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(
        main, "_probe_mcp_server", lambda timeout: {"alive": False, "server_name": None}
    )
    monitor = main._start_adopted_mcp_monitor(handle)
    monitor.join()
    assert handle.state == "error"
    assert handle.last_error == "startup timed out after 15s"


def test_obsolete_adoption_monitor_cannot_update_a_replacement(
    panel: tuple[Any, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Replace the handle during a probe to exercise an otherwise racy boundary."""
    main, _port = panel
    handle = main.McpHandle()
    handle.state = "starting"
    handle.adopted_pid = os.getpid()
    handle._adoption_token = object()

    def probe(timeout: float) -> dict[str, Any]:
        handle._adoption_token = object()
        return {"alive": True, "server_name": main.MCP_SERVER_NAME}

    monkeypatch.setattr(main, "_probe_mcp_server", probe)
    monitor = main._start_adopted_mcp_monitor(handle)
    monitor.join(timeout=2)
    assert not monitor.is_alive()
    assert handle.state == "starting"
    assert handle.logs == main.deque()


def test_external_watcher_shutdown_uses_the_single_pid_helper(
    panel: tuple[Any, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Intercept destructive signals while verifying the panel shutdown route."""
    main, _port = panel
    stopped: list[int] = []
    monkeypatch.setattr(main.panel_processes, "stop_pid", stopped.append)

    def reject_group(pgid: int) -> None:
        pytest.fail("an external watcher process group was signalled")

    monkeypatch.setattr(main, "_stop_group_id", reject_group)
    main._stop_adopted_pid(12345)
    assert stopped == [12345]


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
