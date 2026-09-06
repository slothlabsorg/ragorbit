#!/usr/bin/env python3
"""E2E del artefacto aerolínea con Docker (integración HTTP + Kafka).

Requiere Docker. Genera el proyecto, levanta docker-compose.integration.yml,
envía dos turnos de chat y verifica confirm-gate + respuesta.

    python3 tools/test_airline_docker.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build" / "airline-docker-test"
FLOW = ROOT / "examples" / "01-airline-flight-change" / "flow.json"
COMPOSE = "docker-compose.integration.yml"


def run(cmd, **kw):
    print(f"  $ {' '.join(cmd)}")
    return subprocess.run(cmd, **kw)


def curl_json(url, body=None, timeout=30):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url, data=data, method="POST" if body else "GET",
        headers={"Content-Type": "application/json"} if body else {},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def wait_health(base: str, retries=60):
    for i in range(retries):
        try:
            h = curl_json(f"{base}/health")
            if h.get("ok"):
                return
        except Exception:
            pass
        time.sleep(2)
        if i % 5 == 0:
            print(f"   esperando {base}/health …")
    raise RuntimeError(f"timeout esperando {base}")


def main() -> int:
    sys.path.insert(0, str(ROOT))
    from ragorbit.codegen import generate_project
    from ragorbit.registry import load_registry
    from ragorbit.validator import validate_flow

    flow = json.loads(FLOW.read_text(encoding="utf-8"))
    reg = load_registry()
    res = validate_flow(flow, reg)
    if not res.ok:
        print("❌ flow inválido"); return 1

    if OUT.exists():
        run(["rm", "-rf", str(OUT)], check=True)
    generate_project(flow, OUT, reg)
    print(f"✅ generado en {OUT}")

    # docker disponible?
    if run(["docker", "info"], capture_output=True).returncode != 0:
        print("⚠️  Docker no disponible — solo se verificó la generación.")
        return 0

    run(["docker", "compose", "-f", COMPOSE, "down", "-v"], cwd=OUT, capture_output=True)
    up = run(["docker", "compose", "-f", COMPOSE, "up", "--build", "-d"], cwd=OUT)
    if up.returncode != 0:
        print("❌ docker compose up falló"); return 1

    try:
        base = "http://127.0.0.1:8888"
        wait_health(base)

        t1 = curl_json(f"{base}/chat", {"message": "Quiero cambiar mi vuelo SCL-BOG del 15 al 17", "session_id": "e2e-1"})
        print("   turno 1:", (t1.get("response") or "")[:120], "…")
        if not t1.get("needs_confirm"):
            print("❌ turno 1 debería pedir confirmación"); return 1

        t2 = curl_json(f"{base}/chat", {"message": "Sí, confirmo el cambio.", "session_id": "e2e-1"})
        print("   turno 2:", (t2.get("response") or "")[:120], "…")
        pays = [c for c in t2.get("tool_calls", []) if "ayment" in c.get("name", "")]
        if not any(c.get("status") == "ejecutado" for c in pays):
            print("❌ turno 2 debería ejecutar el pago"); return 1

        print("✅ E2E docker OK — confirm-gate + pago ejecutado")
        return 0
    finally:
        run(["docker", "compose", "-f", COMPOSE, "down", "-v"], cwd=OUT, capture_output=True)


if __name__ == "__main__":
    sys.exit(main())
