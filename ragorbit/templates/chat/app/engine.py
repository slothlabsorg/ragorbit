"""Motor unificado: LLM real, mock en proceso, integración HTTP o LangGraph."""
from __future__ import annotations

from typing import Any, Dict, List

from app import settings
from app.bus import make_bus
from app.mockrun import run as mock_run

_BUSES: Dict[str, Any] = {}


def _bus(session_id: str):
    if session_id not in _BUSES:
        _BUSES[session_id] = make_bus()
    return _BUSES[session_id]


def run_turn(message: str, session_id: str = "web-sess-1") -> Dict[str, Any]:
    calls: List[dict] = []

    if settings.llm_enabled():
        from app.llm_agent import run_turn as llm_run

        res = llm_run(message, session_id=session_id, record=lambda rec: calls.append(rec))
        mode = "llm+integration" if settings.INTEGRATION else "llm"
    elif settings.INTEGRATION or (settings.SERVICES_BASE and not settings.MOCK):
        from app.integration import run as integration_run

        res = integration_run(
            message,
            bus=_bus(session_id),
            session_id=session_id,
            record=lambda rec: calls.append(rec),
        )
        mode = "integration"
    elif settings.MOCK:
        res = mock_run(message)
        mode = "mock"
    else:
        from app.graph import build_graph

        text = build_graph().invoke({"message": message, "session_id": session_id})
        if isinstance(text, dict):
            res = {"response": text.get("response") or str(text), "trace": {}, "citations": []}
        else:
            res = {"response": str(text), "trace": {}, "citations": []}
        mode = "real"

    agent = res.get("trace", {}).get("agent", {})
    return {
        "response": res.get("response"),
        "needs_confirm": agent.get("needs_confirm"),
        "confirmed": agent.get("confirmed"),
        "tool_calls": agent.get("tool_calls", []),
        "citations": res.get("citations", []),
        "calls": calls,
        "mode": mode,
    }
