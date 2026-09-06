"""Ejecutor del flujo en modo mock (stdlib).

Interpreta un "compiled flow" (Flow IR ya resuelto: cada arista trae sourceType y
targetType) ejecutando el comportamiento mock de cada nodo en orden topológico.
La dataflow se enruta por TIPO de puerto.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import behaviors as B


class Context:
    """Estado compartido durante una ejecución mock."""

    def __init__(self, fixtures: Dict[str, Any], seed_message: str, seed_events: Optional[List[dict]] = None,
                 integration: Optional[Dict[str, Any]] = None):
        self.fixtures = fixtures or {}
        self.seed_message = seed_message
        self.seed_events = seed_events or []
        # integration: {"http": callable(baseUrl, operation, payload)->dict, "bus": callable(event)->None}
        # Si está presente, los tools llaman servicios HTTP reales y el audit publica a Kafka/bus.
        self.integration = integration or {}
        self.trace: Dict[str, Any] = {}
        self.audit: List[dict] = []
        self.notifications: List[dict] = []
        self.escalations: List[dict] = []
        self.metrics: List[dict] = []
        self.feedback: List[dict] = []
        self.citations: List[dict] = []

    def fx(self, node_id: str, default=None):
        return self.fixtures.get(node_id, default)


def _toposort(nodes: List[dict], edges: List[dict]) -> List[dict]:
    by_id = {n["id"]: n for n in nodes}
    real = [e for e in edges if not e.get("loop")]
    indeg = {n["id"]: 0 for n in nodes}
    adj: Dict[str, List[str]] = {n["id"]: [] for n in nodes}
    for e in real:
        if e["source"] in adj and e["target"] in indeg:
            adj[e["source"]].append(e["target"])
            indeg[e["target"]] += 1
    queue = sorted([nid for nid, d in indeg.items() if d == 0])
    order: List[dict] = []
    while queue:
        nid = queue.pop(0)
        order.append(by_id[nid])
        for v in sorted(adj[nid]):
            indeg[v] -= 1
            if indeg[v] == 0:
                queue.append(v)
                queue.sort()
    if len(order) != len(nodes):  # ciclo no marcado: orden de declaración
        return list(nodes)
    return order


def _gather_inputs(node: dict, edges: List[dict], outputs: Dict[str, Dict[str, Any]]) -> Dict[str, List[Any]]:
    """Reúne las entradas del nodo agrupadas por tipo de puerto (listas)."""
    inputs: Dict[str, List[Any]] = {}
    for e in edges:
        if e.get("target") != node["id"] or e.get("loop"):
            continue
        src_out = outputs.get(e["source"], {})
        val = src_out.get(e["sourceType"])
        if val is None and src_out:
            # fallback: si el tipo exacto no está, toma el primer output disponible
            val = next(iter(src_out.values()))
        inputs.setdefault(e["targetType"], []).append(val)
    return inputs


OUTPUT_NODE_TYPES = {"io.output", "io.panel", "io.notify"}


def run_flow(compiled: Dict[str, Any], fixtures: Dict[str, Any], seed_message: str = "Hola",
             seed_events: Optional[List[dict]] = None, integration: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    nodes = compiled["nodes"]
    edges = compiled["edges"]
    ctx = Context(fixtures, seed_message, seed_events, integration)

    outputs: Dict[str, Dict[str, Any]] = {}
    order = _toposort(nodes, edges)
    for node in order:
        inputs = _gather_inputs(node, edges, outputs)
        fn = B.BEHAVIORS.get(node.get("behavior"), B.passthrough)
        try:
            out = fn(node, inputs, ctx) or {}
        except Exception as exc:  # un nodo no debe tumbar todo el mock
            out = {"_error": f"{type(exc).__name__}: {exc}"}
        outputs[node["id"]] = out

    final = {}
    for node in nodes:
        if node["type"] in OUTPUT_NODE_TYPES:
            final[node["id"]] = outputs.get(node["id"], {})

    return {
        "flow": compiled.get("flow", {}),
        "outputs": outputs,
        "final": final,
        "response": _primary_response(nodes, outputs),
        "trace": ctx.trace,
        "audit": ctx.audit,
        "notifications": ctx.notifications,
        "escalations": ctx.escalations,
        "metrics": ctx.metrics,
        "feedback": ctx.feedback,
        "citations": ctx.citations,
    }


def _primary_response(nodes: List[dict], outputs: Dict[str, Dict[str, Any]]) -> Any:
    """Mejor esfuerzo: la respuesta principal para mostrar en el panel de chat."""
    for node in reversed(nodes):
        if node["type"] in OUTPUT_NODE_TYPES:
            o = outputs.get(node["id"], {})
            for key in ("Message", "Decision", "Any"):
                if o.get(key) is not None:
                    return o[key]
            non_null = [v for v in o.values() if v is not None]
            if non_null:
                return non_null[0]
    # si no hay nodo de salida, devuelve el último Message/Decision producido
    for node in reversed(nodes):
        o = outputs.get(node["id"], {})
        for key in ("Message", "Decision", "Any"):
            if o.get(key) is not None:
                return o[key]
    return None
