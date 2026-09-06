#!/usr/bin/env python3
"""DEMO del chat de aerolínea con servicios corriendo + AUDITORÍA completa.

Sin docker ni instalación: levanta los servicios mock en un thread, corre el bot
de RAGorbit contra ellos y muestra el RASTRO DE AUDITORÍA: qué tool se llamó, en
qué orden, con qué request/response, qué decidieron los guardrails (confirmación,
idempotencia) y qué eventos se publicaron al bus (Kafka/memoria).

    python3 demo/run_demo.py
    python3 demo/run_demo.py "Quiero cambiar mi vuelo SCL-BOG del 15 al 17"

Escribe el rastro a demo/audit/audit-<sesion>.json y .md
"""
from __future__ import annotations

import json
import sys
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path

_DEMO = Path(__file__).resolve().parent
_REPO = _DEMO.parent
_SVC = _REPO / "e2e" / "airline-chat"
for p in (str(_REPO), str(_SVC), str(_SVC / "services")):
    if p not in sys.path:
        sys.path.insert(0, p)

import os                   # noqa: E402
import mock_services        # noqa: E402
import run_bot              # noqa: E402
from bus import InMemoryBus, make_bus  # noqa: E402

PORT = 8920
BASE = os.environ.get("SERVICES_BASE", f"http://127.0.0.1:{PORT}")
C = {"dim": "\033[2m", "b": "\033[1m", "g": "\033[32m", "y": "\033[33m",
     "c": "\033[36m", "r": "\033[31m", "x": "\033[0m"}


def _start_services():
    mock_services.reset_payment_state()
    httpd = mock_services.build_server(PORT)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    for _ in range(50):
        try:
            urllib.request.urlopen(BASE + "/health", timeout=1); break
        except Exception:
            time.sleep(0.05)
    return httpd


def _hr(title=""):
    print(f"{C['dim']}{'─' * 78}{C['x']}")
    if title:
        print(f"{C['b']}{title}{C['x']}")


def _print_turn(title, msg, res, calls):
    _hr(title)
    print(f"   usuario  ▶  {C['c']}{msg}{C['x']}")
    print(f"   bot      ◀  {res['response']}")
    print(f"   {C['dim']}llamadas a servicios:{C['x']}")
    for i, rec in enumerate(calls, 1):
        print(f"     {C['b']}{i}. {rec['service']}/{rec['operation']}{C['x']} "
              f"→ {C['g']}{json.dumps(rec['response'], ensure_ascii=False)}{C['x']}")
    for c in res["trace"].get("agent", {}).get("tool_calls", []):
        wr = ", ".join(c.get("wrappers", [])) or "—"
        st = c.get("status", "")
        col = C['y'] if st == "pendiente-confirmación" else C['g']
        print(f"     · {c['name']:<20} [{wr}]  {col}{st}{C['x']}")


def main() -> int:
    msg = sys.argv[1] if len(sys.argv) > 1 else "Quiero cambiar mi vuelo SCL-BOG del 15 al 17"
    external = bool(os.environ.get("SERVICES_BASE"))   # en docker los servicios son un contenedor aparte
    httpd = None if external else _start_services()
    bus = make_bus("flight.audit") if os.environ.get("KAFKA_BROKER") else InMemoryBus(topic="flight.audit")
    bus_label = "Kafka" if os.environ.get("KAFKA_BROKER") else "in-memory"

    print()
    _hr("🛰️  RAGorbit · DEMO chat de aerolínea (servicios reales + auditoría)")
    print(f"   servicios:  {BASE}  ·  bus auditoría: {bus_label} (topic flight.audit)")
    print(f"   {C['dim']}El pago NO se ejecuta hasta que el usuario confirma (confirm-gate).{C['x']}")

    # --- Turno 1: el usuario pide el cambio (sin confirmar) ---
    t1: list = []
    r1 = run_bot.run(msg, services_base=BASE, bus=bus, session_id="sess-1",
                     record=lambda rec: t1.append(rec))
    _print_turn("① Turno 1 — solicitud (consulta, NO cobra)", msg, r1, t1)

    # --- Turno 2: el usuario confirma ---
    confirm_msg = "Sí, confirmo el cambio."
    t2: list = []
    r2 = run_bot.run(confirm_msg, services_base=BASE, bus=bus, session_id="sess-1",
                     record=lambda rec: t2.append(rec))
    _print_turn("② Turno 2 — confirmación (ahora SÍ cobra)", confirm_msg, r2, t2)

    # --- Idempotencia: reintento del pago con la misma clave ---
    _hr("🔁  Idempotencia (reintento del pago con la misma Idempotency-Key)")
    idem = r2["_idem_key"]
    retry = _post("/payment/charge", {"amount": 130, "currency": "USD"}, {"Idempotency-Key": idem})
    print(f"   reintento payment/charge  key={idem}")
    print(f"   resp {json.dumps(retry, ensure_ascii=False)}")
    print(f"   {C['g'] if retry.get('deduplicated') else C['r']}→ "
          f"{'DEDUPLICADO: no se cobró dos veces ✅' if retry.get('deduplicated') else 'NO deduplicado ❌'}{C['x']}")

    # --- Audit trail al bus (Kafka) ---
    _hr("📝  Audit trail publicado al bus (topic flight.audit)")
    bus_events = getattr(bus, "events", [])  # InMemoryBus expone .events; en Kafka lo ve el consumer
    for ev in bus_events:
        print(f"   {json.dumps(ev, ensure_ascii=False)}")
    if not bus_events:
        print("   (publicado a Kafka; míralo en el contenedor audit-consumer)")

    # --- Bitácora server-side ---
    _hr("🗄️  Bitácora server-side de los servicios (GET /audit) — qué recibió cada servicio")
    server_audit = _get("/audit")
    for e in server_audit:
        dd = "  [DEDUP — no recobra]" if e.get("deduplicated") else ""
        print(f"   #{e['seq']:<2} {e['service']}/{e['operation']:<8} req={json.dumps(e['request'],ensure_ascii=False)}{C['y']}{dd}{C['x']}")

    # Persistir el rastro
    out_dir = _DEMO / "audit"
    out_dir.mkdir(exist_ok=True)
    record = {
        "session": "sess-1",
        "turn1": {"message": msg, "response": r1["response"], "calls": t1,
                  "guardrails": r1["trace"].get("agent", {})},
        "turn2": {"message": confirm_msg, "response": r2["response"], "calls": t2,
                  "guardrails": r2["trace"].get("agent", {})},
        "payment_idempotency_retry": retry,
        "bus_events": bus_events, "server_audit": server_audit,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    (out_dir / "audit-sess-1.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "audit-sess-1.md").write_text(_to_md(record), encoding="utf-8")
    _hr("💾  Guardado")
    print("   demo/audit/audit-sess-1.json  ·  demo/audit/audit-sess-1.md")
    _hr()
    if httpd:
        httpd.shutdown()
    return 0


def _post(path, body, headers=None):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(),
                                 method="POST", headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


def _get(path):
    with urllib.request.urlopen(BASE + path, timeout=5) as r:
        return json.loads(r.read())


def _to_md(rec: dict) -> str:
    L = [f"# Auditoría · sesión {rec['session']}", "", f"- **Generado:** {rec['generated_at']}", ""]
    for key, title in (("turn1", "Turno 1 — solicitud (no cobra)"), ("turn2", "Turno 2 — confirmación (cobra)")):
        t = rec[key]
        L += [f"## {title}", "",
              f"- **Usuario:** {t['message']}", f"- **Bot:** {t['response']}", "",
              "| # | servicio/op | response | guardrail |", "|---|---|---|---|"]
        calls = {c["name"]: c for c in t["guardrails"].get("tool_calls", [])}
        for i, c in enumerate(t["calls"], 1):
            L.append(f"| {i} | `{c['service']}/{c['operation']}` | `{json.dumps(c['response'],ensure_ascii=False)}` |  |")
        for name, c in calls.items():
            if c.get("status") == "pendiente-confirmación":
                L.append(f"| – | `{name}` | _no ejecutado_ | ⚠ pendiente-confirmación |")
        L.append("")
    L += ["## Idempotencia", "",
          f"Reintento del pago con la misma key → `{json.dumps(rec['payment_idempotency_retry'],ensure_ascii=False)}` "
          f"(**{'deduplicado, sin doble cobro' if rec['payment_idempotency_retry'].get('deduplicated') else 'NO deduplicado'}**).", "",
          "## Eventos de auditoría (bus / Kafka)", ""]
    for ev in rec["bus_events"]:
        L.append(f"- `{json.dumps(ev,ensure_ascii=False)}`")
    L += ["", "## Bitácora server-side", "", "| # | servicio/op | dedup |", "|---|---|---|"]
    for e in rec["server_audit"]:
        L.append(f"| {e['seq']} | `{e['service']}/{e['operation']}` | {'sí' if e.get('deduplicated') else ''} |")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    sys.exit(main())
