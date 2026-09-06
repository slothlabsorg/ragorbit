# 08 · RAG sobre Manuales de Mantenimiento Aeronáutico (AMM)

> **Industria:** Manufactura aeronáutica / MRO (Maintenance, Repair & Overhaul)
> **Deployment target:** `chat-service`

---

## 1. Problema, industria y a quién sirve

Los técnicos de mantenimiento aeronáutico trabajan con el **Aircraft Maintenance Manual (AMM)** de Boeing y Airbus: documentos de miles de páginas organizados por capítulos ATA (Air Transport Association), que contienen procedimientos paso a paso, tablas de tolerancias y diagramas técnicos.

**El problema:** buscar un procedimiento implica navegar manualmente capítulos ATA, cruzar tablas de torque, leer diagramas hidráulicos y verificar la revisión vigente. Un error de referencia (citar el capítulo equivocado o la revisión incorrecta) puede constituir un hallazgo de auditoría FAA/EASA o, peor, un incidente de seguridad.

**A quién sirve:**

- Técnicos de línea (Line Maintenance) que consultan procedimientos en rampa.
- Inspectores de base (Base Maintenance) que verifican límites y tolerancias.
- Coordinadores de MRO que necesitan trazabilidad documental por número de revisión.

El sistema responde en lenguaje natural, cita la sección exacta del AMM y **nunca** da una respuesta sin referencia. Si el procedimiento involucra una advertencia CAUTION o WARNING, escala a un inspector certificado antes de responder de forma autónoma.

---

## 2. Resultado esperado

- El técnico escribe una consulta en lenguaje natural: _"¿Cuál es el procedimiento de inspección del tren de aterrizaje principal en la sección 32-11-00 del A320?"_
- El sistema recupera los fragmentos relevantes del AMM del A320 (y **solo** del A320), sintetiza la respuesta y la entrega citando capítulo ATA, número de sección y revisión del manual.
- Si la respuesta contiene un aviso CAUTION o WARNING, el flujo **interrumpe** la respuesta autónoma y abre una tarea para un inspector certificado, que recibe el contexto completo para aprobar o complementar la respuesta.
- Ninguna respuesta pasa al técnico sin cita verificable; el nodo `logic.citations` rechaza respuestas sin anclaje documental.

---

## 3. Arquitectura (ASCII con puertos)

```
                 ┌─────────────────────────────────── PIPELINE DE INGESTA ──────────────────────────────────────┐
                 │                                                                                                │
[vision_model]   │                                                                                                │
  model.vision   │                                                                                                │
  model ──────▶  │  [amm_loader]        [chunker]          [metadata_amm]       [pgvector_amm]                  │
                 │  loader.multimodal   ingest.chunker      ingest.metadata      store.pgvector                  │
                 │  documents ────▶ documents ────▶ documents ────▶ documents ──▶         ◀── embeddings         │
                 │                                                                retriever ──▶                  │
                 │                                                          [embedding_model]                    │
                 │                                                           model.embedding                     │
                 └────────────────────────────────────────────────────────────────────────────────────────────── ┘

[chat_input]                                              [amm_retrieval]
io.input         message ─────────────────────────────▶  retrieval.vector  (hardFilters: aircraft_type, ata_chapter)
                              ◀── retriever ─── pgvector_amm                chunks ──▶ [prompt_amm]
                                                                                        logic.prompt
[llm]                                                     message ─────────────────▶   (template + system)
model.llm        model ────────────────────────────────────────────────────────────▶
                                                                                        message ──▶ [citations_check]
                                                          chunks ─────────────────────▶ logic.citations (enforce)
                                                                                         ↓ message
                                                                                   [escalate_inspector]
                                                                                    hitl.escalate
                                                                                    (when: WARNING|CAUTION)
                                                                                         ↓ any
                                                                                   [chat_output]
                                                                                    io.output (markdown)
```

**Puertos clave:**

| Arista | Puerto origen | Puerto destino | Tipo |
|--------|--------------|----------------|------|
| `amm_loader` → `chunker` | `documents` | `documents` | `Documents` |
| `chunker` → `metadata_amm` | `documents` | `documents` | `Documents` |
| `metadata_amm` → `pgvector_amm` | `documents` | `documents` | `Documents` |
| `embedding_model` → `pgvector_amm` | `embeddings` | `embeddings` | `Embeddings` |
| `vision_model` → `amm_loader` | `model` | `any` | `Model` |
| `pgvector_amm` → `amm_retrieval` | `retriever` | `retriever` | `Retriever` |
| `chat_input` → `amm_retrieval` | `message` | `query` | `Message` |
| `amm_retrieval` → `prompt_amm` | `chunks` | `chunks` | `Chunks` |
| `chat_input` → `prompt_amm` | `message` | `message` | `Message` |
| `llm` → `prompt_amm` | `model` | `model` | `Model` |
| `prompt_amm` → `citations_check` | `message` | `message` | `Message` |
| `amm_retrieval` → `citations_check` | `chunks` | `chunks` | `Chunks` |
| `citations_check` → `escalate_inspector` | `message` | `any` | `Message` |
| `escalate_inspector` → `chat_output` | `any` | `any` | `Any` |

---

## 4. Construirlo paso a paso

**Paso 1 — Cargar los AMMs**

Apunta `amm_loader` a la carpeta (o bucket S3) donde residen los PDFs del AMM. Configura `sectionScheme: ATA` para que el loader respete la numeración de capítulos (por ejemplo, 32 = Landing Gear). El loader extrae las tablas como JSON estructurado y envía los diagramas al `vision_model` para obtener descripciones en texto antes de indexarlos.

**Paso 2 — Pipeline de ingesta**

Los documentos fluyen por `chunker` (estrategia `by-section`, respeta la estructura ATA sin partir secciones a la mitad) y luego por `metadata_amm`, que etiqueta cada chunk con `ata_chapter`, `aircraft_type`, `document`, `content_type` y `revision_date`. Estos campos son los que `amm_retrieval` usará como filtros duros.

**Paso 3 — Indexar en pgvector**

`pgvector_amm` recibe los documentos etiquetados y los vectores de `embedding_model`. Crea el índice llamado `amm` con distancia coseno.

**Paso 4 — Configurar la recuperación con filtros duros**

`amm_retrieval` tiene `hardFilters: ["aircraft_type", "ata_chapter"]`. En tiempo de consulta, el sistema extrae del contexto de sesión el tipo de aeronave (A320, 787, etc.) y el capítulo ATA indicado por el técnico y los aplica como filtros obligatorios antes de buscar por similitud. Un técnico que trabaja en un A320 nunca verá resultados del 787.

**Paso 5 — Síntesis con cita obligatoria**

`prompt_amm` (tipo `logic.prompt`) combina el LLM, los chunks recuperados y la consulta del técnico. El template instrucye al modelo a indicar siempre capítulo ATA, número de sección, revisión del manual y cualquier aviso CAUTION/WARNING textual.

**Paso 6 — Verificación de citas**

`citations_check` (modo `enforce`) verifica que la respuesta generada ancle cada afirmación en un chunk recuperado. Si no hay cita, rechaza la respuesta y el flujo genera un error accionable en lugar de pasar una alucinación al técnico.

**Paso 7 — Escalación HITL en CAUTION/WARNING**

`escalate_inspector` evalúa la condición `nivel == 'WARNING' OR nivel == 'CAUTION'`. Si es verdadera, abre una tarea asignada a `certified-inspector` con timeout de 2 horas. El inspector recibe el contexto completo (query + chunks + respuesta propuesta) y puede aprobar, modificar o rechazar antes de que llegue al técnico.

**Paso 8 — Salida**

`chat_output` formatea la respuesta final en Markdown con las citas resaltadas.

---

## 5. Config de cada nodo (tabla)

| Nodo | `type` | Config principal |
|------|--------|-----------------|
| `chat_input` | `io.input` | `channel: chat`, `auth: jwt`, `streaming: true` |
| `amm_loader` | `loader.multimodal` | `extractTables: true`, `describeImages: true`, `sectionScheme: ATA` |
| `vision_model` | `model.vision` | `model: anthropic:claude-opus-4-8`, `apiKeyRef: ANTHROPIC_API_KEY` |
| `chunker` | `ingest.chunker` | `strategy: by-section`, `chunkSize: 900`, `overlap: 120` |
| `metadata_amm` | `ingest.metadata` | `fields: [ata_chapter, aircraft_type, document, content_type, revision_date]` |
| `embedding_model` | `model.embedding` | `model: text-embedding-3-large`, `local: false`, `apiKeyRef: OPENAI_API_KEY` |
| `pgvector_amm` | `store.pgvector` | `index: amm`, `distance: cosine` |
| `amm_retrieval` | `retrieval.vector` | `topK: 5`, `hardFilters: [aircraft_type, ata_chapter]` |
| `llm` | `model.llm` | `model: anthropic:claude-opus-4-8`, `temperature: 0.1`, `apiKeyRef: ANTHROPIC_API_KEY` |
| `prompt_amm` | `logic.prompt` | `template`: instrucción de síntesis AMM con cita obligatoria y detección CAUTION/WARNING |
| `citations_check` | `logic.citations` | `mode: enforce` |
| `escalate_inspector` | `hitl.escalate` | `when: nivel == 'WARNING' OR nivel == 'CAUTION'`, `assignee: certified-inspector`, `timeout: 2h` |
| `chat_output` | `io.output` | `format: markdown`, `streaming: true` |

---

## 6. Secretos (solo nombres)

```
ANTHROPIC_API_KEY   # llm + vision_model
OPENAI_API_KEY      # embedding_model
DATABASE_URL        # pgvector_amm
JWT_PUBLIC_KEY      # chat_input (auth jwt)
```

Estos nombres son los únicos que aparecen en `flow.json`. Los valores se inyectan en deploy como variables de entorno; en modo mock no son necesarios.

---

## 7. Qué genera el codegen

Al ejecutar `ragorbit codegen flow.json` sobre este flujo, el generador produce:

```
app/
  main.py                  # FastAPI con endpoint /chat (SSE streaming)
  graph.py                 # Grafo LangGraph: nodos loader → chunker → metadata → store
                           #   y rama de consulta: input → retrieval → prompt → citations → hitl → output
  nodes/
    amm_loader.py          # LangChain multimodal loader con sectionScheme=ATA
    vision_model.py        # Cliente Claude Opus 4.8 para descripción de imágenes
    chunker.py             # RecursiveCharacterTextSplitter with by-section strategy
    metadata_amm.py        # Tagger de metadata: ata_chapter, aircraft_type, etc.
    embedding_model.py     # OpenAIEmbeddings text-embedding-3-large
    pgvector_amm.py        # PGVector store, index=amm, distance=cosine
    amm_retrieval.py       # Similarity search con hard_filter por aircraft_type y ata_chapter
    llm.py                 # init_chat_model("anthropic:claude-opus-4-8")
    prompt_amm.py          # LLMChain con template de síntesis AMM
    citations_check.py     # Verificador enforce: rechaza si no hay cita a chunk fuente
    escalate_inspector.py  # Interrupt node: pausa el grafo y crea tarea HITL si WARNING|CAUTION
    chat_output.py         # StreamingResponse SSE → cliente
mocks/
  amm_loader_mock.py       # Devuelve fixtures/amm_sample.json con secciones ATA de muestra
  vision_model_mock.py     # Devuelve descripción textual fija de diagrama hidráulico
  pgvector_mock.py         # Store en memoria (dict) con los mismos fixtures
  escalate_mock.py         # Registra la escalación en escalations.log sin llamar a sistema externo
tests/
  test_normal_query.py     # Consulta sin WARNING → respuesta con cita
  test_warning_escalation.py  # Consulta con WARNING → escalación HITL
  test_citation_enforce.py    # Respuesta sin cita → rechazada
Dockerfile
docker-compose.yml         # Incluye Postgres+pgvector
.env.template              # ANTHROPIC_API_KEY=, OPENAI_API_KEY=, DATABASE_URL=, JWT_PUBLIC_KEY=
```

El proyecto arranca sin servicios externos con `MOCK=true docker compose up`.

---

## 8. Probarlo con mocks

**Arranque:**

```bash
cd examples/08-manufacturing-maintenance-rag
MOCK=true docker compose up
# API disponible en http://localhost:8000
```

**Caso A — Consulta de procedimiento estándar (sin advertencia)**

Entrada:

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <jwt-mock>" \
  -d '{
    "message": "¿Cuál es el procedimiento de inspección del tren de aterrizaje en la sección 32-11-00 del A320?",
    "session": {
      "aircraft_type": "A320",
      "ata_chapter": "32"
    }
  }'
```

Salida esperada (Markdown, streaming):

```
**Procedimiento: Inspección del tren de aterrizaje principal — A320**

Según el AMM A320, **Capítulo 32 (Landing Gear)**, Sección **32-11-00**,
Revisión **Rev. 47 (2024-03)**, el procedimiento es:

1. Coloca la aeronave en jack de mantenimiento conforme a la Task 07-11-00-581-001.
2. Verifica el juego lateral del pivote siguiendo los límites de la Tabla 32-11-00-991-001
   (tolerancia máxima: 0,35 mm).
3. Inspecciona visualmente la estructura del oleopneumático por fisuras o corrosión
   (ref. Fig. 32-11-00-991-010).
4. Registra los resultados en el formulario AMM-32-INSP-001.

> **Fuente:** AMM A320, Sección 32-11-00, Rev. 47 (2024-03), Tabla 32-11-00-991-001.
```

No se detecta CAUTION ni WARNING → la respuesta llega directamente al técnico.

---

**Caso B — Consulta que toca un WARNING**

Entrada:

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <jwt-mock>" \
  -d '{
    "message": "¿Cómo se retira el actuador hidráulico del tren de morro en la sección 32-21-11?",
    "session": {
      "aircraft_type": "A320",
      "ata_chapter": "32"
    }
  }'
```

Salida esperada — el flujo detecta WARNING y escala:

```
⚠️  Esta consulta ha sido remitida a un inspector certificado.

El procedimiento AMM A320, Sección 32-21-11 (Retiro del actuador hidráulico
del tren de morro) contiene la siguiente advertencia:

**WARNING:** Despresuriza el sistema hidráulico (sistema verde a 0 bar)
antes de desconectar cualquier línea hidráulica. La presión residual puede
provocar lesiones graves.

Un inspector certificado revisará esta consulta antes de que recibas la
respuesta completa. Tiempo estimado de respuesta: ≤ 2 horas.
Referencia de escalación: ESC-2024-0847.
```

El grafo se detiene en `escalate_inspector`; el inspector recibe la query, los chunks recuperados y la respuesta propuesta para aprobar o complementar.

---

**Caso C — Verificación de citas (forzar fallo)**

```bash
# Deshabilitar temporalmente el mock del loader para simular chunks vacíos
MOCK=true EMPTY_CHUNKS=true docker compose up
curl -X POST http://localhost:8000/chat \
  -d '{"message": "procedimiento sección 32-11-00", "session": {"aircraft_type": "A320", "ata_chapter": "32"}}'
```

Salida esperada (error accionable del nodo `logic.citations`):

```json
{
  "error": "citations_required",
  "message": "No se encontraron fragmentos del AMM que respalden la respuesta generada. No se entrega la respuesta. Verifica que el manual A320 esté indexado para el capítulo ATA 32."
}
```

---

## 9. Conceptos staff-level

**Filtros duros como guardrail de seguridad aeronáutica**

Los campos `aircraft_type` y `ata_chapter` en `retrieval.vector` son `hardFilters`, no sugerencias de ranking. Esto significa que la consulta SQL/vectorial al índice `amm` lleva una cláusula `WHERE aircraft_type = 'A320' AND ata_chapter = '32'` antes de calcular similitud. Un técnico de A320 nunca puede recibir un límite de torque del 787 aunque el embedding sea similar: la norma de mantenimiento exige trazabilidad de fabricante/modelo. Este patrón es análogo a los `fare_class` del ejemplo 01, pero aquí la consecuencia de un cruce no es un mal cobro sino un procedimiento incorrecto en una aeronave.

**Citas obligatorias como control de riesgo real**

`logic.citations` en modo `enforce` no es una preferencia estética: si el LLM no puede anclar una afirmación en un chunk del AMM recuperado, la respuesta no sale. La alucinación en mantenimiento aeronáutico tiene consecuencias regulatorias (auditoría PART-145) y de seguridad. El nodo actúa como última línea antes de la salida: la única forma de pasar es que cada afirmación tenga una fuente verificable del documento técnico certificado.

**HITL en CAUTION/WARNING hardcodeado, no decidido por el LLM**

La condición `when: nivel == 'WARNING' OR nivel == 'CAUTION'` en `hitl.escalate` es **determinista**: el modelo extrae el nivel de la respuesta como campo estructurado y la condición la evalúa el motor del grafo, no el LLM. Esto es intencional. Dejar que el modelo decida si un procedimiento es "suficientemente peligroso para escalar" abre la puerta a alucinaciones de confianza. La regla es: si el AMM dice WARNING o CAUTION, siempre escala. Sin excepciones. Es el mismo principio que los guardrails de herramientas en otros ejemplos del libro: las decisiones con consecuencias irreversibles son deterministas.

**Parsing multimodal con sectionScheme ATA**

`loader.multimodal` con `sectionScheme: ATA` no es un simple extractor de texto: preserva la jerarquía ATA (Chapter-Section-Subject, p.ej. 32-11-00), convierte tablas de tolerancias en JSON estructurado (navegables por filtro) y envía cada figura al `model.vision` para obtener una descripción textual antes de indexar. El resultado es que un diagrama hidráulico es recuperable semánticamente por su descripción, no solo por el texto adyacente. Este parsing de doble carril (texto estructurado + visión) es lo que diferencia el caso de uso de un RAG de PDF simple: los manuales de mantenimiento son intensivos en tablas y diagramas.

**Versionado por revisión del manual**

El campo `revision_date` en `ingest.metadata` permite filtrar o ponderar por revisión del manual. En operaciones reales, una aerolínea puede tener el AMM Rev. 47 en producción pero estar evaluando la Rev. 48. El sistema puede configurarse para recuperar solo la revisión vigente (filtro duro) o para mostrar ambas y dejar al inspector comparar (filtro blando). La trazabilidad por `revision_date` es también un requisito de auditoría: cualquier respuesta entregada al técnico debe poder reproducirse con la misma revisión del documento en caso de inspección regulatoria.

---

⬅️ [Índice](../../README.md)
