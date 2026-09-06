# Ejemplo 01 · Agente de cambio de vuelo

---

## 1. Problema / industria

**Industria:** Aerolíneas — contact center y self-service web/app.

Un pasajero quiere cambiar su vuelo (fecha, destino o ambos) en lenguaje natural. El proceso implica consultar el PNR, verificar si la tarifa permite cambios, buscar vuelos alternativos, calcular el diferencial de precio más la penalidad tarifaria y, si el pasajero confirma, ejecutar el cobro y emitir el nuevo itinerario.

**A quién sirve:**
- Pasajeros con reservas activas que desean autogestionar cambios sin llamar al contact center.
- Operadores de aerolínea que necesitan reducir la carga de agentes humanos para casos estándar (cambios domésticos, penalidades conocidas).
- Equipos de ingeniería que quieren un ejemplo de agente transaccional con guardrails financieros y audit trail regulatorio.

---

## 2. Resultado esperado

El chat produce, en streaming markdown:

1. Un resumen del itinerario actual (vuelo, ruta, fecha, fare class).
2. La penalidad de cambio según las reglas de tarifa (consultadas en PolicyRAG).
3. Las opciones de vuelo disponibles en la nueva fecha.
4. El costo total: penalidad + diferencia tarifaria.
5. Una solicitud de confirmación explícita antes de cobrar.
6. Tras confirmación: confirmación de pago exitoso e itinerario actualizado con número de reserva.

Todos los tool calls quedan persistidos en Kafka (`flight-change-audit`) para trazabilidad regulatoria.

---

## 3. Arquitectura

Diagrama ASCII del flujo de nodos con sus puertos:

```
[INGESTA DE POLÍTICAS — pipeline offline]

  loader.pdf                 ingest.chunker          ingest.metadata
  "Fare Rules PDF"           "by-clause"             "fare_class/route_type"
  Documents ──────────────▶  Documents ─────────────▶ Documents ─────────────▶
                                                                               │
                                                                               ▼
  model.embedding                                          store.pgvector "fare_rules"
  "Embeddings" ────────────────────────────────────────▶  (Documents + Embeddings)
                                                           Retriever ──────────────▶
                                                                                    │
                                                              tool.retriever         │
                                                              "PolicyRAG Tool" ◀─────┘
                                                              Tool ──────────────────▶
                                                                                      │
[FLUJO CONVERSACIONAL — runtime]                                                      │
                                                                                      │
  io.input                   agent.react                                             │
  "Chat Input"               "Agente ReAct"  ◀────── Model ── model.llm             │
  Message ─────────────────▶ Message (loop) ◀─────────────────────────────────────── ┘ (Tool)
                             │
                             │ ◀── Tool ── tool.service "ReservationService"
                             │ ◀── Tool ── tool.service "InventoryService"
                             │ ◀── Tool ── tool.service "PricingService"
                             │
                             │ ◀── Tool ── guardrail.resilience ◀── guardrail.confirm ◀── guardrail.idempotency ◀── tool.service "PaymentService"
                             │
                             │ Message
                             ▼
                    observability.audit          io.output
                    "Kafka audit trail"          "Chat Output"
                    Any (passthrough) ─────────▶ Any
```

Relaciones de puertos clave:

```
io.input          Message  ──▶  agent.react       Message
model.llm         Model    ──▶  agent.react       Model
tool.service      Tool     ──▶  agent.react       Tool     (×4: Reservation, Inventory, Pricing + cadena Payment)
tool.retriever    Tool     ──▶  agent.react       Tool
store.pgvector    Retriever──▶  tool.retriever    Retriever
agent.react       Message  ──▶  observability.audit  Any
observability.audit Any    ──▶  io.output         Any
agent.react       Message  ──▶  agent.react       Message  (loop: true — ciclo ReAct)
```

---

## 4. Construirlo paso a paso

Sigue este orden en el lienzo; cada paso corresponde a un nodo o conexión numerada:

1. Arrastra **`io.input`** al lienzo. Configura `channel: chat`, `auth: booking-token`, `streaming: true`. Es el punto de entrada — RAGorbit ya detectará `deploymentTarget: chat-service`.
2. Arrastra **`model.llm`** arriba del lienzo. Deja el modelo en `anthropic:claude-opus-4-8`. Conecta su puerto `Model` al puerto `Model` del agente (aún no existe; lo creas en el paso 6).
3. Arrastra **`loader.pdf`** en la zona inferior. Configura `bucket` apuntando al S3 con los PDFs de políticas IATA.
4. Conecta `loader.pdf:Documents` → **`ingest.chunker`** (`strategy: by-clause`, `chunkSize: 800`). Puerto: `Documents → Documents`.
5. Conecta `ingest.chunker:Documents` → **`ingest.metadata`** (`fields: [fare_class, route_type, effective_date]`). Puerto: `Documents → Documents`.
6. Arrastra **`model.embedding`** (`model: text-embedding-3-large`). Lo necesitará el store.
7. Conecta `ingest.metadata:Documents` → **`store.pgvector`** (`index: fare_rules`). Conecta también `model.embedding:Embeddings` → `store.pgvector:Embeddings`.
8. Conecta `store.pgvector:Retriever` → **`tool.retriever`** "PolicyRAG Tool". Escribe la `description` explicando que filtra por `fare_class` y `route_type`. Puerto: `Retriever → Retriever`.
9. Arrastra **`tool.service`** "ReservationService". Configura `baseUrl`, `operation: getItinerary`, `inputSchema` con campo `pnr`.
10. Arrastra **`tool.service`** "InventoryService". Configura `operation: searchFlights`, esquema con `origin/destination/date`.
11. Arrastra **`tool.service`** "PricingService". Configura `operation: calculateDelta`, esquema con `pnr/newFlightId`.
12. Arrastra **`tool.service`** "PaymentService". Configura `operation: chargeChangeFee`, esquema con `pnr/session_id/amount`.
13. Encadena los guardrails sobre PaymentService: conecta `payment_service:Tool` → **`guardrail.idempotency`** (`keyFields: [pnr, session_id]`) → **`guardrail.confirm`** (`threshold: amount > 500`) → **`guardrail.resilience`** (`retries: 2`). Todos los puertos son `Tool → Tool`.
14. Arrastra **`agent.react`** al centro. Conecta todos los puertos de entrada:
    - `model.llm:Model` → `orchestrator:Model`
    - `io.input:Message` → `orchestrator:Message`
    - `tool.retriever (PolicyRAG):Tool` → `orchestrator:Tool`
    - `reservation_tool:Tool` → `orchestrator:Tool`
    - `inventory_tool:Tool` → `orchestrator:Tool`
    - `pricing_tool:Tool` → `orchestrator:Tool`
    - `payment_resilience:Tool` → `orchestrator:Tool`
    - Añade la arista de loop: `orchestrator:Message` → `orchestrator:Message` con `loop: true` (ciclo ReAct).
15. Arrastra **`observability.audit`** (`sink: kafka`, `topic: flight-change-audit`). Conecta `orchestrator:Message` → `audit:Any`.
16. Arrastra **`io.output`** (`format: markdown`, `streaming: true`). Conecta `audit:Any` → `io.output:Any`.
17. Declara los 8 secretos en el panel de secretos (ver sección 6).
18. Pulsa **Validate** — el lienzo debe mostrar todos los puertos requeridos cubiertos. Luego **Generate**.

---

## 5. Config de cada nodo

| Nodo (id) | Tipo | Campos clave | Valor |
|-----------|------|-------------|-------|
| `chat_input` | `io.input` | `channel` / `auth` / `streaming` | `chat` / `booking-token` / `true` |
| `llm` | `model.llm` | `model` / `temperature` / `apiKeyRef` | `anthropic:claude-opus-4-8` / `0.2` / `ANTHROPIC_API_KEY` |
| `embedding_model` | `model.embedding` | `model` / `local` / `apiKeyRef` | `text-embedding-3-large` / `false` / `OPENAI_API_KEY` |
| `policy_pdf` | `loader.pdf` | `bucket` / `ocr` | `s3://airline-docs/fare-rules` / `false` |
| `policy_chunker` | `ingest.chunker` | `strategy` / `chunkSize` / `overlap` | `by-clause` / `800` / `100` |
| `policy_metadata` | `ingest.metadata` | `fields` | `[fare_class, route_type, effective_date]` |
| `policy_store` | `store.pgvector` | `index` / `distance` | `fare_rules` / `cosine` |
| `policy_tool` | `tool.retriever` | `name` / `description` | `policy_rag` / "Consulta reglas de tarifa y penalidades filtradas por fare_class y route_type" |
| `reservation_tool` | `tool.service` | `name` / `baseUrl` / `operation` | `ReservationService` / `…/reservations` / `getItinerary` |
| `inventory_tool` | `tool.service` | `name` / `baseUrl` / `operation` | `InventoryService` / `…/inventory` / `searchFlights` |
| `pricing_tool` | `tool.service` | `name` / `baseUrl` / `operation` | `PricingService` / `…/pricing` / `calculateDelta` |
| `payment_service` | `tool.service` | `name` / `baseUrl` / `operation` | `PaymentService` / `…/payments` / `chargeChangeFee` |
| `payment_idempotency` | `guardrail.idempotency` | `keyFields` / `ttl` | `[pnr, session_id]` / `24h` |
| `payment_confirm` | `guardrail.confirm` | `threshold` / `message` | `amount > 500` / "El costo supera USD 500. ¿Confirmas?" |
| `payment_resilience` | `guardrail.resilience` | `retries` / `breakerThreshold` / `fallbackMessage` | `2` / `0.5` / "Servicio de pago no disponible. Intenta en unos minutos." |
| `orchestrator` | `agent.react` | `system` / `maxSteps` / `streaming` | (ver flow.json) / `10` / `true` |
| `audit` | `observability.audit` | `sink` / `topic` | `kafka` / `flight-change-audit` |
| `chat_output` | `io.output` | `format` / `streaming` | `markdown` / `true` |

---

## 6. Secretos requeridos

```
ANTHROPIC_API_KEY      — LLM Claude Opus 4.8
OPENAI_API_KEY         — modelo de embeddings text-embedding-3-large
DATABASE_URL           — Postgres + pgvector (índice fare_rules)
RESERVATION_API_KEY    — ReservationService HTTP
INVENTORY_API_KEY      — InventoryService HTTP
PRICING_API_KEY        — PricingService HTTP
PAYMENT_API_KEY        — PaymentService HTTP
KAFKA_BOOTSTRAP        — broker Kafka para audit trail
```

En modo mock (`MOCK=true`) solo se necesitan `ANTHROPIC_API_KEY` y `DATABASE_URL` (o pueden omitirse si el store también está mockeado localmente).

---

## 7. Qué genera el codegen

`deploymentTarget: chat-service` produce un proyecto **listo para probar y desplegar**:

```
airline-flight-change/
├── app/
│   ├── main.py              # FastAPI + UI (pip install -e ".[server]")
│   ├── server_stdlib.py     # Servidor HTTP sin deps (Docker / Cloud Run)
│   ├── engine.py            # Conmuta mock | integración HTTP | LangGraph
│   ├── integration.py       # Tools vía HTTP real
│   ├── mockrun.py           # CLI mock (stdlib)
│   └── graph.py             # LangGraph — esqueleto para MOCK=false prod
├── static/index.html        # Chat web
├── mocks/services/          # APIs HTTP mock (reservation, payment, …)
├── runtime/                 # Motor mock
├── tests/                   # test_flow.py + test_chat_api.py
├── docker-compose.yml       # mock simple (:8888)
├── docker-compose.integration.yml  # mock-services + Kafka + chat
├── gcp/deploy.sh            # Cloud Run
├── flow.json                # Tu diagrama (fuente de verdad)
└── WALKTHROUGH.md           # Tutorial paso a paso
```

**Guía completa (tipo video):** [07 · Del lienzo al chat en producción](../../docs/07-airline-chat-walkthrough.md)

---

## 8. Probarlo

### Nivel 1 — Sin instalar nada (mock en proceso)

```bash
python3 -m ragorbit generate examples/01-airline-flight-change/flow.json --out build/airline
cd build/airline
python3 -m unittest discover -s tests
python3 -m app.mockrun "Quiero cambiar mi vuelo SCL-BOG del 15 al 17"
```

### Nivel 2 — UI local

```bash
pip install -e ".[server]"
python -m app.main
# http://localhost:8000
```

### Nivel 3 — Docker realista (servicios HTTP + Kafka)

```bash
docker compose -f docker-compose.integration.yml up --build
# http://localhost:8888  (UI + API)
```

Turno 1 — solicitud (no cobra):

```bash
curl -X POST http://localhost:8888/chat \
  -H "Content-Type: application/json" \
  -d '{"session_id":"sess-001","message":"Quiero cambiar mi vuelo SCL-BOG del 15 al 17"}'
```

Turno 2 — confirmación:

```bash
curl -X POST http://localhost:8888/chat \
  -H "Content-Type: application/json" \
  -d '{"session_id":"sess-001","message":"Sí, confirmo el cambio."}'
```

### Verificación automática (desde el repo)

```bash
python3 tools/test_airline_docker.py
```

### Google Cloud Run

```bash
export GCP_PROJECT_ID=tu-proyecto
bash gcp/deploy.sh
```

---

## 9. Conceptos staff-level

### Idempotencia por (PNR, session_id)

El `guardrail.idempotency` construye una clave compuesta `PNR + session_id` y la persiste con TTL de 24 horas. Si la misma transacción llega dos veces en ese período (reintento del cliente, doble-click, reconexión SSE), el guardrail detecta la clave ya usada y devuelve la respuesta original cacheada sin invocar a PaymentService de nuevo. Esto es crítico en canales con streaming SSE: una desconexión puede llevar al cliente a reintentar antes de recibir la confirmación.

En producción la clave se almacena en Redis. En modo mock se usa un dict en memoria. El campo `ttl: 24h` cubre el caso de itinerarios emitidos tarda-noche que el pasajero intenta reimprimir al día siguiente (mismo PNR, sesión expirada → no debe cobrar).

### Confirm-gate mayor a USD 500

`guardrail.confirm` intercepta la llamada a PaymentService **antes** de ejecutarla. Evalúa la expresión `amount > 500` contra los argumentos que el agente va a pasar. Si se cumple, pausa la ejecución y devuelve el `message` de confirmación al canal de chat. El agente interpreta la respuesta del usuario ("sí" / "no") y, solo con confirmación positiva, libera la llamada original. Importa que el guardrail actúa sobre el `Tool` envuelto — el agente no gestiona esta lógica; es transparente para el LLM y no consume pasos de `maxSteps`.

### Circuit breaker (guardrail.resilience)

`guardrail.resilience` implementa el patrón Circuit Breaker sobre PaymentService. Con `breakerThreshold: 0.5`, si más del 50 % de las llamadas en una ventana fallan, el circuito se abre y las siguientes llamadas retornan inmediatamente con el `fallbackMessage` sin llegar al servicio. Se intenta la recuperación tras un cooldown configurable. Los `retries: 2` aplican solo con circuito cerrado. Esto protege al agente de quedar bloqueado en esperas de timeout cuando el servicio de pago está degradado — especialmente importante durante ventanas de alta demanda (check-in masivo, disrupciones).

### Audit trail en Kafka

`observability.audit` actúa como passthrough: recibe el `Message` de salida del orquestador y, antes de enviarlo a `io.output`, serializa el evento (tool name, argumentos, respuesta, timestamp, session_id, PNR) y lo publica en el topic `flight-change-audit`. Kafka garantiza retención configurable (por defecto 7 días) y replay. Esto satisface los requisitos de trazabilidad de IATA y normativas locales de aviación: cada acción del agente — especialmente cobros — queda registrada con su contexto completo e inmutable.

### Filtros duros por fare_class en PolicyRAG

`tool.retriever` envuelve el `Retriever` de `store.pgvector` que fue alimentado con metadatos `fare_class` y `route_type` por `ingest.metadata`. Al construir la query de recuperación, el agente incluye esos valores (extraídos del itinerario devuelto por ReservationService) como **filtros duros** (hard filters), no como parte del vector semántico. Esto garantiza que los chunks de penalidades para una tarifa Economy nunca contaminen la respuesta para una tarifa Plus, incluso si semánticamente son similares. Los filtros duros son un guardrail de precisión: el sistema no puede "confundirse" entre tarifas por similitud de texto.

---

⬅️ [Índice](../../README.md)
