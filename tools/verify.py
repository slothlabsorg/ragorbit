#!/usr/bin/env python3
"""Verificación end-to-end de RAGorbit en modo mock (stdlib, sin red ni deps).

Valida los 10 ejemplos, genera sus proyectos, corre los tests mock de cada uno y
audita el CÓDIGO REAL generado (compila + ningún nodo sin implementar).

Uso:  python3 tools/verify.py
Sale con código !=0 si algo falla. Sirve como CI sin dependencias.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ragorbit.codegen import generate_project  # noqa: E402
from ragorbit.registry import load_registry  # noqa: E402
from ragorbit.validator import validate_flow  # noqa: E402


def audit_real_code(out: Path) -> list:
    """Audita el modo real generado. Devuelve la lista de problemas encontrados.

    Existe porque el codegen emitía durante mucho tiempo un `return state` por
    nodo: el artefacto compilaba, los tests mock pasaban, y el modo real no hacía
    nada. Un nodo que no hace nada tiene que ser un fallo del CI, no un detalle
    que se descubre en producción.
    """
    problems = []
    for rel in ("app/nodes.py", "app/graph.py"):
        path = out / rel
        if not path.is_file():
            continue
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            problems.append(f"{rel}: no compila ({exc})")
            continue
        if rel != "app/nodes.py":
            continue
        for fn in (n for n in tree.body if isinstance(n, ast.FunctionDef)):
            if not fn.name.startswith("node_"):
                continue
            # Cuerpo sin el docstring inicial.
            body = [s for s in fn.body
                    if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant)
                            and isinstance(s.value.value, str))]
            if not body:
                problems.append(f"{rel}: {fn.name} está vacío")
                continue
            if len(body) == 1 and isinstance(body[0], ast.Return):
                value = body[0].value
                if isinstance(value, ast.Name) and value.id == "state":
                    problems.append(f"{rel}: {fn.name} es un no-op (`return state`)")
            if any(isinstance(s, ast.Raise) and isinstance(s.exc, ast.Call)
                   and isinstance(s.exc.func, ast.Name)
                   and s.exc.func.id == "NotImplementedError" for s in body):
                problems.append(f"{rel}: {fn.name} sin implementación real (NotImplementedError)")
    return problems


def main() -> int:
    reg = load_registry()
    flows = sorted((ROOT / "examples").glob("*/flow.json"))
    print(f"RAGorbit verify · {len(reg.all())} tipos de nodo · {len(flows)} ejemplos\n")
    ok = True
    with tempfile.TemporaryDirectory() as td:
        for fj in flows:
            flow = json.loads(fj.read_text(encoding="utf-8"))
            fid = flow["flow"]["id"]
            res = validate_flow(flow, reg)
            if not res.ok:
                print(f"❌ {fid}: inválido"); [print("   ", e) for e in res.errors]; ok = False; continue
            out = Path(td) / fid
            generate_project(flow, out, reg)
            r = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"],
                               cwd=out, capture_output=True, text=True)
            passed = r.returncode == 0
            ran = next((ln for ln in r.stderr.splitlines() if ln.startswith("Ran ")), "")
            problems = audit_real_code(out)
            mark = "✅" if passed and not problems else "❌"
            real = "real OK" if not problems else f"{len(problems)} problema(s) en modo real"
            print(f"{mark} {fid}: válido + genera + tests ({ran}) · {real}")
            if not passed:
                print(r.stderr[-800:]); ok = False
            for p in problems:
                print(f"     {p}"); ok = False
    print("\n" + ("✅ TODO OK" if ok else "❌ HAY FALLOS"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
