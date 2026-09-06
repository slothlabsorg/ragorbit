# Caso 10 · Logística — Rebooking de envíos en disrupción masiva

> **Target:** `event-worker` · **Nodo de entrada:** `io.event-source` (Kafka)

---

## 1. Problema / industria y a quién sirve

**Industria:** Logística y última milla (operadoras de paquetería, freight forwarders, marketplaces con red propia).

**Problema:** Un evento de disrupción masiva —tormenta que cierra un hub regional, fallo de transportista, corte de infraestructura— puede afectar simultáneamente a miles de envíos en tránsito. El proceso manual de rebooking (un agente humano analiza cada envío, consulta políticas, propone alternativa, llama al cliente) colapsa en minutos: los SLA se incumplen, los clientes premium no reciben trato diferenciado y el costo operativo explota.

**A quién sirve:**
- **Operadores de logística B2B/B2C** que manejan volumen de cinco o seis cifras de envíos por día y necesitan recuperarse en minutos, no en horas.
- **Marketplaces** con red de transportistas propia que deben honrar garantías de entrega a clientes premium incluso en escenarios adversos.
- **Responsables de operaciones** (Ops Leads, Control Tower) que necesitan visibilidad en tiempo real de cuántos envíos se auto-confirmaron vs cuántos requirieron intervención humana o LLM.

**Guardarrail de negocio central:** ningún envío puede quedar sin rebook (cobertura 100 %) ni ser rebookeado dos veces (idempotencia). Las políticas aplicables dependen de la *causa* de la disrupción: un cierre por clima es "sin penalidad" para el cliente; un error del transportista puede activar compensaciones adicionales.

---

## 2. Resultado esperado

Dado un evento de disrupción en Kafka (por ejemplo, cierre del hub MIA por tormenta con 3 000 envíos afectados):

1. El worker consume el evento y segmenta los envíos en **P1 / P2 / P3** según tier de cliente, conexiones perdidas y severidad.
2. Para cada envío en paralelo (hasta 16 simultáneos), el fan-out:
   - Obtiene el perfil (tier, historial, preferencias).
   - Recupera las políticas de rebook filtradas por causa (`weather`).
   - Busca alternativas disponibles en 48 h.
   - **Auto-confirma** la alternativa obvia sin intervención humana cuando el caso es simple (P2/P3 con opción única).
   - Delega al **LLM** solo los casos complejos (P1 multi-leg, política ambigua, sin alternativa directa).
3. El cliente recibe notificación por email, SMS y/o push con la nueva opción confirmada o las alternativas para elegir.
4. Todo queda registrado en el audit trail de Kafka y las métricas OTLP muestran: throughput, tasa de auto-confirm vs LLM, latencia por prioridad.

**Resultado tangible:** tasa de auto-confirm > 70 % en disrupciones estándar (clima), latencia P95 < 8 s por envío, cero dobles rebookings.

---

## 3. Arquitectura (ASCII con puertos)

```
 KAFKA ──── io.event-source ──(Event)──▶ logic.rules ──(Decision)──▶ logic.router
             shipment.disruption          prioridad/severidad         simple | complejo
             partitionKey=shipment_id     P1/P2/P3 + track            │
             exactlyOnce=true                                          │(Any→Event)
                                                                       ▼
                          ┌────────────────── agent.fanout ───────────────────────┐
                          │  concurrency=16                                        │
                          │  defaults.llm = claude-opus-4-8 (casos complejos)     │
                          │                                                        │
  tool.service ──(Tool)──▶│  ShipmentProfileService  (tier, historial, prefs)     │
  ShipmentProfileService  │                                                        │──(Any)──▶ io.notify
                          │  tool.retriever ──(Tool)──▶ PolicyRAG                 │           email,sms,push
  store.pgvector          │   hardFilters=[disruption_cause] en subAgentSystem    │
   rebook_policies        │   ← store.pgvector(Retriever)                         │──(Any)──▶ observability.audit
    └──(Retriever)──▶     │                                                        │           sink=kafka
   tool.retriever ──(Tool)▶│  tool.service ──(Tool)──▶ AlternativesService        │
                          │   (rutas/transportistas alternativas, ventana 48h)    │──(Any)──▶ observability.metrics
  tool.service ──(Tool)──▶│                                                        │           exporter=otlp
  AlternativesService     │  tool.service ──(Tool)──▶ AutoConfirmService          │
                          │   (confirma sin humano si opción obvia)               │
  tool.service ──(Tool)──▶│                                                        │
  AutoConfirmService      └────────────────────────────────────────────────────────┘

 model.embedding ──(Embeddings)──▶ store.pgvector (rebook_policies)
```

**Leyenda de puertos usados:**

| Arista | Puerto origen | Puerto destino |
|--------|--------------|----------------|
| event-source → logic.rules | `Event` | `Any` |
| logic.rules → logic.router | `Decision` | `Decision` |
| logic.router → fanout | `Any` | `Event` |
| tool.service × 3 → fanout | `Tool` | `Tool` |
| tool.retriever → fanout | `Tool` | `Tool` |
| embedding_model → policy_store | `Embeddings` | `Embeddings` |
| policy_store → policy_tool | `Retriever` | `Retriever` |
| fanout → notify / audit | `Any` | `Any` |
| audit → metrics | `Any` | `Any` |

> **LLM para casos complejos:** el nodo `model.llm` no necesita arista explícita hacia `agent.fanout` porque el fan-out consume el modelo a través del campo `defaults.llm` del flow (`anthropic:claude-opus-4-8`). El sub-agente lo invoca internamente cuando `track == 'complex'`.

---

## 4. Construirlo paso a paso

### Paso 1 — Fuente de eventos

Crea el nodo `io.event-source` y configura:
- `topic: shipment.disruption`
- `partitionKey: shipment_id` (Kafka garantiza orden por envío)
- `exactlyOnce: true` (ningún rebooking doble)

El `deploymentTarget` queda automáticamente en `event-worker`.

### Paso 2 — Ingesta del índice de políticas (pipeline offline)

Este pipeline se ejecuta una vez (o cuando cambien las políticas) y no forma parte del worker en tiempo real:

1. Agrega un `model.embedding` (text-embedding-3-large) para producir el vector de embeddings.
2. Agrega un `store.pgvector` con `index: rebook_policies`. Conecta `Embeddings → Embeddings` desde el modelo.
3. Conecta `store.pgvector (Retriever) → tool.retriever (Retriever)` directamente. El `tool.retriever` expone el store como tool del sub-agente.

El filtro por `disruption_cause` se aplica a nivel de prompt en `subAgentSystem`: el sub-agente instruye a PolicyRAG que filtre por la causa del evento antes de recuperar chunks. En producción se puede añadir un `retrieval.vector` standalone con `hardFilters: [disruption_cause]` como nodo adicional si se quiere imponer el filtro como guardrail en el grafo (no solo en el prompt).

### Paso 3 — Segmentación por prioridad

Agrega `logic.rules` y define las reglas de clasificación:
- P1 (complejo): tier premium, conexiones perdidas, severidad CRITICAL.
- P2/P3 (simple): flexible o estándar sin complicaciones.

### Paso 4 — Router de track

Conecta `logic.rules (Decision) → logic.router`. Define dos ramas: `simple` y `complex`. Ambas alimentan al mismo `agent.fanout` (el sub-agente se comporta diferente según el campo `track` del evento enriquecido).

### Paso 5 — Tools del fan-out

Agrega los cuatro `tool.service`:
- **ShipmentProfileService**: perfil completo del envío (tier, historial, preferencias de cliente).
- **AlternativesService**: rutas y transportistas alternativos disponibles en ventana de 48 h.
- **AutoConfirmService**: confirma sin intervención humana cuando hay una opción obvia.

Conecta cada uno `Tool → fanout (Tool)`.

### Paso 6 — LLM para casos complejos

El LLM se configura a nivel de flow en `defaults.llm: "anthropic:claude-opus-4-8"`. No requiere arista explícita: `agent.fanout` lo consume internamente cuando el sub-agente determina que el caso es `track == 'complex'` (multi-leg, política ambigua). El secreto `ANTHROPIC_API_KEY` se declara en `secrets[]` con `usedBy: [fanout]`.

### Paso 7 — Fan-out

Configura `agent.fanout`:
- `concurrency: 16`
- `subAgentSystem`: instrucciones del agente (ver sección 5).

El fan-out despacha un sub-agente stateless por envío (o micro-batch). El estado persiste en el event log de Kafka y en la BD, no en memoria del agente.

### Paso 8 — Notificación y observabilidad

- `io.notify` con `channels: [email, sms, push]` — conecta `fanout (Any) → notify (Any)`.
- `observability.audit` con `sink: kafka, topic: rebooking-audit` — conecta `fanout (Any) → audit (Any)`.
- `observability.metrics` con `exporter: otlp` — conecta `audit (Any) → metrics (Any)`.

### Paso 9 — Secretos

Declara todos los secretos (solo nombres) en `secrets[]`. Ver sección 6.

### Paso 10 — Generar y levantar

```bash
ragorbit codegen --flow flow.json --out ./generated
cd generated
MOCK=true docker compose up
```

---

## 5. Config de cada nodo (tabla)

| ID nodo | `type` | Config principal |
|---------|--------|-----------------|
| `disruption_source` | `io.event-source` | `broker: kafka`, `topic: shipment.disruption`, `partitionKey: shipment_id`, `exactlyOnce: true` |
| `priority_rules` | `logic.rules` | `rules`: P1 si tier==premium o connections_lost>0 o severity==CRITICAL; P2 si flexible; P3 else |
| `track_router` | `logic.router` | `branches`: `simple` (track==simple), `complex` (track==complex) |
| `embedding_model` | `model.embedding` | `model: text-embedding-3-large`, `local: false`, `apiKeyRef: OPENAI_API_KEY` |
| `policy_store` | `store.pgvector` | `index: rebook_policies`, `distance: cosine` |
| `policy_tool` | `tool.retriever` | `name: policy_rag`, `description`: consulta políticas filtradas por causa de disrupción (hardFilters por `disruption_cause` aplicados en el prompt del sub-agente) |
| `shipment_profile_tool` | `tool.service` | `name: ShipmentProfileService`, `operation: getProfile`, input: `{shipment_id, include_history}` |
| `alternatives_tool` | `tool.service` | `name: AlternativesService`, `operation: getAlternatives`, input: `{shipment_id, window_hours, disruption_cause}` |
| `autoconfirm_tool` | `tool.service` | `name: AutoConfirmService`, `operation: autoConfirm`, input: `{shipment_id, alternative_id, reason}` |
| `fanout` | `agent.fanout` | `concurrency: 16`, `subAgentSystem`: instrucciones de rebooking; LLM para casos complejos vía `defaults.llm = anthropic:claude-opus-4-8` |
| `notify` | `io.notify` | `channels: [email, sms, push]` |
| `audit` | `observability.audit` | `sink: kafka`, `topic: rebooking-audit` |
| `metrics` | `observability.metrics` | `exporter: otlp` |

---

## 6. Secretos (solo nombres)

```
ANTHROPIC_API_KEY        — agent.fanout vía defaults.llm (claude-opus-4-8, casos complejos)
OPENAI_API_KEY           — model.embedding (índice de políticas)
DATABASE_URL             — store.pgvector (rebook_policies)
KAFKA_BOOTSTRAP          — io.event-source + observability.audit
SHIPMENT_PROFILE_API_KEY — tool.service ShipmentProfileService
ALTERNATIVES_API_KEY     — tool.service AlternativesService
AUTOCONFIRM_API_KEY      — tool.service AutoConfirmService
NOTIFY_API_KEY           — io.notify
OTLP_ENDPOINT            — observability.metrics
```

En modo mock (`MOCK=true`) solo se necesita `KAFKA_BOOTSTRAP` si el entorno levanta un broker local (el compose lo incluye). El resto de los servicios los simulan los mocks generados.

---

## 7. Qué genera el codegen

```
generated/
├── app/
│   ├── worker.py                  # consumidor Kafka (aiokafka), exactly-once con transacciones
│   ├── nodes/
│   │   ├── priority_rules.py      # evaluador determinista de reglas (no llama LLM)
│   │   ├── track_router.py        # bifurcación simple/complejo
│   │   ├── fanout.py              # asyncio.gather con semáforo (concurrency=16)
│   │   ├── sub_agent.py           # agente stateless: usa tools según track; LLM vía defaults
│   │   └── notify.py              # dispatcher email/sms/push
│   └── tools/
│       ├── shipment_profile.py
│       ├── alternatives.py
│       ├── autoconfirm.py
│       └── policy_rag.py          # tool.retriever sobre store.pgvector (rebook_policies)
├── mocks/
│   ├── shipment_profile_mock.py   # devuelve perfil con tier/historial/preferencias
│   ├── alternatives_mock.py       # genera 1-3 alternativas en ventana 48h
│   ├── autoconfirm_mock.py        # registra confirmación sin backend real
│   ├── kafka_mock_producer.py     # emite eventos de disrupción de muestra
│   └── fixtures/
│       ├── disruption_events.json # 50 eventos de muestra (cierre hub MIA)
│       ├── shipment_profiles.json
│       └── rebook_policies.json   # políticas weather, hub_closure, carrier_failure
├── tests/
│   ├── test_priority_rules.py
│   ├── test_fanout_simple.py      # verifica auto-confirm en casos P2/P3
│   ├── test_fanout_complex.py     # verifica delegación a LLM en P1 multi-leg
│   └── test_exactly_once.py      # verifica que un mismo shipment_id no se rebook dos veces
├── docker-compose.yml             # kafka + postgres/pgvector + worker + mock-services
└── .env.template                  # solo nombres de secretos
```

**Esqueleto generado:** worker `asyncio` con `aiokafka`, transacciones Kafka para exactly-once, `asyncio.gather` con `asyncio.Semaphore(16)` para el fan-out, LangGraph para el sub-agente stateless.

---

## 8. Probarlo con mocks (comandos + entrada + salida)

### Levantar el entorno

```bash
cd generated
MOCK=true docker compose up --build
# Kafka, Postgres/pgvector, worker y mock-services arrancan juntos
```

### Simular un cierre de hub con N envíos

```bash
# Emitir 100 eventos de disrupción en el topic shipment.disruption
# (hub MIA cerrado por tormenta, mezcla de tiers y configuraciones)
python mocks/kafka_mock_producer.py \
  --topic shipment.disruption \
  --fixture mocks/fixtures/disruption_events.json \
  --count 100
```

**Ejemplo de evento de entrada (un envío):**

```json
{
  "shipment_id":      "SHP-20240614-00742",
  "disruption_cause": "weather",
  "hub_affected":     "MIA",
  "tier":             "standard",
  "connections_lost": 0,
  "delivery_flexibility": "flexible",
  "disruption_severity": "HIGH",
  "destination":      "ORD",
  "eta_original":     "2024-06-15T14:00:00Z"
}
```

### Salida esperada en los logs del worker

```
[priority_rules]  SHP-20240614-00742 → P2 / track=simple
[fanout]          Sub-agente #7 procesando SHP-20240614-00742
[policy_rag]      Recuperadas 3 políticas (disruption_cause=weather) — sin penalidad aplicable
[alternatives]    2 alternativas encontradas: ALT-881 (ETA +6h), ALT-903 (ETA +14h)
[autoconfirm]     Confirmado ALT-881 automáticamente (opción única en ventana preferida)
[notify]          Notificación enviada [email, push] → cliente@example.com
[audit]           Evento emitido → rebooking-audit
```

**Salida para un caso P1 complejo (multi-leg):**

```
[priority_rules]  SHP-20240614-00189 → P1 / track=complex
[fanout]          Sub-agente #2 procesando SHP-20240614-00189
[policy_rag]      Recuperadas 5 políticas (disruption_cause=weather)
[llm]             Analizando itinerario multi-leg MIA→ORD→SEA con 2 conexiones perdidas
[llm]             Propuesta: ruta alternativa MIA→DFW→SEA (ETA +9h, sin penalidad, compensación $15)
[autoconfirm]     NO auto-confirmado (multi-leg ambiguo) — opciones enviadas al cliente
[notify]          3 opciones enviadas [email, sms, push] → cliente.premium@example.com
```

### Verificar métricas de la crisis

```bash
# Ver tasa de auto-confirm vs LLM en tiempo real (OTLP → Prometheus/Grafana local)
curl http://localhost:9090/api/v1/query \
  --data-urlencode 'query=sum(rebooking_autoconfirm_total) / sum(rebooking_processed_total)'
# Resultado esperado con disruption_cause=weather: ~0.74 (74 % auto-confirm)

# Latencia P95 por prioridad
curl http://localhost:9090/api/v1/query \
  --data-urlencode 'query=histogram_quantile(0.95, rebooking_duration_seconds_bucket)'
# P1: ~6.2s  P2: ~2.1s  P3: ~1.8s
```

### Test de exactly-once

```bash
# Enviar el mismo shipment_id dos veces (simula retry de Kafka)
python mocks/kafka_mock_producer.py \
  --topic shipment.disruption \
  --fixture mocks/fixtures/disruption_events.json \
  --shipment-id SHP-20240614-00742 \
  --count 2

# Verificar en el log de audit que solo hay UNA entrada para ese shipment_id
python -c "
import json
events = [json.loads(l) for l in open('logs/audit.jsonl')]
ids = [e['shipment_id'] for e in events if e['shipment_id'] == 'SHP-20240614-00742']
assert len(ids) == 1, f'Doble rebooking detectado: {len(ids)} entradas'
print('OK — exactly-once verificado')
"
```

### Suite de tests automatizados

```bash
pytest tests/ -v
# tests/test_priority_rules.py          PASSED (8 casos)
# tests/test_fanout_simple.py           PASSED — auto-confirm en P2/P3
# tests/test_fanout_complex.py          PASSED — LLM activado en P1 multi-leg
# tests/test_exactly_once.py            PASSED — sin dobles rebookings
```

---

## 9. Conceptos staff-level

### Escala con particiones de Kafka

`io.event-source` con `partitionKey: shipment_id` garantiza que todos los eventos de un mismo envío aterricen en la misma partición. Puedes escalar el worker horizontalmente añadiendo réplicas (un consumer group); Kafka distribuye las particiones entre ellas sin colisión. Con 30 particiones y 3 réplicas del worker, cada réplica procesa 10 particiones en paralelo —y el fan-out interno (`concurrency: 16`) multiplica eso dentro de cada réplica—. El throughput crece linealmente añadiendo réplicas hasta saturar los backends.

### Agentes stateless (estado en el event log + BD)

Cada sub-agente del fan-out no guarda estado en memoria: lee el perfil del envío en cada invocación, persiste la decisión en la BD transaccional y emite al topic de audit. Si el worker cae y Kafka reentrega el evento, el sub-agente consulta la BD, detecta que el envío ya fue procesado y devuelve el resultado cacheado sin ejecutar de nuevo. El estado de la conversación está en el event log, no en el heap —patrón event sourcing aplicado a agentes AI.

### Exactly-once: ningún envío sin rebook ni doble rebook

`exactlyOnce: true` en `io.event-source` activa las transacciones Kafka (producer transaccional + `isolation.level=read_committed`). El commit del offset y la escritura al topic de audit son atómicos: si el worker muere a mitad, el offset no avanza y el evento se reprocesa, pero la idempotencia en la BD (clave `shipment_id`) evita el doble rebooking. Esta combinación —exactly-once de Kafka + idempotencia en BD— es la garantía completa.

### Auto-confirm determinista vs LLM selectivo (control de costo)

`logic.rules` clasifica los envíos antes de invocar cualquier LLM. Para casos P2/P3 (la mayoría en una disrupción típica por clima), el sub-agente sigue un árbol de decisión determinista: si `alternatives.count == 1` y la política no tiene penalidad, `AutoConfirmService` se llama directamente. El LLM solo entra para P1 (multi-leg, clientes premium con preferencias complejas, política ambigua). En una disrupción de 3 000 envíos por tormenta, ~74 % se resuelven sin LLM: el ahorro en tokens puede ser de 10-20x respecto a invocar Claude en todos los casos.

### PolicyRAG por causa de disrupción

El `hardFilter: [disruption_cause]` en `retrieval.vector` es un guardrail de negocio, no solo de performance: garantiza que el agente nunca vea políticas de `carrier_failure` cuando la causa es `weather`. En logística, aplicar la política equivocada puede significar cobrar una penalidad que el contrato prohíbe, o emitir una compensación que no corresponde. El filtro duro hace que el LLM trabaje solo con chunks legalmente relevantes para esa disrupción.

### Guardrails de negocio

Este flujo no usa `guardrail.*` explícitos porque el control es diferente al de un agente conversacional: la idempotencia (Kafka + BD) actúa como el guardrail de transacción, y `logic.rules` actúa como el guardrail de decisión (segmenta antes de actuar). En producción se añadiría `guardrail.pre-tool` antes de `AutoConfirmService` para verificar que el shipment_id no esté ya en estado "rebookeado" en la BD.

### Observabilidad durante la crisis

`observability.metrics` con `exporter: otlp` emite tres métricas clave en tiempo real:
- **`rebooking_processed_total`** (particionado por `priority` y `track`): cuántos envíos se procesaron.
- **`rebooking_autoconfirm_total`** vs **`rebooking_llm_total`**: tasa de auto-confirm (indicador de eficiencia operativa).
- **`rebooking_duration_seconds`** (histograma por `priority`): latencia P50/P95/P99 por segmento.

Durante una crisis activa, el Control Tower ve en Grafana la tasa de recuperación en tiempo real. Si `autoconfirm_total / processed_total` cae por debajo del 50 %, es señal de que la disrupción tiene un patrón inusual (ej. multi-leg masivo) y conviene revisar las reglas de segmentación o aumentar el concurrency del fan-out.

---

⬅️ [Índice](../../README.md)
