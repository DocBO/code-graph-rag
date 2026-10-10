"""The control panel's MCP adoption decision.

Regression coverage for ``docs/BUG_MCP_PROCESS_ADOPTION.md``. The panel backend
is imported with an isolated, empty repository list and a free MCP port so that
importing it cannot touch the real ``repos.json``, the real watchers or the real
server on port 8765.
"""

from __future__ import annotations

import importlib
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
            response = client.post(
                "/api/mcp/start", json={"repo_path": "/tmp/does-not-matter"}
            )
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
        assert response.status_code == 200
        assert response.json()["state"] == "stopped"
        assert any(
            "not stoppable: no locally resolvable pid" in line
            for line in main.manager.mcp.logs
        )
    finally:
        server.close()


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
