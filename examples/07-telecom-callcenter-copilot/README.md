# 07 · Copilot para agentes humanos de call center — Telecom

---

## 1. Problema / industria y a quién sirve

**Industria:** Telecomunicaciones — servicio al cliente por teléfono.

**El problema:** Un agente humano de call center recibe decenas de llamadas al día sobre temas heterogéneos: cargos en la factura, cortes de servicio, portabilidad, planes de datos, regulaciones de roaming. Para responder con precisión necesita consultar manuales de política interna, procedimientos de soporte técnico y FAQs, todo mientras el cliente espera. Buscar manualmente en esos documentos introduce demoras, errores y variabilidad entre agentes.

**A quién sirve:** Al agente humano que ya está en la llamada. El copilot **no reemplaza al agente** — le susurra la respuesta correcta en un panel lateral en menos de 1.5 segundos, sin que el cliente lo note. También sirve al equipo de calidad: el feedback marcado por los agentes (útil/no-útil) alimenta la mejora continua del sistema.

---

## 2. Resultado esperado

- Mientras el cliente habla, el fragmento de audio se transcribe en streaming (Deepgram).
- El clasificador de intención descarta fragmentos no accionables (saludos, silencios, frases de relleno) para no desperdiciar llamadas al RAG.
- Los fragmentos accionables se normalizan (jerga interna → términos canónicos), se rutean al índice correcto (policy / procedure / faq) y generan una sugerencia de respuesta citada de máximo 3 oraciones.
- La sugerencia aparece en el panel lateral del agente en **menos de 1.5 segundos** desde que termina el fragmento.
- El agente marca la sugerencia como útil o no útil; esa señal mejora el reranker de forma continua.

---

## 3. Arquitectura (ASCII con puertos)

```
Audio de la llamada
        │
        ▼ Audio
  ┌──────────┐  Message   ┌──────────────┐  Query    ┌──────────────┐  Query
  │  io.stt  │──────────▶ │ model.intent │─────────▶ │ query.rewrite│────────▶
  │ (deepgram│            │ (facturacion │            │ (glossaryRef)│
  │  es)     │            │  soporte_tec │            └──────────────┘
  └──────────┘            │  no_accion.) │                   │ Query
                          └──────────────┘                   │
                                                             ▼
                    ┌─────────────────────────────────────────────────────────┐
                    │              Capa de ingesta compacta                   │
                    │  loader.pdf ──┐                                         │
                    │  loader.pdf ──┼──▶ Documents ──▶ store.multi-index      │
                    │  loader.web ──┘          (policy / procedure / faq)     │
                    │                              │ Retriever                │
                    └──────────────────────────────┼─────────────────────────┘
                                                   │ Retriever
                                                   ▼
                                        ┌──────────────────┐
                                        │ retrieval.router │◀── Query
                                        │ (keyword/intent) │
                                        └──────────────────┘
                                                │ Chunks
                                                ▼
                                        ┌──────────────────┐
                                        │retrieval.reranker│
                                        │  (topN 3,        │◀── feedbackRef
                                        │   feedbackRef)   │
                                        └──────────────────┘
                                                │ Chunks
                          Model ◀─ model.llm    │
                            │                  ▼
                            └────────▶ ┌──────────────┐  Message
                                       │ logic.prompt │──────────▶
                                       │ (síntesis)   │
                                       └──────────────┘
                                                            │ Message + Chunks
                                                            ▼
                                               ┌────────────────────┐
                                               │  logic.citations   │
                                               │  (mode: enforce)   │
                                               └────────────────────┘
                                                            │ Message
                                                            ▼
                                               ┌────────────────────┐
                                               │    io.panel        │
                                               │  (cite: true)      │◀── panel lateral
                                               └────────────────────┘
                                                            │ Any
                                                            ▼
                                               ┌─────────────────────────┐
                                               │ observability.feedback  │
                                               │ (signals: thumbs)       │
                                               └─────────────────────────┘
                                                            │ loop: true
                                                            └──────────▶ reranker
```

---

## 4. Construirlo paso a paso

**Paso 1 — Ingesta de documentos (offline, una vez)**

Conecta los tres loaders al `store.multi-index`:
- `loader.pdf` → documentos de política (regulaciones, tarifas, condiciones legales).
- `loader.pdf` → procedimientos internos de soporte técnico.
- `loader.web` → FAQs desde la intranet.

Cada loader produce `Documents` que se indexan en su slot correspondiente del multi-index. El embedding model (`model.embedding`, `local: true`) genera los vectores sin depender de APIs externas en runtime.

**Paso 2 — Entrada por voz**

Conecta `io.stt` (Deepgram, `language: es`) como nodo de entrada. Este nodo produce fragmentos `Message` en streaming conforme llega el audio de la llamada. El `deploymentTarget` resultante es `chat-service` (FastAPI con WebSocket).

**Paso 3 — Compuerta de intención**

Conecta `stt.Message → intent.Message`. El clasificador `model.intent` usa embeddings ligeros para etiquetar cada fragmento como `facturacion`, `soporte_tecnico` o `no_accionable`. Solo los fragmentos accionables continúan al RAG; los demás se descartan. Esto elimina entre el 30-50% de las llamadas innecesarias al stack de recuperación.

**Paso 4 — Normalización de jerga**

Conecta `intent.Query → rewrite.Message`. El nodo `query.rewrite` expande abreviaciones y sinónimos internos ("baja de plan" → "cancelación de servicio", "roaming gringo" → "roaming internacional EE.UU.") usando el glosario referenciado en `glossaryRef`.

**Paso 5 — Routing al índice correcto**

Conecta `rewrite.Query → router.Query` y `multi_index.Retriever → router.Retriever`. Las reglas del router mapean el intent/keyword al índice: `facturacion → policy`, `soporte_tecnico → procedure`, fallback → `faq`. Esto evita buscar en los tres índices a la vez (latencia y ruido innecesarios).

**Paso 6 — Reranking con feedback**

Conecta `router.Chunks → reranker.Chunks`. El reranker recorta a los 3 fragmentos más relevantes usando `bge-reranker`. El campo `feedbackRef: "feedback_store"` permite que el modelo mejore con las señales de los agentes.

**Paso 7 — Síntesis y citas**

Conecta `llm.Model → synthesis.Model` y `reranker.Chunks → synthesis.Chunks`. El nodo `logic.prompt` genera la sugerencia. Luego `logic.citations` (`mode: enforce`) garantiza que cada afirmación cita su fuente; rechaza cualquier respuesta sin cita.

**Paso 8 — Panel y feedback loop**

`io.panel` (`cite: true`) muestra la sugerencia en el panel lateral sin interrumpir el audio. Desde allí, `observability.feedback` (`signals: thumbs`) captura la marca del agente y la reenvía al reranker (`loop: true`).

---

## 5. Config de cada nodo (tabla)

| Nodo | `type` | Config clave |
|------|--------|-------------|
| STT Deepgram | `io.stt` | `provider: deepgram`, `language: es` |
| Clasificador de intención | `model.intent` | `labels: [facturacion, soporte_tecnico, no_accionable]`, `backend: embeddings`, `threshold: 0.6` |
| Normalización de jerga | `query.rewrite` | `glossaryRef: telecom-internal-glossary`, `expand: true` |
| Loader Policy | `loader.pdf` | `bucket: s3://telecom-docs/policy`, `ocr: false` |
| Loader Procedimientos | `loader.pdf` | `bucket: s3://telecom-docs/procedure`, `ocr: false` |
| Loader FAQ | `loader.web` | `urls: [https://intranet.telecom.internal/faq]`, `crawlDepth: 1` |
| Embeddings locales | `model.embedding` | `model: text-embedding-3-large`, `local: true` |
| Multi-Index | `store.multi-index` | `indexes: [policy, procedure, faq]` |
| Router | `retrieval.router` | `rules: [{facturacion→policy}, {soporte_tecnico→procedure}]`, `fallback: faq` |
| Reranker | `retrieval.reranker` | `model: bge-reranker`, `topN: 3`, `feedbackRef: feedback_store` |
| LLM | `model.llm` | `model: anthropic:claude-opus-4-8`, `temperature: 0.2` |
| Síntesis | `logic.prompt` | `template`: redacta sugerencia de ≤3 oraciones en español |
| Garantía de citas | `logic.citations` | `mode: enforce` |
| Panel lateral | `io.panel` | `cite: true` |
| Feedback loop | `observability.feedback` | `store: feedback_store`, `signals: [thumbs]` |

---

## 6. Secretos (solo nombres)

```
DEEPGRAM_API_KEY      — clave de la API de Deepgram STT
ANTHROPIC_API_KEY     — clave del LLM (Claude)
OPENAI_API_KEY        — embeddings (text-embedding-3-large); omitir si se cambia a local puro
STORAGE_KEY           — acceso a S3/GCS para los loaders de PDF
```

El codegen produce un `.env.template` con solo estos nombres. En modo mock (`MOCK=true`) no se necesitan las claves de servicios externos.

---

## 7. Qué genera el codegen

Al ejecutar `ragorbit codegen flow.json`, el artefacto generado incluye:

```
app/
  main.py               — FastAPI con WebSocket (chat-service)
  nodes/
    stt.py              — cliente Deepgram streaming
    intent.py           — clasificador con embeddings
    rewrite.py          — normalización de jerga con glossary
    multi_index.py      — gestión de tres índices vectoriales
    router.py           — reglas keyword→índice
    reranker.py         — bge-reranker con feedbackRef
    synthesis.py        — logic.prompt (LangGraph node)
    citations.py        — enforce citations
    panel.py            — WebSocket push al panel lateral
    feedback.py         — captura y almacena señales thumbs
  graph.py              — LangGraph StateGraph completo
mocks/
  stt_mock.py           — reproduce transcripts de muestra
  multi_index_mock.py   — índices en memoria (sin vector DB)
  deepgram_mock.py      — fragmentos de audio simulados
tests/
  test_accionable.py    — fragmento accionable llega al panel
  test_no_accionable.py — fragmento descartado no invoca RAG
  test_latencia.py      — end-to-end < 1500 ms (con mocks)
  test_citations.py     — respuesta sin cita es rechazada
Dockerfile
docker-compose.yml      — incluye servicios mock
.env.template
```

La bandera `local: true` en `model.embedding` hace que el codegen genere el nodo de embeddings con `sentence-transformers` en lugar de llamar a una API, eliminando una dependencia de red en el camino crítico de latencia.

---

## 8. Probarlo con mocks (comandos + entrada + salida)

### Levantar el entorno

```bash
MOCK=true docker compose up
# Expone: ws://localhost:8000/ws/copilot  (WebSocket)
#         http://localhost:8000/panel      (panel lateral simulado)
#         http://localhost:8000/feedback   (endpoint de feedback)
```

### Escenario: cliente pregunta por batería de litio en equipaje

El cliente dice por teléfono:

> "Oiga, y si viajo a Cancún, ¿puedo llevar mi batería de litio de la laptop en el equipaje de mano?"

El mock de STT emite este fragmento como `Message`. El flujo completo es:

**1. Intención detectada — accionable**

```json
// intent clasifica:
{ "label": "facturacion", "score": 0.23 }   // descartado
{ "label": "soporte_tecnico", "score": 0.31 } // descartado
{ "label": "no_accionable", "score": 0.11 }   // descartado
// → ninguno supera threshold 0.6...
```

Nota: el caso de la batería de litio cruza entre regulación de política de vuelo y FAQ. El mock está configurado para que el intent lo clasifique como `facturacion` (regulación) con score `0.71`, superando el umbral:

```json
{ "label": "facturacion", "score": 0.71 }
// → accionable, continúa al RAG
```

**2. Normalización**

```
query.rewrite transforma:
  "batería de litio de la laptop en el equipaje de mano"
  → "bateria litio portatil equipaje cabina"
```

**3. Router elige índice `policy`**

```
keyword "facturacion" → index "policy"
retrieval.router recupera 6 fragmentos del índice policy
```

**4. Reranker recorta a top 3**

```
bge-reranker selecciona los 3 fragmentos más relevantes
  sobre regulaciones de baterías de litio en cabina
```

**5. Síntesis con cita — aparece en panel en < 1.5 s**

```
┌─────────────────────────────────────────────────────────────────┐
│  SUGERENCIA COPILOT                                             │
│                                                                 │
│  Las baterías de litio de uso personal (laptops, teléfonos)     │
│  con capacidad ≤ 100 Wh están permitidas en equipaje de mano;   │
│  no se aceptan en bodega [Policy §4.2]. Para baterías entre     │
│  100-160 Wh se requiere autorización previa de la aerolínea     │
│  [Policy §4.3].                                                 │
│                                                                 │
│  [👍 Útil]  [👎 No útil]                                       │
└─────────────────────────────────────────────────────────────────┘
```

**6. El agente marca "útil" — feedback loop**

```bash
curl -X POST http://localhost:8000/feedback \
  -H "Content-Type: application/json" \
  -d '{"queryId": "q-20240614-0312", "signal": "thumbs_up"}'
# → 200 OK { "stored": true, "feedbackStore": "feedback_store" }
```

La señal queda en `feedback_store` y el reranker la incorporará en el próximo ciclo de fine-tune.

### Escenario: fragmento no accionable (descartado)

```
Cliente: "Sí, claro, aja... un momento..."
→ model.intent: no_accionable (score 0.82)
→ flujo termina aquí, sin llamada al RAG
→ panel permanece con la última sugerencia visible
```

### Verificar latencia end-to-end

```bash
docker compose run tests pytest tests/test_latencia.py -v
# PASSED  test_end_to_end_under_1500ms   [0.94s]
```

---

## 9. Conceptos staff-level

**Intent detection como compuerta del RAG**

No todo lo que dice el cliente merece una búsqueda vectorial. Mandar cada fragmento de audio al stack RAG multiplica la latencia y el costo, y genera ruido en el panel (el agente ve sugerencias para "mmm, sí, entiendo"). El nodo `model.intent` actúa como compuerta barata: embeddings locales clasifican en ~5-10 ms si el fragmento es accionable. Solo pasan los fragmentos que realmente requieren una respuesta del conocimiento corporativo. En producción, el 30-50% de los fragmentos son no accionables.

**Latencia objetivo < 1.5 s: tres palancas**

1. **STT streaming:** Deepgram devuelve fragmentos de transcripción mientras el cliente habla, no espera a que termine. Esto solapa el tiempo de transcripción con el tiempo de procesamiento.
2. **Embeddings locales (`local: true`):** el modelo de embeddings corre en el mismo pod, eliminando una llamada de red en el camino crítico. Ahorra 80-150 ms típicos de una llamada a API de embeddings.
3. **Vector en memoria:** el `store.multi-index` en modo dev/demo usa Chroma en memoria; en producción, Qdrant con memoria caché caliente. La búsqueda vectorial en un índice bien dimensionado cuesta 10-30 ms.

Sumando: STT fragment ~100 ms + intent ~10 ms + rewrite ~5 ms + routing+retrieval ~50 ms + reranker ~80 ms + LLM (haiku/sonnet para síntesis corta) ~400-700 ms + citations ~10 ms = **~700-950 ms end-to-end** con mocks, ~1.1-1.4 s en producción.

**Multi-index routing: por qué no buscar en los tres índices**

Unificar todos los documentos en un solo índice vectorial parece más simple, pero introduce dos problemas: (1) ruido — un query sobre roaming puede recuperar fragmentos de procedimientos de soporte técnico irrelevantes que diluyen el top-K; (2) latencia — buscar en tres índices en paralelo y fusionar es más lento que ir directamente al índice correcto. El `retrieval.router` usa reglas deterministas (keyword → índice) que se resuelven en microsegundos, antes de cualquier búsqueda vectorial.

**Feedback loop → mejora continua del reranker**

El nodo `observability.feedback` captura señales `thumbs_up / thumbs_down` del agente humano. Estas señales se almacenan con el queryId, los fragmentos recuperados y el fragmento que finalmente se mostró. El campo `feedbackRef` en `retrieval.reranker` apunta a ese store: el proceso de fine-tune periódico (offline, fuera del flujo de tiempo real) ajusta los pesos del `bge-reranker` con preferencia por los fragmentos que los agentes marcaron como útiles. Resultado: el reranker mejora sin etiquetar datos manualmente.

**Versionado de índices y rollback**

En producción, cada carga de documentos nuevos (actualización de tarifas, cambio de regulación) genera una nueva versión del índice (`policy-v3`, `policy-v4`). El `store.multi-index` puede apuntar a la versión activa con un campo de configuración. Si una nueva versión degrada las métricas de feedback (porcentaje de `thumbs_up` cae), el operador revierte el puntero al índice anterior sin redeploy — en segundos. Esto es especialmente crítico en telecomunicaciones, donde los cambios regulatorios son frecuentes y una respuesta incorrecta tiene consecuencias legales.

---

⬅️ [Índice](../../README.md)
