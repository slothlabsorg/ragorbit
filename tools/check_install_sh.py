#!/usr/bin/env python3
"""Comprueba dist/install.sh antes de publicarlo.

    python3 tools/check_install_sh.py

El instalador es la puerta de entrada: si falla, el usuario no llega a probar
RAGorbit. Y falla en un sitio donde nada más lo cubre — se sirve desde
`slothlabs.org/install/ragorbit` y se ejecuta con `sh`, no con bash.

Lo que revisa:

1. **Sintaxis** con `sh -n`.
2. **`$VAR` pegado a un carácter no ASCII.** `"$VERSION…"` hace que algunos
   shells lean los bytes UTF-8 de los puntos suspensivos como parte del nombre
   de la variable; con `set -u` eso aborta el instalador con "unbound variable".
   Pasó de verdad. Hay que escribir `"${VERSION}…"`.
3. **Bashismos** en un script que declara `#!/bin/sh`.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "dist" / "install.sh"

# Construcciones que no son POSIX y que `sh` (dash) rechaza o interpreta mal.
BASHISMS = [
    (re.compile(r'\[\['), '[[ ... ]] — usa [ ... ]'),
    (re.compile(r'\bfunction\s+\w+\s*\('), 'function nombre() — usa nombre()'),
    (re.compile(r'\$\(\(.*\+\+.*\)\)'), '++ dentro de $(( )) no es POSIX'),
    (re.compile(r'\becho\s+-e\b'), 'echo -e — usa printf'),
    (re.compile(r'\bsource\s'), 'source — usa .'),
    (re.compile(r'\$\{\w+\[\d*\]\}'), 'arrays — no existen en POSIX sh'),
    (re.compile(r'\b(declare|local)\s+-[aA]\b'), 'declare/local -a — no es POSIX'),
]


def main() -> int:
    if not SCRIPT.is_file():
        print(f"✗ no existe {SCRIPT}")
        return 1

    problems: list[str] = []
    src = SCRIPT.read_text(encoding="utf-8")

    # 1) sintaxis
    check = subprocess.run(["sh", "-n", str(SCRIPT)], capture_output=True, text=True)
    if check.returncode != 0:
        problems.append(f"sh -n falla: {check.stderr.strip()}")

    for lineno, line in enumerate(src.splitlines(), 1):
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue

        # 2) $VAR seguido de un carácter no ASCII
        for m in re.finditer(r"\$([A-Za-z_][A-Za-z0-9_]*)(.)", line):
            nxt = m.group(2)
            if ord(nxt) > 127:
                problems.append(
                    f"línea {lineno}: ${m.group(1)} va pegado a {nxt!r} "
                    f"(U+{ord(nxt):04X}); escribe ${{{m.group(1)}}}"
                )

        # 3) bashismos
        for pattern, msg in BASHISMS:
            if pattern.search(line):
                problems.append(f"línea {lineno}: {msg}")

    if problems:
        print(f"✗ {len(problems)} problema(s) en dist/install.sh:\n")
        for p in problems:
            print(f"  {p}")
        return 1

    print("✅ dist/install.sh: sintaxis POSIX válida, sin variables pegadas a UTF-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
