"""Node registry: descubre y carga manifests del catálogo (stdlib, sin deps).

Carga todos los `*.json` bajo `ragorbit/catalog/nodes/` (built-in) y, opcionalmente,
directorios de plugins externos pasados por env `RAGORBIT_PLUGIN_DIRS` (separados por `os.pathsep`).
Cada archivo puede ser un manifest (objeto) o una lista de manifests.

Esto es lo que hace al catálogo extensible (docs/05-extending.md): agregar un manifest
= aparece en paleta, forms, validación y codegen, sin tocar el core.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from . import resources

_CATALOG_PARTS = ("catalog", "nodes")


class Manifest:
    """Vista conveniente sobre un manifest de nodo."""

    def __init__(self, data: Dict[str, Any]):
        self.data = data
        self.type: str = data["type"]
        self.category: str = data["category"]
        self.title: str = data.get("title", self.type)
        self.description: str = data.get("description", "")
        self.ports: Dict[str, List[dict]] = data.get("ports", {}) or {}
        self.config_schema: dict = data.get("configSchema", {}) or {}
        self.secrets: List[str] = data.get("secrets", []) or []
        self.emitter: str = data.get("emitter", self.type)
        self.mock: dict = data.get("mock", {}) or {}

    # --- puertos -----------------------------------------------------------
    def inputs(self) -> List[dict]:
        return self.ports.get("inputs", []) or []

    def outputs(self) -> List[dict]:
        return self.ports.get("outputs", []) or []

    def resolve_port(self, side: str, ref: str) -> Optional[dict]:
        """Resuelve un puerto por su `name` o por su `type`.

        Los ejemplos nombran los puertos por su tipo (p.ej. "Message", "Retriever"),
        así que aceptamos match por name o por type. `ref == 'Any'` siempre resuelve.
        """
        ports = self.inputs() if side == "input" else self.outputs()
        ref_l = (ref or "").lower()
        ref_sing = ref_l[:-1] if ref_l.endswith("s") else ref_l  # tolera plural ("tools" -> "tool")
        for p in ports:
            cands = {p.get("name", "").lower(), p.get("type", "").lower()}
            if ref_l in cands or ref_sing in cands:
                return p
        if ref_l == "any":
            return {"name": "Any", "type": "Any"}
        # Fallback: si el nodo tiene un único puerto de este lado, la referencia se refiere a él
        # (cubre nombres genéricos como "input"/"output"/"documents" sin generar ruido).
        if len(ports) == 1:
            return ports[0]
        return None

    def default_config(self) -> Dict[str, Any]:
        """Defaults derivados del configSchema (para defaults inteligentes en la UI)."""
        props = (self.config_schema or {}).get("properties", {})
        out: Dict[str, Any] = {}
        for key, spec in props.items():
            if isinstance(spec, dict) and "default" in spec:
                out[key] = spec["default"]
        return out


class Registry:
    def __init__(self) -> None:
        self._by_type: Dict[str, Manifest] = {}

    def add(self, data: Dict[str, Any]) -> None:
        m = Manifest(data)
        self._by_type[m.type] = m

    def get(self, node_type: str) -> Optional[Manifest]:
        return self._by_type.get(node_type)

    def has(self, node_type: str) -> bool:
        return node_type in self._by_type

    def all(self) -> List[Manifest]:
        return sorted(self._by_type.values(), key=lambda m: (m.category, m.type))

    def by_category(self) -> Dict[str, List[Manifest]]:
        out: Dict[str, List[Manifest]] = {}
        for m in self.all():
            out.setdefault(m.category, []).append(m)
        return out

    def to_palette(self) -> List[dict]:
        """Forma serializable para `GET /registry/nodes` (paleta + forms)."""
        return [
            {
                "type": m.type,
                "category": m.category,
                "title": m.title,
                "description": m.description,
                "ports": m.ports,
                "configSchema": m.config_schema,
                "secrets": m.secrets,
                "defaults": m.default_config(),
            }
            for m in self.all()
        ]


def _iter_manifest_files(directory: Path) -> Iterable[Path]:
    if not directory.exists():
        return []
    return sorted(directory.rglob("*.json"))


def _load_raw(raw: Any) -> List[Dict[str, Any]]:
    """Un manifest puede venir solo o como array de manifests."""
    return raw if isinstance(raw, list) else [raw]


def _load_file(path: Path) -> List[Dict[str, Any]]:
    return _load_raw(json.loads(path.read_text(encoding="utf-8")))


def load_registry(extra_dirs: Optional[Iterable[Path]] = None) -> Registry:
    """Carga el catálogo built-in + dirs de plugins (env RAGORBIT_PLUGIN_DIRS + extra_dirs)."""
    reg = Registry()

    # Catálogo built-in: vía importlib.resources, para que funcione igual
    # instalado en disco y dentro del zipapp `ragorbit.pyz`.
    for res in resources.iter_files(*_CATALOG_PARTS, suffix=".json"):
        for data in _load_raw(json.loads(res.read_text(encoding="utf-8"))):
            reg.add(data)

    # Plugins: siempre directorios del sistema de archivos.
    dirs: List[Path] = []
    env = os.environ.get("RAGORBIT_PLUGIN_DIRS", "")
    if env:
        dirs += [Path(p) for p in env.split(os.pathsep) if p]
    if extra_dirs:
        dirs += [Path(p) for p in extra_dirs]
    for d in dirs:
        for f in _iter_manifest_files(d):
            for data in _load_file(f):
                reg.add(data)
    return reg
