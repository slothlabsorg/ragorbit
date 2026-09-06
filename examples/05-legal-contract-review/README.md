# 05 · Revisión de contratos contra playbook

## 1. Problema, industria y a quién sirve

**Industria:** Legal / Servicios corporativos / Cumplimiento normativo.

Toda empresa que firma contratos de cierta magnitud enfrenta el mismo cuello de botella: un abogado o analista debe leer cláusula por cláusula, comparar con el playbook de cláusulas aprobadas internamente, contrastar con la normativa vigente y revisar si algún contrato previo resolvió situaciones similares. El proceso es lento, costoso y propenso a omisiones cuando el volumen de contratos es alto.

Este flujo sirve a:

- **Equipos legales internos** que revisan contratos de proveedores, clientes o socios antes de firmar.
- **Despachos de abogados** que necesitan acelerar due diligence de grandes operaciones (M&A, financiación, infraestructura).
- **Áreas de cumplimiento** que deben verificar que ninguna cláusula entre en conflicto con normativa regulatoria vigente.

El usuario sube el PDF del contrato a revisar, formula su pregunta (por ejemplo, "¿hay riesgos en la cláusula de indemnización?") y recibe un informe estructurado con cada hallazgo clasificado por nivel de riesgo, con citas precisas tanto al contrato como al playbook o regulación que justifican la alerta.

---

## 2. Resultado esperado

El sistema devuelve un informe en Markdown con la siguiente estructura por cada cláusula analizada:

- **Cláusula identificada:** referencia exacta al texto del contrato bajo revisión.
- **Nivel de riesgo:** `alto`, `medio` o `bajo`.
- **Explicación:** descripción del riesgo con cita dual — qué dice el contrato y qué establece el playbook o la normativa de referencia.
- **Recomendación:** acción concreta para mitigar o renegociar la cláusula.

El informe solo se emite si cada hallazgo puede respaldar sus afirmaciones con citas verificadas en los fragmentos recuperados. Si las fuentes recuperadas no contienen la cita necesaria, el verificador de citas rechaza la respuesta y el sistema solicita una reformulación.

---

## 3. Arquitectura (ASCII con puertos)

```
INGESTA DEL CONTRATO (en consulta)
──────────────────────────────────
contract_pdf         contract_chunker          contract_store         contract_retrieval
[loader.pdf]        [ingest.chunker]          [store.pgvector]       [retrieval.vector]
  Documents ──────▶  Documents   Documents ──▶  Documents              Retriever ──▶ Chunks
                     (by-clause)          ──▶  Embeddings (embedding_model)  ──▶(Query←chat_input)

INGESTA DE BASE DE CONOCIMIENTO (en background — 3 índices)
────────────────────────────────────────────────────────────
playbook_pdf  ──▶ playbook_chunker  ──▶ playbook_store ──(Retriever)──┐
[loader.pdf]     [ingest.chunker]     [store.pgvector]                │
regulations_pdf ──▶ regulations_chunker ──▶ regulations_store ─(Ret)─▶  multi_index        router
precedent_pdf  ──▶ precedent_chunker  ──▶ precedent_store ──(Ret)──┘  [store.multi-index] [retrieval.router]
                                                                       Retriever ─────────▶ Retriever
                                                               chat_input.Message ─────────▶ Query
                                                                                              Chunks ──▶

ANÁLISIS Y VERIFICACIÓN
────────────────────────
router.Chunks ──▶ reranker ──▶ Chunks ──────────────────────────────▶ structured_findings
                [retrieval.reranker]           contract_retrieval.Chunks ──▶ Chunks
                  topN: 3                      llm.Model ──────────────────▶ Model
                                                                              Decision ──▶
                              reranker.Chunks ──────────────────────────▶ citations_enforcer
                              chat_input.Message ─────────────────────▶  [logic.citations]
                                                                           mode: enforce
                                                                           Message ──▶

                                       citations_enforcer.Message ──▶ chat_output (Any)
                                       structured_findings.Decision ──▶ chat_output (Any)
                                                                        [io.output]
                                                                        format: markdown
```

**Flujo resumido:**
1. El contrato se indexa en `contract_store` y se recuperan las cláusulas relevantes a la consulta del usuario.
2. La consulta también activa el `router`, que selecciona el índice correcto del `multi_index` (playbook / regulations / precedent) según keywords de intención.
3. El `reranker` retiene los 3 fragmentos de referencia más relevantes.
4. `logic.structured` combina las cláusulas del contrato y los fragmentos de referencia para producir los hallazgos clasificados.
5. `logic.citations` verifica que los fragmentos recuperados soporten las afirmaciones antes de emitir el informe.

---

## 4. Construirlo paso a paso

**Paso 1 — Nodo de entrada conversacional**
Añade `io.input` con `channel: chat` y `auth: jwt`. Este nodo determina el `deploymentTarget: chat-service` y emite un puerto `Message` que alimenta múltiples ramas del grafo.

**Paso 2 — Pipeline de ingesta del contrato bajo revisión**
Conecta `loader.pdf` → `ingest.chunker` (estrategia `by-clause`, para que cada cláusula sea un chunk autónomo) → `store.pgvector` (índice `contract`). Conecta `model.embedding` al mismo store. Añade `retrieval.vector` para recuperar las cláusulas relevantes a la pregunta del usuario.

**Paso 3 — Pipelines de la base de conocimiento (3 índices)**
Repite el mismo patrón `loader.pdf → ingest.chunker → store.pgvector` para cada fuente de referencia: `playbook`, `regulations` y `precedent`. Los tres stores comparten el mismo `model.embedding`. Conecta el puerto `Retriever` de cada store al nodo `store.multi-index`.

**Paso 4 — Multi-index y router**
Configura `store.multi-index` con `indexes: [playbook, regulations, precedent]`. Conecta su salida `Retriever` al `retrieval.router`. Configura el router con reglas de keyword-to-index (p.ej. "indemniz" → playbook, "regulacion" → regulations). Conecta el `Message` del chat al puerto `Query` del router.

**Paso 5 — Reranker**
Conecta la salida `Chunks` del router al `retrieval.reranker` con `topN: 3`. Esto descarta ruido y sube los fragmentos más relevantes.

**Paso 6 — LLM y hallazgos estructurados**
Añade `model.llm` y conecta su `Model` a `logic.structured`. Conecta los `Chunks` del reranker y los `Chunks` del `contract_retrieval` al mismo nodo. Define el esquema de hallazgos con campos `clausula`, `riesgo` (enum alto/medio/bajo), `explicacion` y `recomendacion`. Activa `requireCitations: true`.

**Paso 7 — Verificador de citas**
Añade `logic.citations` con `mode: enforce`. Conecta el `Message` del `chat_input` a su puerto `Message` y los `Chunks` del reranker a su puerto `Chunks`. Su salida `Message` va a `io.output`.

**Paso 8 — Salida**
Conecta tanto `structured_findings.Decision` como `citations_enforcer.Message` al `io.output` (puerto `Any`). Configura `format: markdown` y `streaming: true`.

---

## 5. Config de cada nodo (tabla)

| ID nodo | `type` | Config principal |
|---|---|---|
| `chat_input` | `io.input` | `channel: chat`, `auth: jwt`, `streaming: true` |
| `contract_pdf` | `loader.pdf` | `path: data/contracts/incoming`, `ocr: false` |
| `contract_chunker` | `ingest.chunker` | `strategy: by-clause`, `chunkSize: 900`, `overlap: 120` |
| `embedding_model` | `model.embedding` | `model: text-embedding-3-large`, `local: false`, `apiKeyRef: OPENAI_API_KEY` |
| `contract_store` | `store.pgvector` | `index: contract`, `distance: cosine` |
| `contract_retrieval` | `retrieval.vector` | `topK: 6`, `hardFilters: []` |
| `playbook_pdf` | `loader.pdf` | `path: data/kb/playbook`, `ocr: false` |
| `playbook_chunker` | `ingest.chunker` | `strategy: by-clause`, `chunkSize: 900`, `overlap: 120` |
| `playbook_store` | `store.pgvector` | `index: playbook`, `distance: cosine` |
| `regulations_pdf` | `loader.pdf` | `path: data/kb/regulations`, `ocr: false` |
| `regulations_chunker` | `ingest.chunker` | `strategy: by-clause`, `chunkSize: 900`, `overlap: 120` |
| `regulations_store` | `store.pgvector` | `index: regulations`, `distance: cosine` |
| `precedent_pdf` | `loader.pdf` | `path: data/kb/precedent`, `ocr: false` |
| `precedent_chunker` | `ingest.chunker` | `strategy: by-clause`, `chunkSize: 900`, `overlap: 120` |
| `precedent_store` | `store.pgvector` | `index: precedent`, `distance: cosine` |
| `multi_index` | `store.multi-index` | `indexes: [playbook, regulations, precedent]` |
| `router` | `retrieval.router` | `rules: [{keyword: indemniz, index: playbook}, {keyword: responsabilid, index: playbook}, {keyword: penalidad, index: playbook}, {keyword: regulacion, index: regulations}, {keyword: cumplimiento, index: regulations}, {keyword: normativa, index: regulations}, {keyword: precedente, index: precedent}, {keyword: contrato similar, index: precedent}]`, `fallback: playbook` |
| `reranker` | `retrieval.reranker` | `model: bge-reranker`, `topN: 3` |
| `llm` | `model.llm` | `model: anthropic:claude-opus-4-8`, `temperature: 0.1`, `apiKeyRef: ANTHROPIC_API_KEY` |
| `structured_findings` | `logic.structured` | `schema: {hallazgos[]: {clausula, riesgo: alto/medio/bajo, explicacion, recomendacion}}`, `requireCitations: true` |
| `citations_enforcer` | `logic.citations` | `mode: enforce` |
| `chat_output` | `io.output` | `format: markdown`, `streaming: true` |

---

## 6. Secretos (solo nombres)

| Nombre | Requerido | Usado por |
|---|---|---|
| `ANTHROPIC_API_KEY` | sí | `llm` |
| `OPENAI_API_KEY` | sí | `embedding_model` |
| `DATABASE_URL` | sí | `contract_store`, `playbook_store`, `regulations_store`, `precedent_store` |
| `JWT_PUBLIC_KEY` | sí | `chat_input` |

El codegen genera un `.env.template` con estos cuatro nombres. En modo mock (`MOCK=true`) solo `ANTHROPIC_API_KEY` es estrictamente necesario; los stores usan fixtures en memoria y los loaders usan PDFs de muestra.

---

## 7. Qué genera el codegen

Al ejecutar `ragorbit codegen flow.json`, el generador produce:

```
app/
  main.py                  # servidor FastAPI con SSE (chat-service)
  nodes/
    io_input.py            # recibe mensaje + JWT del abogado
    loader_pdf.py          # carga PDFs desde paths configurados
    ingest_chunker.py      # trocea por cláusula (by-clause)
    model_embedding.py     # client text-embedding-3-large
    store_pgvector.py      # upsert + query sobre pgvector
    retrieval_vector.py    # búsqueda por similitud
    store_multi_index.py   # dispatcher a stores nombrados
    retrieval_router.py    # selección por keyword rules[]
    retrieval_reranker.py  # bge-reranker, recorta a topN
    model_llm.py           # init_chat_model → Claude Opus 4.8
    logic_structured.py    # structured output con JSON Schema
    logic_citations.py     # enforce: rechaza sin cita
    io_output.py           # streaming SSE Markdown
  graph.py                 # grafo LangGraph con todos los nodos
mocks/
  loader_pdf_mock.py       # devuelve cláusulas de muestra
  store_pgvector_mock.py   # vector store en memoria
  retrieval_router_mock.py # devuelve chunks de playbook de muestra
  retrieval_reranker_mock.py
fixtures/
  contract_sample.pdf      # contrato ficticio con cláusula de indemnización
  playbook_sample.pdf      # playbook con cláusula de indemnización aprobada
  regulations_sample.pdf   # normativa de referencia
  precedent_sample.pdf     # contrato previo resuelto
tests/
  test_contract_review.py  # prueba end-to-end con fixtures
.env.template              # ANTHROPIC_API_KEY, OPENAI_API_KEY, DATABASE_URL, JWT_PUBLIC_KEY
docker-compose.yml         # app + postgres/pgvector
Dockerfile
```

**Puntos destacados del código generado:**

- `store_multi_index.py` instancia cada store nombrado y expone un método `get_retriever(index_name)` que el router invoca por nombre.
- `retrieval_router.py` implementa la lógica de matching de keywords en orden de declaración de `rules[]`; si ninguna regla hace match usa el `fallback`.
- `logic_structured.py` usa `init_chat_model` con `with_structured_output(schema)` para forzar el esquema JSON.
- `logic_citations.py` en modo `enforce` verifica que cada `explicacion` del array `hallazgos` contenga al menos una referencia (`[Playbook §X]`, `[Reg Art. Y]` o similar) y bloquea el stream si no la encuentra.

---

## 8. Probarlo con mocks

Con el artefacto generado, lanza el entorno de desarrollo completo:

```bash
# 1. Genera el artefacto (desde el directorio del ejemplo)
ragorbit codegen flow.json --out ./generated

# 2. Levanta en modo mock (sin backends reales)
cd generated
MOCK=true docker compose up
```

El servidor escucha en `http://localhost:8000`. Lanza la consulta de prueba con una cláusula de indemnización:

**Entrada (curl SSE):**
```bash
curl -N -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TEST_JWT" \
  -d '{
    "message": "Revisa la cláusula 12.3 de indemnización del contrato. ¿Hay riesgos frente a nuestro playbook?",
    "contract_ref": "contract_sample"
  }'
```

**Salida esperada (stream Markdown):**
```markdown
## Informe de revisión — Cláusula 12.3 Indemnización

| Cláusula | Riesgo | Explicación | Recomendación |
|---|---|---|---|
| §12.3 — Indemnización ilimitada del proveedor | **alto** | El contrato no establece techo de responsabilidad. El Playbook §4.2 exige límite máximo de 2× el valor anual del contrato. [Playbook §4.2] | Renegociar incluyendo cap de responsabilidad conforme a Playbook §4.2 |
| §12.3(b) — Exclusión de daños indirectos unilateral | **medio** | Solo el proveedor excluye daños indirectos; el cliente queda expuesto. Normativa Art. 18 prohíbe cláusulas asimétricas en contratos B2B de servicios esenciales. [Reg Art. 18] | Añadir reciprocidad o eliminar la exclusión unilateral |
| §12.3(c) — Plazo de notificación de 5 días | **bajo** | El playbook admite plazos desde 7 días; 5 días es más restrictivo pero no crítico. [Playbook §4.5] | Negociar a 7 días para alinearse con el estándar interno |

> Citas verificadas contra playbook y normativa. 3 hallazgos detectados: 1 alto, 1 medio, 1 bajo.
```

Para ver el comportamiento del verificador de citas cuando las fuentes no contienen evidencia suficiente:

```bash
curl -N -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TEST_JWT" \
  -d '{"message": "¿Hay riesgos en la cláusula 99.9 de confidencialidad cuántica?", "contract_ref": "contract_sample"}'
```

El sistema responderá con un error de citas:

```
[logic.citations enforce] No se encontraron fragmentos con citas suficientes para respaldar los hallazgos sobre §99.9. Reformula la consulta o verifica que el playbook contenga reglas para este tipo de cláusula.
```

---

## 9. Conceptos staff-level

**Multi-index con routing para reducir ruido y latencia**
Un único índice que mezcle playbook, normativa y precedentes produciría recuperaciones ruidosas: una consulta sobre indemnización podría traer fragmentos de normativa fiscal no relacionada. El `store.multi-index` + `retrieval.router` resuelven esto particionando la búsqueda: el router detecta la intención de la consulta (keyword matching sobre `rules[]`) y dirige la búsqueda únicamente al índice relevante. El efecto es doble — latencia menor (se consulta un solo store, no tres en paralelo) y precisión mayor (sin ruido cross-índice). El campo `fallback` garantiza que consultas genéricas siempre encuentren al menos el playbook.

**Citas duales: contrato + playbook/regulación**
Un informe de riesgo jurídico sin respaldo explícito en dos fuentes independientes no tiene valor práctico: el abogado necesita saber qué dice el contrato que se está revisando Y qué regla del playbook o artículo de normativa fundamenta el riesgo. `logic.citations` con `mode: enforce` obliga al grafo a producir únicamente hallazgos que citen ambas fuentes. Si el LLM alucina una cita que no aparece en los `Chunks` recuperados, el nodo bloquea el stream y devuelve error. Esto convierte el informe en un documento auditable, no en una opinión sin sustento.

**Niveles de riesgo como enum controlado**
Usar `enum: [alto, medio, bajo]` en el schema de `logic.structured` tiene consecuencias operativas concretas. Primero, el LLM no puede inventar categorías intermedias o formatos distintos. Segundo, el sistema downstream (dashboard legal, gestor de contratos) puede filtrar y ordenar hallazgos por nivel sin parseo adicional. Tercero, el campo `riesgo` puede alimentar en el futuro un `logic.rules` que auto-apruebe contratos sin hallazgos `alto` o escale a revisor humano los que sí los tengan.

**Reranker para precisión en fragmentos de referencia**
El router puede devolver hasta `topK` fragmentos por índice. Sin embargo, no todos los fragmentos del playbook sobre "indemnización" son igualmente relevantes para la cláusula específica bajo análisis. El `retrieval.reranker` con `topN: 3` aplica un modelo cross-encoder que evalúa la relevancia semántica entre la consulta y cada chunk de forma conjunta (a diferencia del embedding, que los codifica por separado). Esto reduce el contexto enviado al LLM a los 3 fragmentos más útiles, mejora la calidad de las citas y disminuye el costo de tokens.

**Versionado del playbook como práctica de ingeniería**
El playbook (`data/kb/playbook`) es un artifact versionado en git, igual que el código. Cuando el equipo legal actualiza una política (por ejemplo, eleva el cap de responsabilidad de 2× a 3× el valor anual), se hace un commit en el repositorio del playbook, se re-indexa `playbook_store` y todos los análisis futuros usan automáticamente la versión nueva. Los informes anteriores quedan trazados contra el hash del playbook vigente en el momento de la revisión. Esto es crucial en auditorías: "¿qué versión del playbook se usó para aprobar este contrato en marzo de 2025?" tiene respuesta precisa. El `index: playbook` en `store.pgvector` puede incluir metadata de versión para filtros duros que aislen revisiones históricas.

---

⬅️ [Índice](../../README.md)
