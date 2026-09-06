"""Servidor HTTP del chat — FastAPI con UI, /chat y streaming SSE."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from app import settings
from app.engine import run_turn

_STATIC = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(
    title="{{FLOW_NAME}}",
    version="0.1.0",
    description="Chat generado por RAGorbit · flow {{FLOW_ID}}",
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    session_id: str = Field(default="web-sess-1", min_length=1)


@app.get("/health")
def health():
    return {
        "ok": True,
        "flow_id": settings.FLOW_ID,
        "mock": settings.MOCK,
        "integration": settings.INTEGRATION,
        "services_base": settings.SERVICES_BASE,
    }


@app.get("/")
def index():
    ui = _STATIC / "index.html"
    if ui.is_file():
        return FileResponse(ui)
    return {"message": "POST /chat con {message, session_id}"}


@app.post("/chat")
def chat(body: ChatRequest):
    try:
        return run_turn(body.message, session_id=body.session_id)
    except Exception as exc:
        raise HTTPException(503, f"Error ejecutando el flujo: {exc}") from exc


@app.post("/chat/stream")
def chat_stream(body: ChatRequest):
    """Streaming SSE: trocea la respuesta en líneas (útil para UI tipo copilot)."""
    result = run_turn(body.message, session_id=body.session_id)
    text = result.get("response") or ""

    def gen():
        for line in text.split("\n"):
            yield f"data: {line}\n\n"
            time.sleep(0.02)
        if result.get("needs_confirm"):
            yield "data: [needs_confirm]\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


def main():
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=settings.PORT, log_level="info")


if __name__ == "__main__":
    main()
