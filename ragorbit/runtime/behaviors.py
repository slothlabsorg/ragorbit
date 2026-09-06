"""Comportamientos mock por tipo de nodo (stdlib, deterministas).

Convenciones de valores que viajan por los puertos:
  Documents/Chunks : list[ {text, metadata, source} ]
  Retriever        : { "kind":"retriever", "chunks":[...] }
  Embeddings/Model : { "kind": "embeddings"|"model", "name": str }
  Tool             : { "kind":"tool", "name":str, "result":any, "wrappers":{...} }
  Message/Query    : str
  Decision         : dict
  Event            : dict
Cada función recibe (node, inputs, ctx) y devuelve {tipo_de_puerto_de_salida: valor}.
`inputs` está agrupado por tipo de puerto como listas.
"""
from __future__ import annotations

from typing import Any, Dict, List


# ---------- helpers ----------
def _first(inputs: Dict[str, List[Any]], t: str, default=None):
    vals = inputs.get(t)
    if vals:
        return vals[0]
    return default


def _all(inputs: Dict[str, List[Any]], t: str) -> List[Any]:
    return [v for v in inputs.get(t, []) if v is not None]


def _cfg(node: dict, key: str, default=None):
    return (node.get("config") or {}).get(key, default)


def _sample_docs(node, ctx, n=3) -> List[dict]:
    fx = ctx.fx(node["id"])
    if isinstance(fx, dict) and isinstance(fx.get("documents"), list):
        return fx["documents"]
    label = node.get("label") or node["type"]
    return [
        {"text": f"Fragmento de muestra {i+1} de '{label}'.",
         "metadata": {"section": f"§{i+1}"},
         "source": f"{node['id']}#sec{i+1}"}
        for i in range(n)
    ]


def _chunks_from(value) -> List[dict]:
    if isinstance(value, dict) and value.get("kind") == "retriever":
        return value.get("chunks", [])
    if isinstance(value, list):
        return value
    return []


# ---------- io ----------
def passthrough(node, inputs, ctx):
    # default / passthrough_message
    v = _first(inputs, "Any") or _first(inputs, "Message") or _first(inputs, "Decision")
    return {"Any": v, "Message": v if isinstance(v, str) else ctx.seed_message}


def passthrough_message(node, inputs, ctx):
    return {"Message": ctx.seed_message}


def stt_transcript(node, inputs, ctx):
    fx = ctx.fx(node["id"]) or {}
    return {"Message": fx.get("transcript", ctx.seed_message)}


def emit_events(node, inputs, ctx):
    fx = ctx.fx(node["id"]) or {}
    events = fx.get("events") or ctx.seed_events or [
        {"id": f"evt-{i+1}", "type": _cfg(node, "topic", "event"), "payload": {"n": i + 1}}
        for i in range(3)
    ]
    return {"Event": events}


def emit_documents(node, inputs, ctx):
    return {"Documents": _sample_docs(node, ctx)}


def load_documents(node, inputs, ctx):
    return {"Documents": _sample_docs(node, ctx)}


def collect_output(node, inputs, ctx):
    v = _first(inputs, "Any") or _first(inputs, "Message") or _first(inputs, "Decision")
    return {"Any": v, "Message": v if isinstance(v, str) else None, "Decision": v if isinstance(v, dict) else None}


def record_notify(node, inputs, ctx):
    payload = _first(inputs, "Any") or _first(inputs, "Message") or _first(inputs, "Decision")
    note = {"channels": _cfg(node, "channels", ["email"]), "payload": payload}
    ctx.notifications.append(note)
    return {"Any": note}


# ---------- ingest ----------
def chunk(node, inputs, ctx):
    docs = _first(inputs, "Documents") or []
    out = []
    for d in docs:
        out.append({"text": d.get("text", ""), "metadata": d.get("metadata", {}), "source": d.get("source", "")})
    return {"Documents": out or _sample_docs(node, ctx)}


def tag_metadata(node, inputs, ctx):
    docs = _first(inputs, "Documents") or _sample_docs(node, ctx)
    fields = _cfg(node, "fields", []) or []
    for d in docs:
        for f in fields:
            d.setdefault("metadata", {}).setdefault(f, "muestra")
    return {"Documents": docs}


# ---------- store / retrieval ----------
def build_store(node, inputs, ctx):
    docs = _all(inputs, "Documents")
    flat: List[dict] = []
    for d in docs:
        if isinstance(d, list):
            flat.extend(d)
    # también admite retrievers de entrada (multi-index)
    for r in _all(inputs, "Retriever"):
        flat.extend(_chunks_from(r))
    if not flat:
        flat = _sample_docs(node, ctx)
    return {"Retriever": {"kind": "retriever", "chunks": flat, "node": node["id"]}}


def retrieve(node, inputs, ctx):
    r = _first(inputs, "Retriever")
    chunks = _chunks_from(r) or _sample_docs(node, ctx)
    topk = int(_cfg(node, "topK", 4) or 4)
    return {"Chunks": chunks[:topk]}


def route_retrieve(node, inputs, ctx):
    retrievers = _all(inputs, "Retriever")
    chunks = _chunks_from(retrievers[0]) if retrievers else _sample_docs(node, ctx)
    topk = int(_cfg(node, "topK", 4) or 4)
    return {"Chunks": chunks[:topk]}


def rerank(node, inputs, ctx):
    chunks = _first(inputs, "Chunks") or []
    topn = int(_cfg(node, "topN", 3) or 3)
    return {"Chunks": chunks[:topn]}


# ---------- model / query ----------
def embed(node, inputs, ctx):
    return {"Embeddings": {"kind": "embeddings", "name": _cfg(node, "model", "embed")}}


def llm(node, inputs, ctx):
    return {"Model": {"kind": "model", "name": _cfg(node, "model", "anthropic:claude-opus-4-8")}}


def vision(node, inputs, ctx):
    return {"Model": {"kind": "model", "name": _cfg(node, "model", "anthropic:claude-opus-4-8"), "vision": True}}


def intent(node, inputs, ctx):
    msg = _first(inputs, "Message") or ctx.seed_message
    labels = _cfg(node, "labels", []) or ["accionable"]
    return {"Query": msg, "Decision": {"intent": labels[0], "actionable": True}}


def rewrite(node, inputs, ctx):
    msg = _first(inputs, "Message") or ctx.seed_message
    return {"Query": msg.strip()}


# ---------- logic ----------
def _cite(chunks: List[dict]) -> str:
    if chunks:
        src = chunks[0].get("source") or chunks[0].get("metadata", {}).get("section") or "fuente"
        return f"[fuente: {src}]"
    return "[fuente: n/d]"


def prompt(node, inputs, ctx):
    msg = _first(inputs, "Message") or ctx.seed_message
    chunks = _first(inputs, "Chunks") or []
    cite = _cite(chunks)
    body = chunks[0]["text"] if chunks else "Sin contexto recuperado."
    text = f"Respuesta a: «{msg}». Según la documentación: {body} {cite}"
    return {"Message": text}


def structured(node, inputs, ctx):
    fx = ctx.fx(node["id"]) or {}
    if isinstance(fx.get("decision"), dict):
        decision = dict(fx["decision"])
    else:
        decision = _decision_from_schema(_cfg(node, "schema", {}) or {})
    chunks = _first(inputs, "Chunks") or []
    if _cfg(node, "requireCitations", False):
        cits = [c.get("source", "fuente") for c in chunks[:2]] or ["fuente-muestra"]
        decision["citations"] = cits
        for c in cits:
            ctx.citations.append({"node": node["id"], "source": c})
    return {"Decision": decision}


def _decision_from_schema(schema: dict) -> dict:
    props = (schema or {}).get("properties", {})
    out: Dict[str, Any] = {}
    for k, spec in props.items():
        t = (spec or {}).get("type")
        if "default" in (spec or {}):
            out[k] = spec["default"]
        elif t == "number" or t == "integer":
            out[k] = 0
        elif t == "boolean":
            out[k] = True
        elif t == "array":
            out[k] = []
        else:
            out[k] = "muestra"
    if not out:
        out = {"resultado": "muestra"}
    return out


def rules(node, inputs, ctx):
    fx = ctx.fx(node["id"]) or {}
    if isinstance(fx.get("decision"), dict):
        return {"Decision": dict(fx["decision"])}
    rules_cfg = _cfg(node, "rules", []) or []
    decision = {"matched": bool(rules_cfg), "action": (rules_cfg[0].get("then") if rules_cfg and isinstance(rules_cfg[0], dict) else _cfg(node, "else", "default"))}
    return {"Decision": decision}


def router(node, inputs, ctx):
    d = _first(inputs, "Decision") or _first(inputs, "Any") or {}
    return {"Any": d}


def citations(node, inputs, ctx):
    msg = _first(inputs, "Message") or ""
    chunks = _first(inputs, "Chunks") or []
    mode = _cfg(node, "mode", "enforce")
    has_cite = "[fuente:" in (msg or "")
    if mode == "enforce" and not has_cite:
        msg = f"{msg} {_cite(chunks)}"
        has_cite = True
    ctx.citations.append({"node": node["id"], "enforced": mode == "enforce", "present": has_cite})
    return {"Message": msg}


# ---------- tools ----------
def tool_service(node, inputs, ctx):
    fx = ctx.fx(node["id"]) or {}
    name = _cfg(node, "name") or node.get("label") or node["type"]
    base = _cfg(node, "baseUrl")
    op = _cfg(node, "operation", "invoke")
    integ = getattr(ctx, "integration", {}) or {}
    # Modo integración: el tool se DIFIERE — el agente decide cuándo llamarlo
    # (así respeta los guardrails, p.ej. no cobra antes de confirmar). Si no, usa fixtures.
    if base and integ.get("http"):
        return {"Tool": {"kind": "tool", "name": name, "result": None, "wrappers": {},
                          "_base": base, "_op": op, "_deferred": True}}
    return {"Tool": {"kind": "tool", "name": name, "result": fx.get("result", {"ok": True}), "wrappers": {}}}


def tool_retriever(node, inputs, ctx):
    r = _first(inputs, "Retriever")
    chunks = _chunks_from(r)
    if not chunks:
        chunks = _first(inputs, "Chunks") or _sample_docs(node, ctx)
    name = _cfg(node, "name", "search")
    return {"Tool": {"kind": "tool", "name": name, "result": chunks, "wrappers": {}, "retriever": True}}


# ---------- guardrails (envuelven un Tool) ----------
def _wrap_tool(inputs, key, value):
    tool = _first(inputs, "Tool")
    if not isinstance(tool, dict):
        tool = {"kind": "tool", "name": "tool", "result": {}, "wrappers": {}}
    tool = {**tool, "wrappers": {**tool.get("wrappers", {}), key: value}}
    return tool


def guardrail_idempotency(node, inputs, ctx):
    return {"Tool": _wrap_tool(inputs, "idempotency", _cfg(node, "keyFields", []) or True)}


def guardrail_confirm(node, inputs, ctx):
    return {"Tool": _wrap_tool(inputs, "confirm", _cfg(node, "threshold", True))}


def guardrail_resilience(node, inputs, ctx):
    return {"Tool": _wrap_tool(inputs, "resilience", {"retries": _cfg(node, "retries", 2)})}


def guardrail_pretool(node, inputs, ctx):
    return {"Tool": _wrap_tool(inputs, "pretool", _cfg(node, "checks", []) or True)}


# ---------- agents ----------
_CONFIRM_WORDS = ("sí", "si,", "si ", "confirmo", "confirmar", "de acuerdo", "procede", "acepto", "adelante")


def _short_result(res):
    """Resumen compacto del resultado de un tool para el rastro de auditoría."""
    if isinstance(res, list):
        return {"items": len(res)}
    if isinstance(res, dict):
        return {k: res[k] for k in list(res)[:6]}
    return res


def agent_react(node, inputs, ctx):
    tools = [t for t in _all(inputs, "Tool") if isinstance(t, dict)]
    retrievers = _all(inputs, "Retriever")
    msg = _first(inputs, "Message") or ctx.seed_message
    confirmed = any(w in (msg or "").lower() for w in _CONFIRM_WORDS)
    integ = getattr(ctx, "integration", {}) or {}
    http = integ.get("http")

    # Procesa primero las tools sin confirmación; las que exigen confirm, al final.
    ordered = sorted(tools, key=lambda t: 1 if "confirm" in (t.get("wrappers", {}) or {}) else 0)
    tool_calls = []
    needs_confirm = False
    amount = None
    for t in ordered:
        w = t.get("wrappers", {}) or {}
        call = {"name": t.get("name"), "wrappers": list(w.keys())}
        if "confirm" in w and not confirmed:
            # Guardrail: NO se ejecuta hasta confirmación explícita del usuario.
            call.update(status="pendiente-confirmación", executions=0, needs_confirm=True, result=None)
            needs_confirm = True
            tool_calls.append(call)
            continue
        # Ejecuta: HTTP real si está diferido (integración), si no usa el result del fixture.
        if t.get("_deferred") and http and t.get("_base"):
            try:
                t["result"] = http(t["_base"], t.get("_op", "invoke"), {"message": msg})
            except Exception as exc:
                t["result"] = {"error": f"{type(exc).__name__}: {exc}"}
        res = t.get("result")
        if isinstance(res, dict) and amount is None:
            amount = res.get("amount", res.get("total"))
        call.update(status="ejecutado", executions=1, result=_short_result(res))
        tool_calls.append(call)

    cite = ""
    if retrievers:
        cite = " " + _cite(_chunks_from(retrievers[0]))
    elif any(t.get("retriever") for t in tools):
        rt = next(t for t in tools if t.get("retriever"))
        cite = " " + _cite(rt.get("result") or [])

    executed = [c["name"] for c in tool_calls if c.get("status") == "ejecutado"]
    response = f"He procesado: «{msg}». Consulté: {', '.join(executed) or 'ninguna herramienta'}.{cite}"
    if needs_confirm:
        monto = f" El costo total es USD {amount}." if amount else ""
        response += f"{monto} ¿Confirmas la operación?"
    elif confirmed:
        response += " Operación confirmada y ejecutada."
    ctx.trace["agent"] = {"tool_calls": tool_calls, "needs_confirm": needs_confirm,
                          "confirmed": confirmed, "amount": amount, "response": response}
    return {"Message": response}


def agent_fanout(node, inputs, ctx):
    events = _first(inputs, "Event") or ctx.seed_events or []
    if isinstance(events, dict):
        events = [events]
    tools = [t for t in _all(inputs, "Tool") if isinstance(t, dict)]
    results = []
    for ev in events:
        results.append({"event": ev.get("id", "evt"), "tools": [t.get("name") for t in tools], "status": "rebooked"})
    ctx.trace["fanout"] = {"processed": len(results), "concurrency": _cfg(node, "concurrency", 16)}
    return {"Any": results}


# ---------- hitl / observability ----------
def hitl_escalate(node, inputs, ctx):
    val = _first(inputs, "Any") or _first(inputs, "Message") or _first(inputs, "Decision")
    when = (_cfg(node, "when", "") or "").lower()
    text = str(val).lower()
    triggers = ["warning", "caution", "crítico", "critico", "critical"]
    escalate = any(k in text for k in triggers) or any(k in when for k in triggers)
    if escalate:
        ctx.escalations.append({"node": node["id"], "assignee": _cfg(node, "assignee", "humano"), "reason": when or "condición crítica"})
    return {"Any": val, "Message": val if isinstance(val, str) else None}


def audit(node, inputs, ctx):
    val = _first(inputs, "Any") or _first(inputs, "Message") or _first(inputs, "Decision")
    event = {"node": node["id"], "sink": _cfg(node, "sink", "log"), "payload": val}
    ctx.audit.append(event)
    integ = getattr(ctx, "integration", {}) or {}
    if integ.get("bus"):  # publica a Kafka/bus real (e2e)
        try:
            integ["bus"](event)
        except Exception:
            pass
    return {"Any": val, "Message": val if isinstance(val, str) else None}


def feedback(node, inputs, ctx):
    val = _first(inputs, "Any") or _first(inputs, "Message")
    ctx.feedback.append({"node": node["id"], "signals": _cfg(node, "signals", ["thumbs"])})
    return {"Any": val}


def metrics(node, inputs, ctx):
    val = _first(inputs, "Any") or _first(inputs, "Message")
    ctx.metrics.append({"node": node["id"], "exporter": _cfg(node, "exporter", "otlp")})
    return {"Any": val}


BEHAVIORS = {
    "passthrough_message": passthrough_message,
    "stt_transcript": stt_transcript,
    "emit_events": emit_events,
    "emit_documents": emit_documents,
    "load_documents": load_documents,
    "collect_output": collect_output,
    "record_notify": record_notify,
    "chunk": chunk,
    "tag_metadata": tag_metadata,
    "build_store": build_store,
    "retrieve": retrieve,
    "route_retrieve": route_retrieve,
    "rerank": rerank,
    "embed": embed,
    "llm": llm,
    "vision": vision,
    "intent": intent,
    "rewrite": rewrite,
    "prompt": prompt,
    "structured": structured,
    "rules": rules,
    "router": router,
    "citations": citations,
    "tool_service": tool_service,
    "tool_retriever": tool_retriever,
    "guardrail_idempotency": guardrail_idempotency,
    "guardrail_confirm": guardrail_confirm,
    "guardrail_resilience": guardrail_resilience,
    "guardrail_pretool": guardrail_pretool,
    "agent_react": agent_react,
    "agent_fanout": agent_fanout,
    "hitl_escalate": hitl_escalate,
    "audit": audit,
    "feedback": feedback,
    "metrics": metrics,
}
