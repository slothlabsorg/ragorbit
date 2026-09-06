#!/usr/bin/env python3
"""Empaqueta RAGorbit como un zipapp de un solo archivo: `ragorbit.pyz`.

    python3 tools/build_pyz.py [--out dist/ragorbit.pyz]

Corre con cualquier `python3` (3.10+) sin instalar nada:

    python3 ragorbit.pyz list-nodes
    python3 ragorbit.pyz generate examples/09-hr-policy-assistant/flow.json --out ./mi-bot

Se puede hacer porque el engine no tiene dependencias. Solo stdlib (`zipapp`), así
que el build no necesita red — el mismo argumento que el resto del proyecto.

Incluye el paquete `ragorbit/` con su catálogo, spec y plantillas. NO incluye
`examples/` ni `docs/`: el zipapp es la herramienta, y los templates se descargan
del release (`ragorbit-course-starter.zip`) o se clonan del repo.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import zipapp
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Lo que no tiene sentido meter en el zipapp.
EXCLUDE_DIRS = {"__pycache__", ".pytest_cache", ".mypy_cache"}
EXCLUDE_SUFFIXES = {".pyc", ".pyo"}


def _copy_package(dest: Path) -> None:
    """Copia ragorbit/ dentro de dest, sin basura de compilación."""
    def ignore(_dir, names):
        return [
            n for n in names
            if n in EXCLUDE_DIRS or Path(n).suffix in EXCLUDE_SUFFIXES
        ]

    shutil.copytree(ROOT / "ragorbit", dest / "ragorbit", ignore=ignore)


def build(out: Path, compress: bool = True) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        staging = Path(td)
        _copy_package(staging)

        # zipapp ejecuta `__main__.py` de la raíz del archivo, no del paquete.
        (staging / "__main__.py").write_text(
            '"""Punto de entrada del zipapp de RAGorbit."""\n'
            "import sys\n\n"
            "from ragorbit.__main__ import main\n\n"
            'if __name__ == "__main__":\n'
            "    sys.exit(main())\n",
            encoding="utf-8",
        )

        zipapp.create_archive(
            staging,
            target=out,
            interpreter="/usr/bin/env python3",
            compressed=compress,
        )
    out.chmod(0o755)
    return out


def smoke_test(pyz: Path) -> None:
    """El .pyz tiene que hacer algo, no solo existir.

    Corre `list-nodes` en un subproceso y comprueba que el catálogo viajó dentro
    del archivo — es el fallo clásico de un zipapp: empaqueta el código pero deja
    fuera los datos, y falla en la máquina del usuario y no en el CI.
    """
    result = subprocess.run(
        [sys.executable, str(pyz), "list-nodes"],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        raise SystemExit(f"✗ el .pyz no corre:\n{result.stderr[-2000:]}")
    if "Total:" not in result.stdout:
        raise SystemExit(f"✗ `list-nodes` no listó el catálogo:\n{result.stdout[-2000:]}")
    total_line = next(l for l in result.stdout.splitlines() if l.startswith("Total:"))
    print(f"  smoke test: {total_line}")

    # Y que pueda generar un artefacto: prueba que las plantillas también viajaron.
    with tempfile.TemporaryDirectory() as td:
        gen = subprocess.run(
            [sys.executable, str(pyz), "generate",
             str(ROOT / "examples" / "09-hr-policy-assistant" / "flow.json"),
             "--out", str(Path(td) / "artifact")],
            capture_output=True, text=True, timeout=120,
        )
        if gen.returncode != 0:
            raise SystemExit(f"✗ el .pyz no genera:\n{gen.stderr[-2000:]}")
        if not (Path(td) / "artifact" / "app" / "engine.py").is_file():
            raise SystemExit("✗ artefacto incompleto: faltan las plantillas en el .pyz")
    print("  smoke test: genera un artefacto completo ✓")


def main() -> int:
    ap = argparse.ArgumentParser(description="Construye ragorbit.pyz")
    ap.add_argument("--out", default="dist/ragorbit.pyz")
    ap.add_argument("--no-compress", action="store_true")
    ap.add_argument("--skip-smoke", action="store_true")
    args = ap.parse_args()

    out = build(Path(args.out), compress=not args.no_compress)
    size_kb = out.stat().st_size / 1024
    print(f"✅ {out} ({size_kb:.0f} KB)")
    if not args.skip_smoke:
        smoke_test(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
