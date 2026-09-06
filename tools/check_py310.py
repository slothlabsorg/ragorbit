#!/usr/bin/env python3
"""Comprueba que el código corre en Python 3.10/3.11, no solo en el intérprete local.

    python3 tools/check_py310.py

Python 3.12 relajó las f-strings (PEP 701): a partir de ahí se puede poner una
barra invertida dentro de `{...}`. En 3.10 y 3.11 eso es un `SyntaxError` en
tiempo de importación — el módulo entero no carga.

Como `pyproject.toml` declara `requires-python = ">=3.10"`, escribir esto en una
máquina con 3.12+ rompe a los usuarios de 3.10 sin que salte nada en local. Este
chequeo recorre el AST y encuentra el caso sin necesitar un intérprete viejo.

`ast.parse(..., feature_version=(3, 10))` NO lo detecta: la restricción es del
tokenizador y feature_version no la emula.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN_DIRS = ("ragorbit", "tools", "apps", "e2e", "demo")


def _delimiter_at(src_lines: list, node: ast.JoinedStr) -> str:
    """Comillas que delimitan esta f-string, leídas del código fuente.

    El AST no las guarda, así que se leen desde la posición del nodo. Hace falta
    para saber qué comilla NO se puede reusar dentro de `{...}`.
    """
    try:
        line = src_lines[node.lineno - 1]
    except IndexError:
        return ""
    rest = line[node.col_offset:]
    for delim in ('"""', "'''", '"', "'"):
        # Salta el prefijo (f, rf, fr, F…) antes de la comilla.
        idx = rest.find(delim)
        if idx != -1 and idx <= 3:
            return delim
    return ""


def offenders(path: Path) -> list:
    src = path.read_text(encoding="utf-8")
    src_lines = src.splitlines()
    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError as exc:
        # Si este script corre EN 3.10/3.11, el propio parseo ya falla y ese es
        # el diagnóstico más fiable que existe.
        return [(exc.lineno or 0, f"no compila: {exc.msg}")]

    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.JoinedStr):
            continue
        delim = _delimiter_at(src_lines, node)
        for part in node.values:
            if not isinstance(part, ast.FormattedValue):
                continue
            segment = ast.get_source_segment(src, part.value)
            if not segment:
                continue
            if "\\" in segment:
                found.append((
                    part.value.lineno,
                    f"barra invertida dentro de una expresión de f-string "
                    f"(requiere 3.12+): {segment.strip()[:70]}",
                ))
            # Reusar la comilla de la propia f-string dentro de `{...}` también
            # es 3.12+. Para `'''`/`\"\"\"` basta con que aparezca; para una
            # comilla simple, que aparezca ese mismo carácter.
            if delim and delim in segment:
                found.append((
                    part.value.lineno,
                    f"comillas {delim} reutilizadas dentro de la f-string que las "
                    f"delimita (requiere 3.12+): {segment.strip()[:70]}",
                ))
    return found


def main() -> int:
    problems = []
    for d in SCAN_DIRS:
        base = ROOT / d
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            for lineno, msg in offenders(path):
                problems.append(f"{path.relative_to(ROOT)}:{lineno}: {msg}")

    if problems:
        print(f"✗ {len(problems)} problema(s) de compatibilidad con Python 3.10/3.11:\n")
        for p in problems:
            print(f"  {p}")
        print("\nSaca la expresión a una variable antes de la f-string.")
        return 1

    print("✅ compatible con Python 3.10+ (sin barras invertidas en f-strings)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
