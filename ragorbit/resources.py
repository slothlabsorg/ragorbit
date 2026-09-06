"""Acceso a los datos del paquete (catálogo, spec, plantillas) — stdlib.

`Path(__file__).parent / "catalog"` funciona en una instalación normal pero **no**
dentro de un zipapp: ahí el paquete vive comprimido y no hay directorio real que
recorrer. Como RAGorbit se distribuye también como `ragorbit.pyz` de un solo
archivo, todo acceso a datos del paquete pasa por aquí.

`importlib.resources.files()` devuelve un *Traversable* que funciona en los dos
casos, así que el resto del código no tiene que saber cómo está empaquetado.
"""
from __future__ import annotations

import shutil
from importlib.resources import files
from pathlib import Path
from typing import Iterator


def package_root():
    """Raíz del paquete `ragorbit` como Traversable (disco o zip)."""
    return files("ragorbit")


def resource(*parts: str):
    """Un recurso del paquete por su ruta relativa: resource('catalog', 'nodes')."""
    node = package_root()
    for part in parts:
        node = node.joinpath(part)
    return node


def read_text(*parts: str) -> str:
    return resource(*parts).read_text(encoding="utf-8")


def iter_files(*parts: str, suffix: str | None = None) -> Iterator:
    """Recorre recursivamente un directorio del paquete.

    Devuelve Traversables de archivo. `Traversable` no tiene `rglob`, así que se
    baja a mano — es la diferencia entre funcionar y no funcionar dentro del zip.
    """
    root = resource(*parts)
    if not root.is_dir():
        return

    def walk(node) -> Iterator:
        for child in sorted(node.iterdir(), key=lambda c: c.name):
            if child.is_dir():
                yield from walk(child)
            elif suffix is None or child.name.endswith(suffix):
                yield child

    yield from walk(root)


def relative_name(child, *root_parts: str) -> str:
    """Ruta de `child` relativa al directorio raíz dado, con separadores `/`.

    Traversable no expone rutas relativas, así que se reconstruye desde el nombre
    completo. Funciona igual con un path de disco y con una entrada de zip.
    """
    root = str(resource(*root_parts))
    full = str(child)
    if full.startswith(root):
        return full[len(root):].lstrip("/\\").replace("\\", "/")
    return child.name


def copy_tree(dest: Path, *parts: str) -> None:
    """Copia un directorio del paquete al sistema de archivos."""
    dest.mkdir(parents=True, exist_ok=True)
    for child in iter_files(*parts):
        rel = relative_name(child, *parts)
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        with child.open("rb") as src, open(target, "wb") as out:
            shutil.copyfileobj(src, out)
