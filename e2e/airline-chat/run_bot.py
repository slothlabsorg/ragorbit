"""Corre el flujo "chat de aerolínea" de RAGorbit en MODO INTEGRACIÓN:
los tool.service llaman a los servicios HTTP reales que estén corriendo, y el
audit publica al bus (Kafka o memoria). Reusa el runtime del engine RAGorbit.

Uso (con servicios en :8900 y, opcional, Kafka):
    python e2e/airline-chat/run_bot.py "Quiero cambiar mi vuelo SCL-BOG del 15 al 17"
"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO))

from ragorbit.codegen import compile_flow, generate_fixtures  # noqa: E402
from ragorbit.registry import load_registry  # noqa: E402
from ragorbit.runtime.executor import run_flow  # noqa: E402

FLOW_PATH = _REPO / "examples" / "01-airline-flight-change" / "flow.json"

# Mapea cada tool.service (por palabra clave en su nombre/label) a su servicio/operación reales.
SERVICE_MAP = [
    (("reservation", "pnr", "reserva"), "reservation", "lookup"),
    (("inventory", "inventario", "disponibil"), "inventory", "search"),
    (("pricing", "tarif", "precio"), "pricing", "quote"),
    (("payment", "pago", "cobro"), "payment", "charge"),
]


def _match_service(node) -> tuple[str, str] | None:
    name = (str(node.get("label", "")) + " " + str(node.get("config", {}).get("name", "")) + " " + node["id"]).lower()
    for keys, service, op in SERVICE_MAP:
        if any(k in name for k in keys):
            return service, op
    return None


def patch_flow_with_services(flow: dict, services_base: str) -> dict:
    """Inyecta baseUrl/operation en los tool.service para apuntarlos a los servicios reales."""
    for n in flow["nodes"]:
        if n["type"] == "tool.service":
            m = _match_service(n)
            if m:
                service, op = m
                n.setdefault("config", {})
                n["config"]["baseUrl"] = f"{services_base}/{service}"
                n["config"]["operation"] = op
    return flow


def make_http(idem_key: str, record=None):
    """Devuelve un callable http(base, op, payload). Si `record` se pasa, registra
    cada llamada con su request/response para el rastro de auditoría del cliente."""
    def http(base: str, operation: str, payload: dict) -> dict:
        url = f"{base}/{operation}"
        service = base.rstrip("/").split("/")[-1]
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST",
                                     headers={"Content-Type": "application/json",
                                              "Idempotency-Key": idem_key})
        with urllib.request.urlopen(req, timeout=5) as r:
            resp = json.loads(r.read())
        if record is not None:
            record({"service": service, "operation": operation, "url": url,
                    "request": payload, "response": resp, "idempotencyKey": idem_key})
        return resp
    return http


def run(seed_message: str, services_base: str | None = None, bus=None,
        session_id: str = "sess-1", record=None) -> dict:
    import os
    services_base = services_base or os.environ.get("SERVICES_BASE", "http://127.0.0.1:8900")
    reg = load_registry()
    flow = json.loads(FLOW_PATH.read_text(encoding="utf-8"))
    patch_flow_with_services(flow, services_base)
    compiled = compile_flow(flow, reg)
    fixtures = generate_fixtures(flow, reg)
    idem_key = f"{flow['flow']['id']}:{session_id}"
    integration = {"http": make_http(idem_key=idem_key, record=record), "idem_key": idem_key}
    if bus is not None:
        integration["bus"] = bus.publish
    res = run_flow(compiled, fixtures, seed_message=seed_message, integration=integration)
    res["_idem_key"] = idem_key
    res["_services_base"] = services_base
    return res


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from bus import make_bus  # type: ignore
    msg = sys.argv[1] if len(sys.argv) > 1 else "Quiero cambiar mi vuelo SCL-BOG del 15 al 17"
    bus = make_bus()
    res = run(msg, bus=bus)
    print(json.dumps({
        "response": res["response"],
        "tool_calls": [c["name"] for c in res["trace"].get("agent", {}).get("tool_calls", [])],
        "audit_events_on_bus": len(bus.drain()),
    }, ensure_ascii=False, indent=2))
