"""Backend de producción de RAGorbit (FastAPI). Reusa el engine `ragorbit`.

Mismos endpoints que el backend stdlib (`python -m ragorbit serve`), pero con FastAPI:
streaming, validación de tipos, OpenAPI, etc. Requiere instalar deps:

    pip install -e ".[api]"
    uvicorn apps.api.main:app --reload

El engine es stdlib puro; FastAPI solo expone la API HTTP.
"""
from __future__ import annotations

import io
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ragorbit.codegen import compile_flow, generate_fixtures, generate_project
from ragorbit.registry import load_registry
from ragorbit.runtime.executor import run_flow
from ragorbit.validator import validate_flow

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = load_registry()

app = FastAPI(title="RAGorbit API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# Persistencia simple en memoria (dev). En prod: SQLAlchemy + Postgres.
_FLOWS: Dict[str, dict] = {}
_SECRETS: Dict[str, str] = {}


class FlowBody(BaseModel):
    flow: Dict[str, Any]
    seedMessage: Optional[str] = "Hola, ¿me ayudas con mi caso?"


@app.get("/api/registry/nodes")
def registry_nodes() -> List[dict]:
    return REGISTRY.to_palette()


@app.get("/api/templates")
def templates() -> List[dict]:
    import json
    out = []
    for fj in sorted((ROOT / "examples").glob("*/flow.json")):
        flow = json.loads(fj.read_text(encoding="utf-8"))
        out.append({"id": flow["flow"]["id"], "name": flow["flow"].get("name"),
                    "description": flow["flow"].get("description", ""),
                    "deploymentTarget": flow["flow"].get("deploymentTarget"), "flow": flow})
    return out


@app.post("/api/validate")
def validate(body: FlowBody) -> dict:
    res = validate_flow(body.flow, REGISTRY)
    return {"ok": res.ok, "errors": res.errors, "warnings": res.warnings}


@app.post("/api/run-mock")
def run_mock(body: FlowBody) -> dict:
    res = validate_flow(body.flow, REGISTRY)
    if not res.ok:
        return {"ok": False, "errors": res.errors}
    compiled = compile_flow(body.flow, REGISTRY)
    fixtures = generate_fixtures(body.flow, REGISTRY)
    out = run_flow(compiled, fixtures, seed_message=body.seedMessage or "Hola")
    return {"ok": True, "result": {
        "response": out["response"], "escalations": out["escalations"],
        "notifications": out["notifications"], "citations": out["citations"],
        "audit": out["audit"], "metrics": out["metrics"], "trace": out["trace"]}}


@app.post("/api/generate")
def generate(body: FlowBody):
    res = validate_flow(body.flow, REGISTRY)
    if not res.ok:
        raise HTTPException(status_code=400, detail={"errors": res.errors})
    with tempfile.TemporaryDirectory() as td:
        proj = Path(td) / body.flow["flow"]["id"]
        generate_project(body.flow, proj, REGISTRY)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for p in proj.rglob("*"):
                if p.is_file():
                    z.write(p, p.relative_to(proj.parent))
        buf.seek(0)
        fid = body.flow["flow"]["id"]
        return StreamingResponse(io.BytesIO(buf.getvalue()), media_type="application/zip",
                                 headers={"Content-Disposition": f"attachment; filename={fid}.zip"})


# CRUD mínimo de flows y secretos (dev)
@app.get("/api/flows")
def list_flows() -> List[dict]:
    return list(_FLOWS.values())


@app.post("/api/flows")
def save_flow(body: FlowBody) -> dict:
    fid = body.flow["flow"]["id"]
    _FLOWS[fid] = body.flow
    return {"ok": True, "id": fid}


@app.put("/api/secrets/{name}")
def set_secret(name: str, value: dict) -> dict:
    _SECRETS[name] = value.get("value", "")  # en prod: cifrar at-rest
    return {"ok": True, "name": name}
