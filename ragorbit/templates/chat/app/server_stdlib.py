"""Servidor HTTP stdlib — sin dependencias pip (Docker / Cloud Run offline)."""
from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from app.engine import run_turn

_STATIC = Path(__file__).resolve().parent.parent / "static"
_PORT = int(os.environ.get("PORT", "8000"))


class Handler(BaseHTTPRequestHandler):
    server_version = "RAGorbitChat/0.1"

    def log_message(self, *a):
        pass

    def _send(self, code: int, body, ctype="application/json"):
        if isinstance(body, (dict, list)):
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            ctype = "application/json"
        else:
            data = body if isinstance(body, (bytes, bytearray)) else str(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            from app import settings
            self._send(200, {"ok": True, "flow_id": settings.FLOW_ID, "mock": settings.MOCK,
                              "integration": settings.INTEGRATION, "llm": settings.llm_enabled(),
                              "server": "stdlib"})
            return
        if path in ("/", "/index.html"):
            ui = _STATIC / "index.html"
            if ui.is_file():
                self._send(200, ui.read_bytes(), "text/html; charset=utf-8")
                return
        self._send(404, {"error": "not found"})

    def do_POST(self):
        path = urlparse(self.path).path
        n = int(self.headers.get("Content-Length", 0) or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            body = {}
        if path == "/chat":
            msg = body.get("message", "")
            sid = body.get("session_id", "web-sess-1")
            if not msg:
                self._send(400, {"error": "message required"}); return
            try:
                self._send(200, run_turn(msg, session_id=sid))
            except Exception as exc:
                self._send(503, {"error": str(exc)})
            return
        self._send(404, {"error": "not found"})


def main():
    host = os.environ.get("HOST", "0.0.0.0")
    httpd = ThreadingHTTPServer((host, _PORT), Handler)
    print(f"Chat stdlib en http://{host}:{_PORT}")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
