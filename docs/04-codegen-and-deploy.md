# 04 · Codegen y deploy

> Qué produce RAGorbit a partir de un [Flow IR](./01-concepts.md#2-flow-ir--la-especificación-portable), cómo correrlo con mocks y cómo desplegarlo. El artefacto es **código Python normal**: corre sin RAGorbit.

## Cómo se genera

1. El generador valida el Flow IR (reglas de [01 §2.2](./01-concepts.md#22-reglas-de-validez-un-flow-ir-es-válido-si)) y comprueba los [contratos](./01-concepts.md) — un flujo que no funcionaría se rechaza antes de generar nada.
2. **Compila** el flujo: resuelve el tipo de puerto de cada arista, para que el dataflow se enrute por tipo.
3. Elige el **esqueleto** según el [deployment target](./01-concepts.md#5-deployment-targets-cómo-se-despliega) (derivado del nodo de entrada).
4. Por cada nodo busca su **emisor** (el campo `emitter` del manifest, ver [05 · Extender](./05-extending.md)) y emite su implementación real; el `mock.behavior` del mismo manifest es el que corre en modo mock.
5. Empaqueta todo en un proyecto con `mocks/`, `tests/`, `Dockerfile` y `docker-compose.yml`.

## Estructura del artefacto generado

Los targets `batch` y `event-worker` generan un grafo explícito:

```
mi-job/
  app/
    nodes.py          # la implementación REAL de cada nodo: una función por nodo
    graph.py          # el StateGraph de LangGraph que cablea esas funciones
    mockrun.py        # runner en modo mock (stdlib)
    main.py           # entrada según target (job batch o worker de eventos)
    settings.py       # lee env; MOCK=true conmuta a mocks
  runtime/            # ejecutor mock determinista (copiado del engine, sin deps)
  mocks/
    fixtures.json     # datos de muestra por nodo
  tests/
    test_flow.py      # corre el flujo end-to-end contra los mocks
  .env.template       # SOLO nombres de secretos
  pyproject.toml      # extra [real] con las deps que ESTE flujo necesita
  Dockerfile
  docker-compose.yml
  README.md           # pasos exactos para correr
```

`chat-service` no lleva `graph.py`/`nodes.py`: su camino real es un agente con
tool-calling y guardrails (`app/engine.py` + `app/llm_agent.py`), más el servidor
FastAPI, la UI en `static/` y los mocks de servicios en `mocks/services/`.

### `nodes.py` y `graph.py`, y por qué están separados

`nodes.py` tiene **una función por nodo**, con la misma firma que su equivalente
mock en `runtime/behaviors.py`: recibe `inputs` (las entradas agrupadas por tipo
de puerto) y devuelve `{tipo_de_puerto: valor}`. Puedes abrir el mock y el real
en paralelo y leer la misma lógica dos veces.

`graph.py` solo cablea. El estado lleva `outputs[node_id][port_type]` y las
entradas de cada nodo se reúnen por arista y por tipo de puerto — exactamente lo
que hace el ejecutor mock. Por eso un flujo se comporta igual en los dos modos, y
dos nodos pueden alimentar el mismo puerto sin pisarse (con un reducer, porque
LangGraph corre las ramas independientes en paralelo).

La separación es lo que hace editable el artefacto: cambias la lógica de un nodo
sin tocar el cableado, y cambias el cableado sin releer 300 líneas de lógica.

## El interruptor `MOCK`

Cada `tool.service`/loader genera **dos** implementaciones con la misma firma. `settings.py` lee `MOCK`:

- `MOCK=true` (default del artefacto): usa `mocks/services/*` con `mocks/fixtures/*`. **No requiere secretos de servicios externos** — solo la API key del LLM (y en los tests, ni eso si el LLM también se simula).
- `MOCK=false`: usa las implementaciones reales y exige los secretos del `.env`.

Esto es lo que hace que el artefacto **funcione el día 1** y que los tests sean deterministas.

## Esqueletos por target

| Target | Entrada | Esqueleto | Cómo corre |
|--------|---------|-----------|------------|
| `chat-service` | `io.input` | FastAPI con endpoint `/chat` (SSE/WebSocket streaming) | `docker compose up` → `POST localhost:8000/chat` |
| `event-worker` | `io.event-source` | Consumer Kafka stateless con fan-out (`agent.fanout`) | `docker compose up` (incluye Kafka + un productor de eventos de muestra) |
| `temporal` | `io.trigger` | Workflow + activities (`temporalio`) | `docker compose up` (incluye Temporal) → script que dispara el workflow |
| `batch` | `io.batch` | Job CLI/cron | `docker compose run job --input ./fixtures` |

## El modelo (Claude por defecto)

`model.llm` genera inicialización vía interfaz estándar:

```python
from langchain.chat_models import init_chat_model
llm = init_chat_model("anthropic:claude-opus-4-8", temperature=0.2)
```

Cambiar de proveedor es cambiar el string del modelo (`openai:…`, etc.) — sin tocar el resto del grafo. Para IDs/precios exactos, consulta la skill `claude-api`.

## Probar el artefacto (sin tocar nada real)

```bash
cd mi-bot
docker compose up          # arranca en modo mock
# chat-service:
curl -N localhost:8000/chat -d '{"message":"hola, ¿qué cubre mi plan?"}'
# tests:
docker compose run tests   # pytest end-to-end contra mocks
```

Cada ejemplo en `examples/` documenta su comando exacto y la salida esperada en su sección **"Probarlo con mocks"**.

## Pasar a producción

1. `MOCK=false` en el entorno.
2. Completa el `.env` con los secretos reales (los nombres están en `.env.template`).
3. Construye y despliega el contenedor donde quieras (k8s, ECS, Cloud Run…). No hay dependencia de RAGorbit.

➡️ Siguiente: [05 · Extender el catálogo](./05-extending.md).
