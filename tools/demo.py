#!/usr/bin/env python3
"""Demo/CI headless de TODO RAGorbit — sin red, sin pip, sin docker, sin browser.

    python3 tools/demo.py

Corre, en un solo comando y solo con stdlib:
  1) valida + genera + testea los 10 casos (modo mock),
  2) el e2e del chat de aerolínea con servicios HTTP reales (en threads) + idempotencia,
  3) la conciencia de contratos rechazando un flujo que no funcionaría.
Sale !=0 si algo falla.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def run(label, argv, cwd=ROOT):
    print(f"\n\033[1m▶ {label}\033[0m")
    r = subprocess.run(argv, cwd=cwd, capture_output=True, text=True)
    out = (r.stdout + r.stderr).strip()
    print("\n".join("   " + ln for ln in out.splitlines()[-14:]))
    return r.returncode == 0


def main() -> int:
    ok = True
    print("=" * 64)
    print(" RAGorbit · demo headless (stdlib puro, sin instalar nada)")
    print("=" * 64)

    ok &= run("1) Validar + generar + testear los 10 casos", [sys.executable, "tools/verify.py"])

    ok &= run("2) E2E chat de aerolínea con servicios reales + Kafka(mem)",
              [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
              cwd=ROOT / "e2e" / "airline-chat")

    # 3) contrato: rechazar lo que no funcionaría
    bad = {"irVersion": "1.0",
           "flow": {"id": "roto", "name": "Roto", "deploymentTarget": "chat-service", "defaults": {}},
           "nodes": [{"id": "in", "type": "io.input", "config": {}},
                      {"id": "agent", "type": "agent.react", "config": {"system": "x"}},
                      {"id": "out", "type": "io.output", "config": {}}],
           "edges": [{"source": "in", "sourcePort": "Message", "target": "agent", "targetPort": "Message"},
                      {"source": "agent", "sourcePort": "Message", "target": "out", "targetPort": "Any"}],
           "secrets": []}
    from ragorbit.validator import validate_flow
    res = validate_flow(bad)
    rejected = (not res.ok) and any("herramientas" in e or "Model" in e for e in res.errors)
    print("\n\033[1m▶ 3) Contrato: rechazar flujo inválido\033[0m")
    for e in res.errors:
        print("   ERROR", e)
    print(f"   -> {'rechazado correctamente ✅' if rejected else 'NO rechazó ❌'}")
    ok &= rejected

    print("\n" + "=" * 64)
    print(" RESULTADO:", "✅ TODO OK — el sistema corre completo sin dependencias" if ok else "❌ HAY FALLOS")
    print("=" * 64)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
