"""Agente ReAct con Claude real (API Anthropic / LLM-Proxy). Solo stdlib."""
from __future__ import annotations

import json
import os
import re
import ssl
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from app import settings
from app.integration import SERVICE_MAP, patch_flow_with_services, make_http

_ROOT = Path(__file__).resolve().parent.parent
_FLOW_PATH = _ROOT / "flow.json"

_SESSIONS: Dict[str, Dict[str, Any]] = {}
_CONFIRM = re.compile(r"\b(sí|si|confirmo|confirmar|de acuerdo|adelante|acepto|procede)\b", re.I)


def _model_id() -> str:
    m = settings.LLM_MODEL
    if m.startswith("anthropic:"):
        m = m.split(":", 1)[1]
    # alias del diagrama → modelo en proxy
    aliases = {
        "claude-opus-4-8": "claude-opus-4-6",
        "claude-sonnet-4-6": "claude-sonnet-4-6",
    }
    return aliases.get(m, m)


def _system_prompt() -> str:
    flow = json.loads(_FLOW_PATH.read_text(encoding="utf-8"))
    for n in flow.get("nodes", []):
        if n["type"] == "agent.react":
            base = n.get("config", {}).get("system", "")
            break
    else:
        base = "Eres un asistente de aerolínea."
    extra = (
        "\n\nReglas adicionales:\n"
        "- Si el usuario saluda o pregunta qué puedes hacer, responde en texto SIN usar herramientas.\n"
        "- Usa herramientas solo cuando el usuario quiera cambiar un vuelo o necesite datos de reserva/precio/pago.\n"
        "- NUNCA llames PaymentService hasta que el usuario confirme explícitamente el cobro.\n"
        "- Responde en español, markdown breve."
    )
    return base + extra


def _anthropic_tools(flow: dict) -> List[dict]:
    tools = []
    for n in flow.get("nodes", []):
        if n["type"] == "tool.service":
            cfg = n.get("config", {})
            name = cfg.get("name") or n.get("label") or n["id"]
            schema = cfg.get("inputSchema") or {"type": "object", "properties": {"message": {"type": "string"}}}
            tools.append({
                "name": name.replace(" ", "_"),
                "description": f"Servicio {name}. Operation: {cfg.get('operation', 'invoke')}",
                "input_schema": schema,
            })
        elif n["type"] == "tool.retriever":
            cfg = n.get("config", {})
            tools.append({
                "name": cfg.get("name", "policy_rag"),
                "description": cfg.get("description", "Consulta reglas tarifarias"),
                "input_schema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            })
    return tools


def _tool_http_map(flow: dict) -> Dict[str, tuple]:
    """nombre_tool -> (baseUrl, operation)"""
    out: Dict[str, tuple] = {}
    for n in flow.get("nodes", []):
        if n["type"] == "tool.service":
            cfg = n.get("config", {})
            name = (cfg.get("name") or n.get("label") or n["id"]).replace(" ", "_")
            base = cfg.get("baseUrl", "")
            op = cfg.get("operation", "invoke")
            for keys, svc, default_op in SERVICE_MAP:
                if any(k in name.lower() for k in keys):
                    op = default_op
                    break
            out[name] = (base, op)
        elif n["type"] == "tool.retriever":
            cfg = n.get("config", {})
            name = cfg.get("name", "policy_rag")
            out[name] = (f"{settings.SERVICES_BASE}/policy-rag", "search")
    return out


def _ssl_context():
    if os.environ.get("SSL_VERIFY", "true").lower() in ("0", "false", "no"):
        return ssl._create_unverified_context()
    return None


def _call_claude(messages: List[dict], tools: List[dict]) -> dict:
    url = f"{settings.ANTHROPIC_BASE_URL.rstrip('/')}/v1/messages"
    body = {
        "model": _model_id(),
        "max_tokens": 1024,
        "system": _system_prompt(),
        "messages": messages,
        "tools": tools,
    }
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "x-api-key": settings.ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=90, context=_ssl_context()) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        err = e.read().decode()
        raise RuntimeError(f"LLM proxy {e.code}: {err[:400]}") from e


def _execute_tool(
    name: str,
    tool_input: dict,
    http_fn,
    tool_map: Dict[str, tuple],
    user_msg: str,
    session: dict,
) -> Any:
    if "ayment" in name or "Payment" in name:
        if not _CONFIRM.search(user_msg) and not session.get("payment_confirmed"):
            session["pending_payment"] = tool_input
            return {
                "blocked": True,
                "reason": "confirm_required",
                "message": "Se requiere confirmación explícita del pasajero antes de cobrar.",
            }
        session["payment_confirmed"] = True

    mapping = tool_map.get(name)
    if not mapping:
        for k, v in tool_map.items():
            if k.lower() in name.lower() or name.lower() in k.lower():
                mapping = v
                break
    if not mapping:
        return {"error": f"tool desconocida: {name}"}
    base, op = mapping
    payload = dict(tool_input) if tool_input else {}
    if "message" not in payload and "query" not in payload:
        payload.setdefault("message", user_msg)
    return http_fn(base, op, payload)


def run_turn(message: str, session_id: str = "web-sess-1", record=None) -> Dict[str, Any]:
    if session_id not in _SESSIONS:
        _SESSIONS[session_id] = {"messages": [], "payment_confirmed": False}
    session = _SESSIONS[session_id]
    if _CONFIRM.search(message):
        session["payment_confirmed"] = True

    flow = json.loads(_FLOW_PATH.read_text(encoding="utf-8"))
    patch_flow_with_services(flow, settings.SERVICES_BASE)
    tools = _anthropic_tools(flow)
    tool_map = _tool_http_map(flow)
    idem_key = f"{settings.FLOW_ID}:{session_id}"
    http_fn = make_http(idem_key=idem_key, record=record)

    messages = list(session["messages"])
    messages.append({"role": "user", "content": message})

    tool_calls_trace: List[dict] = []
    needs_confirm = False
    final_text = ""

    for _ in range(settings.LLM_MAX_STEPS):
        resp = _call_claude(messages, tools)
        blocks = resp.get("content", [])
        text_parts = [b["text"] for b in blocks if b.get("type") == "text"]
        tool_uses = [b for b in blocks if b.get("type") == "tool_use"]

        if text_parts:
            final_text = "\n".join(text_parts)

        messages.append({"role": "assistant", "content": blocks})

        if resp.get("stop_reason") != "tool_use" or not tool_uses:
            break

        results = []
        for tu in tool_uses:
            name = tu.get("name", "")
            inp = tu.get("input") or {}
            raw = _execute_tool(name, inp, http_fn, tool_map, message, session)
            if isinstance(raw, dict) and raw.get("blocked"):
                needs_confirm = True
                result = raw
            else:
                result = raw
            tool_calls_trace.append({
                "name": name,
                "status": "pendiente-confirmación" if needs_confirm and "ayment" in name else "ejecutado",
                "result": result,
            })
            results.append({
                "type": "tool_result",
                "tool_use_id": tu["id"],
                "content": json.dumps(result, ensure_ascii=False),
            })
        messages.append({"role": "user", "content": results})

    session["messages"] = messages[-20:]  # ventana

    if needs_confirm and "confirm" not in final_text.lower():
        final_text += "\n\n¿Confirmas la operación y el cobro?"

    return {
        "response": final_text or "Sin respuesta del modelo.",
        "trace": {
            "agent": {
                "tool_calls": tool_calls_trace,
                "needs_confirm": needs_confirm,
                "confirmed": session.get("payment_confirmed", False),
            }
        },
        "citations": [],
        "_mode": "llm",
    }
