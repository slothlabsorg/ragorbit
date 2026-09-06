"""Modo integración: el flujo llama servicios HTTP reales (mock o prod)."""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from runtime.executor import run_flow

_ROOT = Path(__file__).resolve().parent.parent
_FLOW_PATH = _ROOT / "flow.json"

SERVICE_MAP = {{SERVICE_MAP_JSON}}


def _match_service(node: dict) -> tuple[str, str] | None:
    name = (
        str(node.get("label", ""))
        + " "
        + str(node.get("config", {}).get("name", ""))
        + " "
        + node["id"]
    ).lower()
    for keys, service, op in SERVICE_MAP:
        if any(k in name for k in keys):
            return service, op
    return None


def patch_flow_with_services(flow: dict, services_base: str) -> dict:
    for n in flow["nodes"]:
        if n["type"] == "tool.service":
            m = _match_service(n)
            if m:
                service, op = m
                n.setdefault("config", {})
                n["config"]["baseUrl"] = f"{services_base}/{service}"
                n["config"]["operation"] = op
    return flow


def _compile_and_fixtures():
    fixtures = json.loads((_ROOT / "mocks" / "fixtures.json").read_text(encoding="utf-8"))
    return fixtures


def _compiled_patched(flow: dict) -> dict:
    """Aplica baseUrl/operation parcheados al compiled flow en disco."""
    compiled = json.loads((_ROOT / "flow.compiled.json").read_text(encoding="utf-8"))
    by_id = {n["id"]: n for n in flow.get("nodes", [])}
    for n in compiled.get("nodes", []):
        src = by_id.get(n["id"])
        if src and src.get("type") == "tool.service":
            n["config"] = {**n.get("config", {}), **src.get("config", {})}
    return compiled


def make_http(idem_key: str, record: Optional[Callable] = None):
    from app import settings

    def http(base: str, operation: str, payload: dict) -> dict:
        url = f"{base}/{operation}"
        service = base.rstrip("/").split("/")[-1]
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Idempotency-Key": idem_key,
            },
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            resp = json.loads(r.read())
        if record is not None:
            record(
                {
                    "service": service,
                    "operation": operation,
                    "url": url,
                    "request": payload,
                    "response": resp,
                    "idempotencyKey": idem_key,
                }
            )
        return resp

    return http


def run(
    seed_message: str,
    services_base: Optional[str] = None,
    bus=None,
    session_id: str = "web-sess-1",
    record: Optional[Callable] = None,
) -> dict:
    from app import settings

    services_base = (services_base or settings.SERVICES_BASE).rstrip("/")
    flow = json.loads(_FLOW_PATH.read_text(encoding="utf-8"))
    patch_flow_with_services(flow, services_base)
    compiled = _compiled_patched(flow)
    fixtures = _compile_and_fixtures()
    idem_key = f"{settings.FLOW_ID}:{session_id}"
    integration: Dict[str, Any] = {
        "http": make_http(idem_key=idem_key, record=record),
        "idem_key": idem_key,
    }
    if bus is not None:
        integration["bus"] = bus.publish
    res = run_flow(compiled, fixtures, seed_message=seed_message, integration=integration)
    res["_idem_key"] = idem_key
    res["_services_base"] = services_base
    return res
