"""Validador del Flow IR (stdlib, sin deps). Implementa docs/01-concepts.md §2.2.

Devuelve `errors` (rompen la validez) y `warnings` (mejoras / posibles problemas).
Un flujo es válido si no hay errors. Los mensajes son ACCIONABLES (docs/06).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .registry import Registry, load_registry

ENTRY_TYPES = {"io.input", "io.stt", "io.event-source", "io.trigger", "io.batch"}
OUTPUT_TYPES = {"io.output", "io.panel", "io.notify"}


@dataclass
class ValidationResult:
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


# Coerciones implícitas semánticamente sanas (texto): un mensaje puede usarse como query y viceversa.
_COERCIONS = {("Message", "Query"), ("Query", "Message")}


def _types_compatible(out_type: str, in_type: str) -> bool:
    return (
        out_type == in_type
        or out_type == "Any"
        or in_type == "Any"
        or (out_type, in_type) in _COERCIONS
    )


def validate_flow(flow: Dict[str, Any], registry: Optional[Registry] = None,
                  *, strict_secrets: bool = False) -> ValidationResult:
    reg = registry or load_registry()
    res = ValidationResult()

    if flow.get("irVersion") != "1.0":
        res.errors.append("irVersion debe ser '1.0'.")

    f = flow.get("flow", {})
    for k in ("id", "name", "deploymentTarget"):
        if not f.get(k):
            res.errors.append(f"flow.{k} es obligatorio.")

    nodes = flow.get("nodes", [])
    edges = flow.get("edges", [])
    secrets = flow.get("secrets", [])

    ids: List[str] = [n.get("id") for n in nodes]
    id_set = set(ids)
    if len(ids) != len(id_set):
        res.errors.append("Hay ids de nodo duplicados; cada nodo debe tener id único.")

    node_by_id: Dict[str, dict] = {n.get("id"): n for n in nodes}

    # Regla 1 + 2: tipo existe y config requerida presente
    for n in nodes:
        nid, ntype = n.get("id"), n.get("type")
        m = reg.get(ntype)
        if m is None:
            res.errors.append(
                f"Nodo '{nid}': tipo desconocido '{ntype}'. Revisa el catálogo (docs/02) o agrega un manifest."
            )
            continue
        required = (m.config_schema or {}).get("required", []) or []
        cfg = n.get("config", {}) or {}
        for rk in required:
            if rk not in cfg or cfg.get(rk) in (None, ""):
                res.errors.append(
                    f"Nodo '{nid}' ({ntype}): falta el campo de config requerido '{rk}'."
                )

    # Regla 3: aristas con endpoints válidos y tipos compatibles
    incoming: Dict[Tuple[str, str], int] = {}
    for e in edges:
        s, sp, t, tp = e.get("source"), e.get("sourcePort"), e.get("target"), e.get("targetPort")
        if s not in id_set:
            res.errors.append(f"Arista con source inexistente '{s}'.")
            continue
        if t not in id_set:
            res.errors.append(f"Arista con target inexistente '{t}'.")
            continue
        sm = reg.get(node_by_id[s].get("type"))
        tm = reg.get(node_by_id[t].get("type"))
        if not sm or not tm:
            continue
        sport = sm.resolve_port("output", sp)
        tport = tm.resolve_port("input", tp)
        if sport is None:
            opts = ", ".join(p["type"] for p in sm.outputs()) or "(ninguno)"
            res.warnings.append(
                f"La conexión sale de '{s}' por un puerto '{sp}' que no existe. "
                f"Salidas válidas de {sm.type}: {opts}. Reconéctala a una de ellas."
            )
        if tport is None:
            opts = ", ".join(p["type"] for p in tm.inputs()) or "(este nodo no acepta entradas)"
            res.warnings.append(
                f"La conexión entra a '{t}' por un puerto '{tp}' que no existe. "
                f"Entradas válidas de {tm.type}: {opts}. Reconéctala a una de ellas."
            )
        if sport and tport and not _types_compatible(sport["type"], tport["type"]):
            res.errors.append(
                f"Arista {s}.{sp} -> {t}.{tp}: tipos incompatibles "
                f"({sport['type']} -> {tport['type']}). Conecta tipos compatibles."
            )
        if tport:
            incoming[(t, tport["type"])] = incoming.get((t, tport["type"]), 0) + 1

    # Regla 4: puertos de entrada requeridos conectados
    for n in nodes:
        m = reg.get(n.get("type"))
        if not m:
            continue
        for p in m.inputs():
            if p.get("required") and incoming.get((n.get("id"), p["type"]), 0) == 0:
                res.errors.append(
                    f"Nodo '{n.get('id')}' ({m.type}): falta conectar una entrada requerida "
                    f"de tipo {p['type']} ('{p.get('name')}')."
                )

    # Regla 5: al menos una entrada y una salida
    entries = [n for n in nodes if n.get("type") in ENTRY_TYPES]
    outputs = [n for n in nodes if n.get("type") in OUTPUT_TYPES]
    if not entries:
        res.errors.append("El flujo no tiene nodo de entrada (io.input / io.event-source / io.batch / io.trigger / io.stt).")
    if not outputs:
        res.warnings.append("El flujo no tiene nodo de salida (io.output / io.panel / io.notify).")

    # Regla 6: aciclicidad salvo edges loop:true
    if _has_cycle(nodes, [e for e in edges if not e.get("loop")]):
        res.errors.append("El grafo tiene un ciclo en aristas no marcadas loop:true. Marca el ciclo con loop:true (ReAct/feedback) o elimínalo.")

    # Regla 7: secretos referenciados existen en secrets[]
    declared = {s.get("name") for s in secrets}
    for n in nodes:
        m = reg.get(n.get("type"))
        cfg = n.get("config", {}) or {}
        ref = cfg.get("apiKeyRef")
        if ref and ref not in declared:
            res.warnings.append(f"Nodo '{n.get('id')}': el secreto '{ref}' no está declarado en secrets[].")

    # Reglas 8: contratos / precondiciones semánticas (qué puede conectarse a qué).
    from .contracts import check_contracts
    c_err, c_warn = check_contracts(flow, reg, strict_secrets=strict_secrets)
    res.errors.extend(c_err)
    res.warnings.extend(c_warn)
    return res


def _has_cycle(nodes: List[dict], edges: List[dict]) -> bool:
    adj: Dict[str, List[str]] = {n.get("id"): [] for n in nodes}
    for e in edges:
        if e.get("source") in adj and e.get("target") in adj:
            adj[e["source"]].append(e["target"])
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {nid: WHITE for nid in adj}

    def dfs(u: str) -> bool:
        color[u] = GRAY
        for v in adj[u]:
            if color[v] == GRAY:
                return True
            if color[v] == WHITE and dfs(v):
                return True
        color[u] = BLACK
        return False

    return any(color[nid] == WHITE and dfs(nid) for nid in adj)


def topological_order(flow: Dict[str, Any]) -> List[dict]:
    """Orden topológico de nodos (ignora aristas loop:true para romper ciclos)."""
    nodes = flow.get("nodes", [])
    node_by_id = {n.get("id"): n for n in nodes}
    edges = [e for e in flow.get("edges", []) if not e.get("loop")]
    indeg = {n.get("id"): 0 for n in nodes}
    adj: Dict[str, List[str]] = {n.get("id"): [] for n in nodes}
    for e in edges:
        if e.get("source") in adj and e.get("target") in indeg:
            adj[e["source"]].append(e["target"])
            indeg[e["target"]] += 1
    queue = [nid for nid, d in indeg.items() if d == 0]
    order: List[dict] = []
    while queue:
        queue.sort()  # determinista
        nid = queue.pop(0)
        order.append(node_by_id[nid])
        for v in adj[nid]:
            indeg[v] -= 1
            if indeg[v] == 0:
                queue.append(v)
    if len(order) != len(nodes):  # ciclo: cae a orden de declaración
        return list(nodes)
    return order
