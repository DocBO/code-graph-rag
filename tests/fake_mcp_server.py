"""A minimal, *real* HTTP MCP endpoint for control-panel tests.

It speaks just enough of the streamable-HTTP transport (``initialize`` returning
``serverInfo``, plus session ``DELETE``) that the panel's probe can be exercised
against a real socket instead of a mocked ``urllib``. Test-only helper; pytest
does not collect it.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args: Any) -> None:
        return  # keep pytest output clean

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        server: FakeMcpServer = self.server  # type: ignore[assignment]
        length = int(self.headers.get("Content-Length", 0) or 0)
        self.rfile.read(length)
        server.initialize_calls += 1
        if server.status != 200:
            self.send_response(server.status)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        session_id = f"session-{server.initialize_calls}"
        server.sessions.add(session_id)
        result = {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "serverInfo": {"name": server.mcp_name, "version": server.mcp_version},
        }
        payload = json.dumps({"jsonrpc": "2.0", "id": 1, "result": result})
        if server.sse:
            body = f"event: message\r\ndata: {payload}\r\n\r\n".encode()
            content_type = "text/event-stream"
        else:
            body = payload.encode()
            content_type = "application/json"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("mcp-session-id", session_id)
        self.end_headers()
        self.wfile.write(body)

    def do_DELETE(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        server: FakeMcpServer = self.server  # type: ignore[assignment]
        session_id = self.headers.get("mcp-session-id", "")
        server.sessions.discard(session_id)
        server.deleted.add(session_id)
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()


class FakeMcpServer(ThreadingHTTPServer):
    """A localhost HTTP endpoint that answers MCP ``initialize``.

    ``mcp_name`` is deliberately not called ``server_name``: ``HTTPServer``
    already defines that attribute for the host the socket is bound to.
    """

    def __init__(
        self,
        port: int = 0,
        name: str = "graph-code-mcp",
        version: str = "9.9.9",
        sse: bool = False,
        status: int = 200,
    ) -> None:
        super().__init__(("127.0.0.1", port), _Handler)
        self.mcp_name = name
        self.mcp_version = version
        self.sse = sse
        self.status = status
        self.sessions: set[str] = set()
        self.deleted: set[str] = set()
        self.initialize_calls = 0
        self.port = int(self.server_address[1])
        self._thread = threading.Thread(target=self.serve_forever, daemon=True)
        self._thread.start()

    def close(self) -> None:
        self.shutdown()
        self.server_close()
        self._thread.join(timeout=5)
