"""Conciencia de contratos: qué puede conectarse a qué y qué precondiciones debe
cumplir un flujo para que el artefacto generado FUNCIONE de verdad.

Esto va más allá de los tipos de puerto (validator.py): comprueba precondiciones
semánticas (un agente sin tools no sirve, un store sin embeddings no recupera,
un guardrail debe envolver un tool, etc.) y requisitos de auth/secretos por nodo.
Se usa en validate_flow y, en modo estricto, bloquea la generación.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Set, Tuple

# --------------------------------------------------------------------------
# Requisitos por tipo de nodo: (descripción, función(got_types) -> bool ok)
# `got_types` = conjunto de tipos de puerto que ENTRAN al nodo por aristas.
# --------------------------------------------------------------------------
def _needs(*types: str) -> Callable[[Set[str]], bool]:
    return lambda got: all(t in got for t in types)


def _needs_any(*types: str) -> Callable[[Set[str]], bool]:
    return lambda got: bool(set(types) & got)


# error|warn, mensaje accionable, predicado
NODE_REQUIREMENTS: Dict[str, List[Tuple[str, str, Callable[[Set[str]], bool]]]] = {
    "agent.react": [
        ("error", "El agente necesita un Model conectado (model.llm).", _needs("Model")),
        ("error", "El agente no tiene herramientas: conecta al menos un tool.* o un tool.retriever.", _needs_any("Tool", "Retriever")),
    ],
    "agent.fanout": [
        ("error", "El fan-out necesita una fuente de eventos (Event) conectada.", _needs("Event")),
        ("warn", "El fan-out no tiene tools; los sub-agentes no podrán actuar.", _needs_any("Tool")),
    ],
    "logic.prompt": [
        ("error", "La síntesis necesita un Model conectado (model.llm).", _needs("Model")),
    ],
    "logic.structured": [
        ("error", "La salida estructurada necesita un Model conectado (model.llm).", _needs("Model")),
    ],
    "logic.citations": [
        ("error", "Las citas necesitan los Chunks fuente conectados para poder citar.", _needs("Chunks")),
    ],
    "store.pgvector": [("error", "El store necesita Embeddings (conecta un model.embedding).", _needs("Embeddings"))],
    "store.qdrant": [("error", "El store necesita Embeddings (conecta un model.embedding).", _needs("Embeddings"))],
    "store.chroma": [("error", "El store necesita Embeddings (conecta un model.embedding).", _needs("Embeddings"))],
    "store.neo4j": [("error", "El store necesita Embeddings (conecta un model.embedding).", _needs("Embeddings"))],
    "store.multi-index": [("error", "Multi-index necesita Retrievers o Documents de entrada.", _needs_any("Retriever", "Documents"))],
    "retrieval.vector": [("error", "El recuperador necesita un Retriever (conecta un store.*).", _needs("Retriever"))],
    "retrieval.graph": [("error", "El recuperador necesita un Retriever (conecta un store.neo4j).", _needs("Retriever"))],
    "retrieval.hybrid": [("error", "El recuperador necesita un Retriever (conecta un store.*).", _needs("Retriever"))],
    "retrieval.parent-child": [("error", "El recuperador necesita un Retriever (conecta un store.*).", _needs("Retriever"))],
    "retrieval.router": [("error", "El router necesita Retrievers (conecta un store.multi-index).", _needs("Retriever"))],
    "retrieval.reranker": [("error", "El reranker necesita Chunks de entrada (conecta un retrieval.*).", _needs("Chunks"))],
    "tool.retriever": [("error", "Este tool expone un retriever: conéctale un Retriever o Chunks.", _needs_any("Retriever", "Chunks"))],
    "guardrail.confirm": [("error", "El guardrail debe envolver un Tool (conéctale un tool.*).", _needs("Tool"))],
    "guardrail.idempotency": [("error", "El guardrail debe envolver un Tool (conéctale un tool.*).", _needs("Tool"))],
    "guardrail.resilience": [("error", "El guardrail debe envolver un Tool (conéctale un tool.*).", _needs("Tool"))],
    "guardrail.pre-tool": [("error", "El guardrail debe envolver un Tool (conéctale un tool.*).", _needs("Tool"))],
}

# Tipos de nodo que representan un "tool transaccional" (efectos secundarios).
TRANSACTIONAL_HINTS = ("pay", "pago", "payment", "charge", "cobro", "confirm", "book", "order",
                       "refund", "devol", "return", "cancel", "reembolso")


def _incoming_types(flow: Dict[str, Any], reg) -> Dict[str, Set[str]]:
    """Tipos de puerto que entran a cada nodo (resueltos vía registry)."""
    by_id = {n["id"]: n for n in flow.get("nodes", [])}
    incoming: Dict[str, Set[str]] = {n["id"]: set() for n in flow.get("nodes", [])}
    for e in flow.get("edges", []):
        if e.get("loop"):
            continue
        tnode = by_id.get(e.get("target"))
        if not tnode:
            continue
        tm = reg.get(tnode["type"])
        tp = tm.resolve_port("input", e.get("targetPort")) if tm else None
        incoming[e["target"]].add((tp or {}).get("type", e.get("targetPort")))
    return incoming


def check_contracts(flow: Dict[str, Any], reg, *, strict_secrets: bool = False) -> Tuple[List[str], List[str]]:
    """Devuelve (errors, warnings) por incumplimiento de contratos/precondiciones."""
    errors: List[str] = []
    warnings: List[str] = []
    incoming = _incoming_types(flow, reg)
    declared_secrets = {s.get("name") for s in flow.get("secrets", [])}

    for n in flow.get("nodes", []):
        nid, ntype = n["id"], n["type"]
        got = incoming.get(nid, set())
        for level, msg, pred in NODE_REQUIREMENTS.get(ntype, []):
            if not pred(got):
                (errors if level == "error" else warnings).append(f"Nodo '{nid}' ({ntype}): {msg}")

        # Auth/secretos: un nodo con secretos declarados en su manifest debe tenerlos en secrets[]
        m = reg.get(ntype)
        if m:
            for sec in m.secrets:
                if sec not in declared_secrets:
                    lvl = "error" if strict_secrets else "warn"
                    (errors if lvl == "error" else warnings).append(
                        f"Nodo '{nid}' ({ntype}): requiere el secreto '{sec}'. Decláralo en secrets[] (y en producción, en el gestor de secretos).")

    # Guardrails de confirmación/idempotencia deberían envolver tools transaccionales
    by_id = {n["id"]: n for n in flow.get("nodes", [])}
    for e in flow.get("edges", []):
        s, t = by_id.get(e.get("source")), by_id.get(e.get("target"))
        if not s or not t:
            continue
        if t["type"] in ("guardrail.confirm", "guardrail.idempotency") and s["type"].startswith("tool."):
            name = (s.get("label", "") + " " + str(s.get("config", {}).get("name", ""))).lower()
            # informativo: confirmamos que el guardrail protege algo transaccional
            if not any(h in name for h in TRANSACTIONAL_HINTS):
                warnings.append(
                    f"Guardrail '{t['id']}' envuelve el tool '{s['id']}', que no parece transaccional; "
                    f"normalmente confirm/idempotency protegen pagos/reservas.")
    return errors, warnings
