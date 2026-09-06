"""Configuración del artefacto generado. Lee variables de entorno."""
import os

MOCK = os.environ.get("MOCK", "true").lower() in ("1", "true", "yes")
INTEGRATION = os.environ.get("INTEGRATION", "false").lower() in ("1", "true", "yes")
USE_LLM = os.environ.get("USE_LLM", "false").lower() in ("1", "true", "yes")
SERVICES_BASE = os.environ.get("SERVICES_BASE", "http://127.0.0.1:8900").rstrip("/")
KAFKA_BROKER = os.environ.get("KAFKA_BROKER", "")
FLOW_ID = os.environ.get("FLOW_ID", "{{FLOW_ID}}")
LLM_MODEL = os.environ.get("LLM_MODEL", "claude-sonnet-4-6")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
# Vacío = API oficial de Anthropic. Ponlo solo si pasas por un gateway/proxy
# propio (LLM proxy corporativo, LiteLLM, Bedrock-compatible…).
ANTHROPIC_BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
LLM_MAX_STEPS = int(os.environ.get("LLM_MAX_STEPS", "6"))
PORT = int(os.environ.get("PORT", "8000"))


def llm_enabled() -> bool:
    return bool(ANTHROPIC_API_KEY) and (USE_LLM or not MOCK)
