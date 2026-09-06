# 07 · Del lienzo al chat en producción — Caso aerolínea (paso a paso)

> Guía narrativa para mostrar en video o workshop: qué arrastras en el diagramador, para qué sirve cada bloque, qué descargas al exportar, cómo probarlo en tres niveles (mock → docker con APIs → GCP) y qué queda por completar para producción con LLM real.

**Caso:** [Agente de cambio de vuelo](../examples/01-airline-flight-change/) · `deploymentTarget: chat-service`

**Tiempo estimado:** 45–60 min (diseño + export + docker). Sin cuenta de LLM para los primeros pasos.

---

## Escena 0 — Qué vas a lograr

Al terminar tendrás:

1. Un grafo validado en RAGorbit (el diagrama del bot).
2. Un ZIP exportado con **chat web + API + tests + Docker + scripts GCP**.
3. El bot funcionando contra **servicios HTTP mock** (reservation, inventory, pricing, payment) con **confirm-gate** e **idempotencia**.
4. Un camino claro hacia producción (`app/graph.py` + secretos reales).

```
  RAGorbit (lienzo)  ──export──▶  artefacto/  ──docker──▶  http://localhost:8888
                                       │
                                       └── gcp/deploy.sh ──▶  Cloud Run
```

---

## Escena 1 — Abrir RAGorbit y cargar el template

```bash
cd ragorbit
python3 -m ragorbit serve
# abre http://localhost:8888  (evita conflicto con `ragorbit serve` en :8000)
```

1. En la **galería**, elige **«Agente de cambio de vuelo»**.
2. El lienzo carga ~18 nodos ya cableados. No empieces de cero.

**Qué ves:** un grafo con zona superior conversacional y zona inferior de ingesta de políticas (RAG offline).

---

## Escena 2 — Qué es cada bloque (y por qué lo arrastras)

Recorre el lienzo de izquierda a derecha, de abajo hacia arriba.

### Zona inferior — Ingesta de políticas (offline)

| Bloque | Tipo | Para qué sirve |
|--------|------|----------------|
| **Políticas IATA PDF** | `loader.pdf` | Carga los PDF de reglas tarifarias. En prod: S3/GCS. En mock: fixtures. |
| **Chunker by-clause** | `ingest.chunker` | Parte el PDF por cláusulas (no por páginas sueltas) para citas precisas. |
| **Metadata** | `ingest.metadata` | Etiqueta chunks con `fare_class`, `route_type` para filtros duros en retrieval. |
| **Embedding Model** | `model.embedding` | Vectoriza texto → números para el store. |
| **PgVector fare_rules** | `store.pgvector` | Índice vectorial de políticas. En prod: Postgres+pgvector. |
| **PolicyRAG Tool** | `tool.retriever` | Expone el retriever como **tool** del agente (el LLM decide cuándo consultar reglas). |

**Mensaje para la audiencia:** esto es el pipeline RAG de políticas; corre una vez (o en batch) y alimenta el agente.

### Zona central — El agente

| Bloque | Tipo | Para qué sirve |
|--------|------|----------------|
| **Chat Input** | `io.input` | Entrada del usuario. Define `chat-service` como target de despliegue. |
| **Claude Opus** | `model.llm` | El modelo que razona y elige tools. |
| **Agente ReAct** | `agent.react` | Orquestador: piensa → llama tools → responde. Arista `loop` = ciclo ReAct. |
| **ReservationService** | `tool.service` | HTTP a sistema de reservas (PNR, itinerario). |
| **InventoryService** | `tool.service` | Busca vuelos alternativos. |
| **PricingService** | `tool.service` | Calcula penalidad + diferencia tarifaria. |
| **PaymentService** | `tool.service` | Cobra el cambio. **Transaccional.** |

### Cadena de guardrails (sobre el pago)

Conectados en serie `Tool → Tool`:

| Bloque | Tipo | Para qué sirve |
|--------|------|----------------|
| **Idempotency** | `guardrail.idempotency` | Misma `Idempotency-Key` → un solo cobro. |
| **Confirm > USD 500** | `guardrail.confirm` | No cobra hasta confirmación explícita del usuario. |
| **Circuit Breaker** | `guardrail.resilience` | Reintentos y fallback si el pago falla. |

**Demo clave:** en el turno 1 el pago queda `pendiente-confirmación`. En el turno 2, tras «Sí, confirmo», se ejecuta.

### Salida y observabilidad

| Bloque | Tipo | Para qué sirve |
|--------|------|----------------|
| **Audit Trail Kafka** | `observability.audit` | Publica cada respuesta al bus (regulatorio). |
| **Chat Output** | `io.output` | Respuesta markdown al usuario. |

---

## Escena 3 — Validar y probar en el lienzo (sin exportar)

1. Pulsa **Validar**. Debe quedar en verde (puertos cubiertos, contratos OK).
2. Pulsa **Probar con mocks**. Escribe:

   > Quiero cambiar mi vuelo SCL-BOG del 15 al 17

3. En el inspector ves la respuesta mock y el trace del agente.

**Qué acabas de probar:** el **motor mock del engine** (mismo que irá dentro del ZIP). No es el LLM real; simula tools y guardrails.

---

## Escena 4 — Exportar el artefacto

1. Pulsa **Exportar** (o CLI):

```bash
python3 -m ragorbit generate examples/01-airline-flight-change/flow.json --out build/airline-chat
```

2. Descomprime / entra al directorio. Estructura:

```
airline-chat/
├── app/
│   ├── main.py           # FastAPI + UI web en /
│   ├── engine.py         # mock | integración HTTP | LangGraph
│   ├── integration.py    # tools llaman servicios HTTP
│   ├── mockrun.py        # CLI mock (stdlib)
│   ├── graph.py          # LangGraph — esqueleto para prod real
│   └── bus.py            # audit Kafka o memoria
├── static/index.html     # chat en el navegador
├── mocks/
│   ├── fixtures.json
│   └── services/mock_services.py   # APIs HTTP mock
├── runtime/              # motor mock (copia del engine)
├── tests/
├── docker-compose.yml              # mock simple
├── docker-compose.integration.yml  # stack realista
├── Dockerfile / Dockerfile.services
├── gcp/deploy.sh                   # Cloud Run
├── flow.json                       # tu diagrama (fuente de verdad)
└── WALKTHROUGH.md                  # esta guía (copia)
```

---

## Escena 5 — Nivel 1: tests sin red (30 segundos)

```bash
cd build/airline-chat
python3 -m unittest discover -s tests
python3 -m app.mockrun "Quiero cambiar mi vuelo SCL-BOG del 15 al 17"
```

**Qué valida:** topología del grafo, guardrails, citas, confirm-gate — todo en memoria.

---

## Escena 6 — Nivel 2: servidor local con UI

```bash
pip install -e ".[server]"
python -m app.main
```

Abre **http://localhost:8000**:

- Escribe la solicitud de cambio de vuelo.
- El bot responde pidiendo confirmación (mock en proceso).
- Pulsa **Confirmar** o escribe «Sí, confirmo el cambio.»

**API directa:**

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"Quiero cambiar mi vuelo SCL-BOG del 15 al 17","session_id":"demo-1"}'
```

---

## Escena 7 — Nivel 3: Docker con APIs mock (lo más realista)

Aquí el bot **no simula** los tools en memoria: hace **HTTP real** a servicios mock con contratos, idempotencia y Kafka.

```bash
docker compose -f docker-compose.integration.yml up --build
```

| Contenedor | Rol |
|------------|-----|
| `mock-services` | reservation, inventory, pricing, payment, policy-rag |
| `kafka` | bus de auditoría |
| `app` | chat en :8888 (host) con `INTEGRATION=true` |
| `audit-consumer` | imprime eventos `[AUDIT]` en logs |

1. Abre **http://localhost:8888**.
2. Turno 1: solicitud de cambio → ves llamadas HTTP en el panel lateral.
3. Turno 2: confirmación → `payment/charge` → `TXN-0001`.
4. Revisa logs de `audit-consumer` para el trail regulatorio.

**Verificación automática (desde el repo):**

```bash
python3 tools/test_airline_docker.py
```

---

## Escena 8 — Desplegar en Google Cloud Run

Desde la raíz del artefacto exportado:

```bash
export GCP_PROJECT_ID=tu-proyecto
export GCP_REGION=us-central1
bash gcp/deploy.sh
```

Despliega dos servicios:

1. **`airline-flight-change-services`** — mock HTTP (reservation, payment, …).
2. **`airline-flight-change-chat`** — UI + API; `SERVICES_BASE` apunta al primero.

El script imprime la URL pública del chat.

Alternativa CI:

```bash
gcloud builds submit --config gcp/cloudbuild.yaml
```

---

## Escena 9 — Qué falta para producción «de verdad»

El exportado te deja **muy cerca** en arquitectura y contratos. Para LLM y datos reales:

| Pieza | Estado en el ZIP | Tu trabajo |
|-------|------------------|------------|
| Chat + UI + API | ✅ Generado | Configurar dominio, auth (`io.input` → JWT) |
| Tools HTTP | ✅ Integración mock/prod | Cambiar `SERVICES_BASE` a APIs reales |
| Guardrails | ✅ Mock + integración | Ajustar umbrales en `flow.json` y regenerar |
| Motor mock / tests | ✅ Listo | Mantener en CI |
| `app/graph.py` LangGraph | ⚠️ Esqueleto | Implementar lógica por nodo o plantillas futuras |
| LLM / embeddings | ⚠️ Requiere keys | `MOCK=false`, `INTEGRATION=false`, `.env` |
| PgVector / PDFs | ⚠️ Infra externa | `DATABASE_URL`, bucket de PDFs |

**Modos del artefacto:**

| Variable | Efecto |
|----------|--------|
| `MOCK=true` | Motor en proceso, fixtures (tests, dev rápido) |
| `INTEGRATION=true` | Tools vía HTTP (`docker` / Cloud Run) |
| `MOCK=false` + sin integración | LangGraph en `app/graph.py` (completar) |

---

## Escena 10 — Flujo de trabajo recomendado para equipos

1. **Producto / analista** — arma el grafo en RAGorbit, valida, prueba con mocks.
2. **Dev** — exporta, corre tests, levanta `docker-compose.integration.yml`, valida contratos con backend.
3. **Plataforma** — `gcp/deploy.sh` o pipeline con `gcp/cloudbuild.yaml`.
4. **IA engineer** — completa `app/graph.py`, conecta LLM real, promueve `MOCK=false`.

---

## Referencias

- Flow IR de ejemplo: [`examples/01-airline-flight-change/flow.json`](../examples/01-airline-flight-change/flow.json)
- Demo local con auditoría: [`demo/run_demo.py`](../demo/run_demo.py)
- Conceptos: [01 · Conceptos](./01-concepts.md) · [04 · Codegen](./04-codegen-and-deploy.md)
