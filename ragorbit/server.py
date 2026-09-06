"""Backend de RAGorbit con stdlib (http.server). Sin dependencias.

Sirve la API y la UI canvas (apps/web-lite). Corre con:  python -m ragorbit serve
Es el backend de desarrollo verificable sin instalar nada. La versión de producción
(apps/api con FastAPI) expone los mismos endpoints.

Endpoints:
  GET  /                      -> UI canvas (apps/web-lite/index.html)
  GET  /api/registry/nodes    -> catálogo (paleta + forms)
  GET  /api/templates         -> los 10 ejemplos (galería)
  POST /api/validate          -> {flow} -> {ok, errors, warnings}
  POST /api/run-mock          -> {flow, seedMessage} -> resultado de la ejecución mock
  POST /api/generate          -> {flow} -> zip del proyecto generado
"""
from __future__ import annotations

import io
import json
import tempfile
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .codegen import compile_flow, generate_fixtures, generate_project
from .registry import load_registry
from .runtime.executor import run_flow
from .validator import validate_flow

_PKG = Path(__file__).parent


def _templates(root: Path):
    out = []
    ex = root / "examples"
    for fj in sorted(ex.glob("*/flow.json")):
        try:
            flow = json.loads(fj.read_text(encoding="utf-8"))
        except Exception:
            continue
        out.append({
            "id": flow["flow"]["id"],
            "name": flow["flow"].get("name", flow["flow"]["id"]),
            "description": flow["flow"].get("description", ""),
            "deploymentTarget": flow["flow"].get("deploymentTarget"),
            "flow": flow,
        })
    return out


def make_handler(root: Path, registry):
    ui_file = root / "apps" / "web-lite" / "index.html"

    class Handler(BaseHTTPRequestHandler):
        server_version = "RAGorbit/0.1"

        def log_message(self, *a):  # silencioso
            pass

        def _send(self, code, body, ctype="application/json", extra=None):
            data = body if isinstance(body, (bytes, bytearray)) else json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def _body(self):
            n = int(self.headers.get("Content-Length", 0) or 0)
            return json.loads(self.rfile.read(n) or b"{}")

        def do_OPTIONS(self):
            self._send(204, b"")

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                if ui_file.exists():
                    self._send(200, ui_file.read_bytes(), "text/html; charset=utf-8")
                else:
                    self._send(200, b"<h1>RAGorbit</h1><p>UI no encontrada.</p>", "text/html")
                return
            if self.path.startswith("/api/registry/nodes"):
                self._send(200, registry.to_palette()); return
            if self.path.startswith("/api/templates"):
                self._send(200, _templates(root)); return
            # estáticos (vendor/*.js, *.css) bajo apps/web-lite/ — UI 100% offline
            static = self._safe_static(self.path)
            if static is not None and static.exists():
                self._send(200, static.read_bytes(), _ctype(static))
                return
            self._send(404, {"error": "not found"})

        def _safe_static(self, path):
            rel = path.lstrip("/").split("?")[0]
            base = (root / "apps" / "web-lite").resolve()
            target = (base / rel).resolve()
            if str(target).startswith(str(base)) and target.is_file():
                return target
            return None

        def do_POST(self):
            try:
                if self.path.startswith("/api/validate"):
                    flow = self._body().get("flow", {})
                    res = validate_flow(flow, registry)
                    self._send(200, {"ok": res.ok, "errors": res.errors, "warnings": res.warnings}); return
                if self.path.startswith("/api/run-mock"):
                    body = self._body()
                    flow = body.get("flow", {})
                    res = validate_flow(flow, registry)
                    if not res.ok:
                        self._send(200, {"ok": False, "errors": res.errors}); return
                    compiled = compile_flow(flow, registry)
                    fixtures = generate_fixtures(flow, registry)
                    out = run_flow(compiled, fixtures, seed_message=body.get("seedMessage", "Hola, ¿me ayudas?"))
                    self._send(200, {"ok": True, "result": _slim(out)}); return
                if self.path.startswith("/api/generate"):
                    flow = self._body().get("flow", {})
                    res = validate_flow(flow, registry)
                    if not res.ok:
                        self._send(400, {"ok": False, "errors": res.errors}); return
                    zip_bytes = _zip_project(flow, registry)
                    self._send(200, zip_bytes, "application/zip",
                               {"Content-Disposition": f"attachment; filename={flow['flow']['id']}.zip"}); return
                self._send(404, {"error": "not found"})
            except Exception as exc:
                self._send(500, {"error": f"{type(exc).__name__}: {exc}"})

    return Handler


def _ctype(path) -> str:
    ext = path.suffix.lower()
    return {".js": "application/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
            ".html": "text/html; charset=utf-8", ".json": "application/json",
            ".map": "application/json"}.get(ext, "application/octet-stream")


def _slim(out: dict) -> dict:
    return {
        "response": out.get("response"),
        "escalations": out.get("escalations", []),
        "notifications": out.get("notifications", []),
        "citations": out.get("citations", []),
        "audit": out.get("audit", []),      # lista completa de eventos (para el panel de auditoría)
        "metrics": out.get("metrics", []),
        "trace": out.get("trace", {}),       # incluye trace.agent.tool_calls con result/guardrails
    }


def _zip_project(flow, registry) -> bytes:
    with tempfile.TemporaryDirectory() as td:
        proj = Path(td) / flow["flow"]["id"]
        generate_project(flow, proj, registry)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for p in proj.rglob("*"):
                if p.is_file():
                    z.write(p, p.relative_to(proj.parent))
        return buf.getvalue()


def serve(port: int = 8000, root: Path = Path(".")):
    root = Path(root).resolve()
    registry = load_registry()
    handler = make_handler(root, registry)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    print(f"RAGorbit en http://127.0.0.1:{port}  (root={root})")
    print(f"  {len(registry.all())} tipos de nodo · {len(_templates(root))} templates")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.shutdown()
