# 02 · Catálogo de nodos (el libro de bloques)

> Referencia de **todos** los tipos de nodo, agrupados por categoría. Cada entrada lista: **`type`**, qué hace, **puertos** (con [tipos de puerto](./01-concepts.md#42-tipos-de-dato-del-grafo-port-types)), **config** principal (con defaults), **secretos** y si trae **mock**. Los 10 ejemplos usan estos `type` exactos.

**Leyenda de puertos:** `→ Tipo` entrada · `Tipo →` salida · *(req)* requerido.

Índice de categorías: [io](#io--entradas-y-salidas) · [loaders](#loaders--fuentes-de-datos) · [ingestion](#ingestion--preparar-datos) · [store](#store--almacenamiento) · [retrieval](#retrieval--recuperación) · [model](#model--modelos) · [query](#query--operaciones-sobre-la-consulta) · [logic](#logic--razonamiento-y-reglas) · [agent](#agent--agentes) · [tool](#tool--herramientas-externas) · [guardrail](#guardrail--seguridad-y-resiliencia) · [hitl](#hitl--humano-en-el-loop) · [observability](#observability--auditoría-y-feedback)

---

## io · entradas y salidas

El **nodo de entrada** determina el [deployment target](./01-concepts.md#5-deployment-targets-cómo-se-despliega).

| `type` | Qué hace | Puertos | Config clave (default) | Mock |
|--------|----------|---------|------------------------|------|
| `io.input` | Entrada conversacional (chat o voz). ⇒ target `chat-service` | `Message →` | `channel: chat\|voice` (`chat`), `auth: none\|jwt\|booking-token` (`none`), `streaming` (`true`) | n/a |
| `io.stt` | Speech-to-Text streaming previo al chat (voz) | `→ Audio` · `Message →` | `provider: transcribe\|deepgram` (`deepgram`), `language` (`es`) | mock de transcript |
| `io.event-source` | Consume eventos de un stream. ⇒ target `event-worker` | `Event →` | `broker: kafka` (`kafka`), `topic` *(req)*, `partitionKey`, `exactlyOnce` (`true`) | emisor de eventos de muestra |
| `io.trigger` | Disparador durable. ⇒ target `temporal` | `Message →` | `schedule` (cron opcional), `idempotencyKey` | n/a |
| `io.batch` | Lote de archivos / cron. ⇒ target `batch` | `Documents →` | `source` *(req)*, `glob` (`**/*.pdf`) | archivos de muestra |
| `io.output` | Salida final al usuario/sistema | `→ Any` *(req)* | `format: text\|markdown\|json` (`markdown`), `streaming` (`true`) | n/a |
| `io.notify` | Notificación saliente (email/SMS/push) | `→ Any` *(req)* | `channels: [email,sms,push]` | mock que registra envíos |
| `io.panel` | Sugerencia a UI lateral (no interrumpe) — copilots | `→ Any` *(req)* | `cite: true` | n/a |

---

## loaders · fuentes de datos

Producen `Documents`. Todos traen **mock con fixtures** (datos de muestra) para correr sin la fuente real.

| `type` | Qué carga | Puertos | Config clave (default) | Secretos |
|--------|-----------|---------|------------------------|----------|
| `loader.pdf` | PDFs (texto) | `Documents →` | `path`/`bucket`, `ocr` (`false`) | — |
| `loader.multimodal` | PDFs con **tablas → JSON** y **diagramas → vision → texto**; preserva referencias cruzadas | `Documents →` | `extractTables` (`true`), `describeImages` (`true`), `sectionScheme` (p.ej. `ATA`) | — |
| `loader.tabular` | CSV/Parquet/Excel (p.ej. datos financieros) | `Documents →` | `path`, `schemaHint` | — |
| `loader.web` | Páginas/sitemaps | `Documents →` | `urls[]`, `crawlDepth` (`0`) | — |
| `loader.s3` | Objetos en S3/GCS | `Documents →` | `bucket` *(req)*, `prefix` | `STORAGE_KEY` |
| `loader.sql` | Filas de una BD como documentos | `Documents →` | `query` *(req)* | `DATABASE_URL` |

---

## ingestion · preparar datos

| `type` | Qué hace | Puertos | Config clave (default) |
|--------|----------|---------|------------------------|
| `ingest.chunker` | Trocea documentos. Estrategia consciente de estructura (cláusula/sección) | `→ Documents` *(req)* · `Documents →` | `strategy: recursive\|by-section\|by-clause` (`recursive`), `chunkSize` (`1000`), `overlap` (`150`) |
| `ingest.metadata` | Etiqueta metadata por chunk (para filtros duros) | `→ Documents` *(req)* · `Documents →` | `fields[]` (p.ej. `fare_class`, `aircraft_type`, `effective_date`) |

---

## store · almacenamiento

Consumen `Documents` + `Embeddings`, producen `Retriever`.

| `type` | Backend | Puertos | Config clave (default) | Secretos |
|--------|---------|---------|------------------------|----------|
| `store.pgvector` | Postgres + pgvector | `→ Documents` · `→ Embeddings` *(req)* · `Retriever →` | `index` *(req)*, `distance: cosine` | `DATABASE_URL` |
| `store.qdrant` | Qdrant | idem | `collection` *(req)* | `QDRANT_URL`, `QDRANT_API_KEY` |
| `store.chroma` | Chroma (local, ideal para demos) | idem | `collection` (`default`) | — |
| `store.neo4j` | **Knowledge Graph (GraphRAG)**: nodos entidad/chunk (`text`+`embedding`) y relaciones tipadas | `→ Documents` · `→ Embeddings` · `Retriever →` | `database` (`neo4j`), `entitySchema`, `buildRelations` (`true`) | `NEO4J_URI`, `NEO4J_AUTH` |
| `store.multi-index` | Agrupa varios índices nombrados para routing | `→ Retriever` (n) *(req)* · `Retriever →` | `indexes[]` *(req)* (p.ej. `policy`, `procedure`, `faq`) |

---

## retrieval · recuperación

Consumen `Retriever`/`Query`, producen `Chunks` (o un `Retriever` que el agente usa como tool).

| `type` | Qué hace | Puertos | Config clave (default) |
|--------|----------|---------|------------------------|
| `retrieval.vector` | Búsqueda por similitud | `→ Retriever` *(req)* · `→ Query` · `Chunks →` | `topK` (`4`), `hardFilters[]` (filtros duros = guardrail, p.ej. `fare_class`) |
| `retrieval.graph` | Recuperación sobre knowledge graph (vecindario, parent-child) | `→ Retriever` *(req)* · `→ Query` · `Chunks →` | `hops` (`1`), `pattern` |
| `retrieval.hybrid` | Vector + keyword (BM25) fusionados | `→ Retriever` *(req)* · `Chunks →` | `alpha` (`0.5`) |
| `retrieval.router` | **Multi-index routing**: elige índice por keyword/intent (ahorra latencia/ruido) | `→ Retriever` (multi-index) *(req)* · `→ Query` · `Chunks →` | `rules[]` (keyword→index), `fallback` |
| `retrieval.parent-child` | Devuelve el chunk padre para más contexto | `→ Retriever` *(req)* · `Chunks →` | `parentField` (`parent_id`) |
| `retrieval.reranker` | Reordena y recorta a top-N relevantes | `→ Chunks` *(req)* · `Chunks →` | `model` (`bge-reranker`), `topN` (`3`), `feedbackRef` (índice de feedback para fine-tune) |

---

## model · modelos

| `type` | Qué es | Puertos | Config clave (default) | Secretos |
|--------|--------|---------|------------------------|----------|
| `model.llm` | LLM vía interfaz estándar (`init_chat_model`) | `Model →` | `model` (`anthropic:claude-opus-4-8`), `temperature` (`0.2`), `apiKeyRef` (`ANTHROPIC_API_KEY`) | `ANTHROPIC_API_KEY` (u otra) |
| `model.embedding` | Modelo de embeddings | `Embeddings →` | `model` (`text-embedding-3-large`), `local` (`false`), `apiKeyRef` | según proveedor |
| `model.vision` | Modelo multimodal (describe imágenes/diagramas) | `Model →` | `model` (`anthropic:claude-opus-4-8`) | `ANTHROPIC_API_KEY` |
| `model.intent` | Clasificador ligero (compuerta del RAG; barato y rápido) | `→ Message` *(req)* · `Query →` | `labels[]` *(req)*, `backend: embeddings\|small-llm` (`embeddings`), `threshold` (`0.6`) |

> **Default Claude:** todos los nodos de modelo apuntan por defecto al Claude más reciente (Opus 4.8; alternativas Sonnet 4.6, Haiku 4.5) vía `init_chat_model`. Cambiar de proveedor es editar un campo — sin lock-in. Para precios/IDs exactos, ver la skill `claude-api`.

---

## query · operaciones sobre la consulta

| `type` | Qué hace | Puertos | Config clave (default) |
|--------|----------|---------|------------------------|
| `query.rewrite` | Normaliza jerga interna ("rebooking" → "cambio de vuelo"), expande la query | `→ Message` *(req)* · `Query →` | `glossaryRef`, `expand` (`true`) |
| `query.intent` | Detecta intención accionable; **no dispara el RAG** si no aplica (alias de `model.intent` orientado a routing) | `→ Message` *(req)* · `Query →` · `Decision →` | `labels[]` *(req)* |

---

## logic · razonamiento y reglas

| `type` | Qué hace | Puertos | Config clave (default) |
|--------|----------|---------|------------------------|
| `logic.prompt` | Síntesis con LLM a partir de chunks/contexto | `→ Model` *(req)* · `→ Chunks` · `→ Message` · `Message →` | `template` *(req)*, `system` |
| `logic.structured` | **Salida estructurada con esquema** (p.ej. criterio de crédito, veredicto). Puede exigir **citas obligatorias** | `→ Model` *(req)* · `→ Chunks` · `Decision →` | `schema` *(req, JSON Schema)*, `requireCitations` (`false`) |
| `logic.rules` | **Reglas deterministas** (auto-confirm, segmentación). Sin LLM | `→ Any` *(req)* · `Decision →` | `rules[]` *(req)* (when→then), `else` |
| `logic.router` | Bifurca el flujo según una condición/decisión | `→ Decision` *(req)* · `Any →` (n salidas nombradas) | `branches[]` *(req)* |
| `logic.citations` | Garantiza que cada afirmación cite su fuente; rechaza respuestas sin cita | `→ Message` *(req)* · `→ Chunks` *(req)* · `Message →` | `mode: enforce\|annotate` (`enforce`) |

---

## agent · agentes

| `type` | Qué hace | Puertos | Config clave (default) |
|--------|----------|---------|------------------------|
| `agent.react` | Orchestrator `create_agent` (ReAct): razona y llama tools en lenguaje natural | `→ Model` *(req)* · `→ Tool` (n) · `→ Retriever` (n) · `→ Message` · `Message →` | `system` *(req)*, `maxSteps` (`8`), `streaming` (`true`) |
| `agent.fanout` | Despacha N sub-agentes **stateless** en paralelo (por batch/partición) | `→ Event` *(req)* · `→ Tool` (n) · `Any →` | `concurrency` (`16`), `subAgentSystem` |

---

## tool · herramientas externas

Producen `Tool` para que un agente las invoque. **Todas traen mock con fixtures** ⇒ el agente funciona sin backends reales.

| `type` | Qué hace | Puertos | Config clave (default) | Secretos |
|--------|----------|---------|------------------------|----------|
| `tool.service` | Tool genérico hacia un servicio HTTP (declara operación + esquemas I/O) | `Tool →` | `name` *(req)*, `baseUrl` *(req)*, `operation` *(req)*, `inputSchema`, `outputSchema` | `SERVICE_API_KEY` |
| `tool.http` | Llamada HTTP simple parametrizada | `Tool →` | `method` (`GET`), `urlTemplate` *(req)* | opcional |
| `tool.function` | Función Python custom (snippet que tú pegas) | `Tool →` | `name` *(req)*, `signature`, `body` *(req)* | — |
| `tool.mcp` | Tool servida por un servidor MCP | `Tool →` | `server` *(req)*, `tool` *(req)* | según server |
| `tool.retriever` | Expone un `Retriever` como tool del agente (p.ej. PolicyRAG) | `→ Retriever` *(req)* · `Tool →` | `name` (`search`), `description` *(req)* |

---

## guardrail · seguridad y resiliencia

Se colocan **alrededor** de tools o antes de acciones. Envuelven el puerto `Tool` (entran `Tool`, salen `Tool`).

| `type` | Qué hace | Puertos | Config clave (default) |
|--------|----------|---------|------------------------|
| `guardrail.pre-tool` | Validación **antes** de ejecutar (límites de monto, no-downgrade de cabina) | `→ Tool` *(req)* · `Tool →` | `checks[]` *(req)* (when→deny/allow) |
| `guardrail.confirm` | Exige confirmación explícita si se supera un umbral | `→ Tool` *(req)* · `Tool →` | `threshold` (p.ej. `amount > 500`), `message` |
| `guardrail.idempotency` | Hace idempotente un tool transaccional (clave por `PNR+session`) | `→ Tool` *(req)* · `Tool →` | `keyFields[]` *(req)*, `ttl` (`24h`) |
| `guardrail.resilience` | Circuit breaker + retry + fallback ante servicio degradado | `→ Tool` *(req)* · `Tool →` | `retries` (`2`), `breakerThreshold` (`0.5`), `fallbackMessage` |

---

## hitl · humano en el loop

| `type` | Qué hace | Puertos | Config clave (default) |
|--------|----------|---------|------------------------|
| `hitl.escalate` | Interrumpe y escala a un humano (inspector/agente) en casos críticos | `→ Any` *(req)* · `Any →` (resume) | `when` *(req)* (condición, p.ej. severidad `WARNING`), `assignee`, `timeout` |

---

## observability · auditoría y feedback

| `type` | Qué hace | Puertos | Config clave (default) |
|--------|----------|---------|------------------------|
| `observability.audit` | Persiste cada tool call + respuesta (Kafka/log) — trazabilidad regulatoria | `→ Any` *(req)* · `Any →` (passthrough) | `sink: kafka\|log` (`log`), `topic` |
| `observability.feedback` | **Feedback loop**: ingiere callbacks de transacción y labels útil/no-útil → store para métricas y fine-tune del reranker | `→ Any` *(req)* · `Any →` | `store` *(req)*, `signals[]` (`thumbs`, `txn_callback`) |
| `observability.metrics` | Exporta métricas (OpenTelemetry): throughput, auto-confirm vs. escalado, latencia | `→ Any` *(req)* · `Any →` | `exporter: otlp` (`otlp`) |

---

## Cobertura

Los 10 ejemplos, en conjunto, usan al menos un nodo de **cada** categoría. Mapa rápido:

| Categoría | Ejemplos que la ejercitan |
|-----------|----------------------------|
| io (chat/voz/event/batch) | 1,2,3,4,5,6,7,8,9,10 |
| loaders (incl. multimodal) | 2,3,4,5,8,9 |
| store (incl. neo4j, multi-index) | 2,3,5,7,8,9 |
| retrieval (router, reranker, graph) | 5,7,8 |
| model (llm, vision, intent) | todos / 4,8 / 7 |
| query (rewrite, intent) | 7 |
| logic (structured, rules, citations, router) | 2,3,4,8,10 |
| agent (react, fanout) | 1,6 / 10 |
| tool (service, retriever, function) | 1,3,6,10 |
| guardrail (pre-tool, confirm, idempotency, resilience) | 1,6 |
| hitl | 3,8 |
| observability (audit, feedback, metrics) | 1,7,10 |

➡️ Siguiente: [03 · Construye tu primer flujo](./03-build-first-flow.md).
