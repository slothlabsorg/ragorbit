# 03 · Asistente de pre-autorización clínica

**Industria:** Salud — pagadores (aseguradoras) y hospitales  
**Deployment target:** `chat-service`

---

## 1. Problema, industria y a quién sirve

Las aseguradoras exigen **pre-autorización** antes de aprobar procedimientos costosos (cirugías, imágenes diagnósticas, medicamentos de alto costo). Hoy ese proceso es manual: un agente de autorización busca en PDF de guías clínicas, llama al sistema de historia del paciente, verifica criterios y escala a un médico revisor cuando hay dudas. El ciclo tarda horas o días, genera errores por mezcla de criterios de planes distintos, y en casos urgentes la demora puede comprometer la atención.

**A quién sirve este flujo:**

- **Agentes de autorización** de aseguradoras que procesan decenas de solicitudes diarias.
- **Hospitales y clínicas** que envían solicitudes al pagador y necesitan respuesta inmediata con criterio documentado.
- **Revisores clínicos certificados** que reciben solo los casos que realmente requieren juicio humano, no todo el volumen.

El flujo no reemplaza al médico revisor: lo libera para los casos que importan.

---

## 2. Resultado esperado

Para una solicitud de pre-autorización (p.ej. "Resonancia magnética de rodilla para paciente con plan PPO-Gold, diagnóstico M23.2 — lesión de menisco"), el asistente:

1. Recupera la historia clínica del paciente (diagnósticos activos, plan, autorizaciones previas).
2. Consulta las guías clínicas del pagador **filtradas por el plan y la condición exacta** del paciente.
3. Emite una decisión (aprobado / rechazado / escalado) **con cita explícita** de la sección de la guía que respalda cada afirmación.
4. Si el caso es crítico, urgente o no existe criterio claro en la guía, interrumpe el flujo y lo asigna a un revisor clínico certificado con un plazo de 4 horas.

El solicitante recibe una respuesta en Markdown con la decisión, el fundamento y las referencias. El revisor humano recibe los casos escalados con todo el contexto ya armado.

---

## 3. Arquitectura (ASCII con puertos)

```
                              ┌─────────────────────────────────────────────────────────────────┐
                              │                PIPELINE DE INGESTA (offline)                    │
                              │                                                                 │
  [loader.pdf]                │  documents→  [ingest.chunker]  documents→  [ingest.metadata]   │
  path: data/clinical_        │              strategy:                fields:                  │
  guidelines                  │              by-section               [plan, condition,         │
        │ documents            │                                       effective_date]           │
        └──────────────────── ─┘                                           │ documents
                                                                           ▼
                                             [model.embedding] ─embeddings→ [store.pgvector]
                                             text-embedding-3-large         index: clinical_
                                                                            guidelines
                                                                                │ retriever
                                                                                ▼
                                                                      [retrieval.vector]
                                                                      topK: 5
                                                                      hardFilters:
                                                                      [plan, condition]
                                                                                │ chunks
                                                                                ▼
                                                                      [tool.retriever]
                                                                      "GuidelinesRAG"
                                                                                │ tool
                                                                                │
┌──────────────┐  message    ┌──────────────────────────────┐  ◄──────────────┘
│  io.input    │ ──────────► │       agent.react            │
│  channel:chat│             │   "Agente Pre-Autorización"  │ ◄── tool ── [tool.service]
│  auth: jwt   │             │   maxSteps: 10               │             "PatientHistoryService"
└──────────────┘             └──────────────────────────────┘
                                          │ message (loop: ReAct)
                                          ▼
                             ┌────────────────────────┐
                [model.llm] ─┤   logic.citations      │
                model →      │   mode: enforce        │
                             └────────────────────────┘
                                          │ message
                                          ▼
                             ┌────────────────────────┐
                             │    hitl.escalate       │
                             │  when: severidad==alta │
                             │  assignee: clinical-   │
                             │  reviewer              │
                             │  timeout: 4h           │
                             └────────────────────────┘
                                          │ any
                                          ▼
                             ┌────────────────────────┐
                             │     io.output          │
                             │  format: markdown      │
                             └────────────────────────┘
```

**Puertos clave:**
- `io.input → message` entra en `agent.react → message`
- `model.llm → model` entra en `agent.react → model`
- `tool.retriever → tool` y `tool.service → tool` entran en `agent.react → tools`
- `agent.react → message` sale a `logic.citations → message`
- `logic.citations → message` sale a `hitl.escalate → any`
- `hitl.escalate → any` sale a `io.output → any`

---

## 4. Construirlo paso a paso

1. **Crear el nodo de entrada.** Arrastra `io.input` al lienzo, configura `channel: chat` y `auth: jwt`. RAGorbit fija automáticamente `deploymentTarget: chat-service`.

2. **Agregar el LLM.** Arrastra `model.llm`, elige `anthropic:claude-opus-4-8`, temperatura `0.1` (baja para decisiones médicas deterministas). Conecta `model →` al agente en el paso 6.

3. **Construir el pipeline de ingesta de guías clínicas.** Arrastra `loader.pdf` apuntando a `data/clinical_guidelines`. Conecta `documents →` a `ingest.chunker` (`by-section`, chunkSize 800). Conecta la salida al `ingest.metadata` con campos `[plan, condition, effective_date]`.

4. **Configurar el store vectorial.** Arrastra `model.embedding` (text-embedding-3-large). Arrastra `store.pgvector` con `index: clinical_guidelines`. Conecta `ingest.metadata → documents` y `model.embedding → embeddings` al store. El store produce un `retriever`.

5. **Crear el retriever con filtros duros.** Conecta `store.pgvector → retriever` a `retrieval.vector`. Configura `hardFilters: [plan, condition]`. Esta es la clave de seguridad: ningún chunk de un plan ajeno puede colarse en la respuesta.

6. **Exponer el retriever como tool del agente.** Arrastra `tool.retriever`, nómbralo `GuidelinesRAG`, escribe una descripción clara de cuándo usarlo. Conecta `retrieval.vector → chunks` al `tool.retriever → retriever`. La salida `tool →` va al agente.

7. **Agregar el servicio de historia del paciente.** Arrastra `tool.service`, configura nombre `PatientHistoryService`, `baseUrl`, operación `getPatientHistory` y los schemas I/O. Conecta `tool →` al agente.

8. **Configurar el agente ReAct.** Arrastra `agent.react`. Redacta el `system` prompt con instrucciones explícitas: consultar historia, filtrar por plan+condición, citar siempre, señalar severidad alta si el caso es ambiguo. Conecta `io.input → message`, `model.llm → model`, y los dos tools al agente.

9. **Forzar citas obligatorias.** Arrastra `logic.citations`, modo `enforce`. Conecta `agent.react → message` a `citations_check`. Si la respuesta llega sin cita, el nodo la rechaza antes de que salga al usuario.

10. **Configurar la escalación humana.** Arrastra `hitl.escalate`, condición `severidad == 'alta' OR criterio_no_encontrado == true`, `assignee: clinical-reviewer`, `timeout: 4h`. Conecta `logic.citations → message` a la entrada `any` del escalador.

11. **Agregar la salida.** Arrastra `io.output`, formato `markdown`. Conecta `hitl.escalate → any` a la entrada `any` de la salida.

12. **Declarar secretos.** RAGorbit detecta los secretos referenciados y los lista. Verifica que `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `DATABASE_URL`, `SERVICE_API_KEY` y `JWT_PUBLIC_KEY` estén en `secrets[]`.

13. **Generar y levantar.** Haz clic en **Generate** → `docker compose up`. El agente funciona desde el primer minuto con mocks: historia de paciente simulada y chunks de guía de muestra.

---

## 5. Config de cada nodo (tabla)

| ID | `type` | Config destacada |
|----|--------|-----------------|
| `chat_input` | `io.input` | `channel: chat`, `auth: jwt`, `streaming: true` |
| `llm` | `model.llm` | `model: anthropic:claude-opus-4-8`, `temperature: 0.1`, `apiKeyRef: ANTHROPIC_API_KEY` |
| `pdf_guidelines` | `loader.pdf` | `path: data/clinical_guidelines`, `ocr: false` |
| `chunker` | `ingest.chunker` | `strategy: by-section`, `chunkSize: 800`, `overlap: 120` |
| `metadata_tagger` | `ingest.metadata` | `fields: [plan, condition, effective_date]` |
| `embedding_model` | `model.embedding` | `model: text-embedding-3-large`, `apiKeyRef: OPENAI_API_KEY` |
| `pgvector_store` | `store.pgvector` | `index: clinical_guidelines`, `distance: cosine` |
| `guidelines_retrieval` | `retrieval.vector` | `topK: 5`, `hardFilters: [plan, condition]` |
| `guidelines_rag_tool` | `tool.retriever` | `name: GuidelinesRAG`, `description: (criterios de pre-autorización por plan y condición)` |
| `patient_history_tool` | `tool.service` | `name: PatientHistoryService`, `baseUrl: https://ehr.internal/api/v1`, `operation: getPatientHistory` |
| `prior_auth_agent` | `agent.react` | `system: (ver flow.json)`, `maxSteps: 10`, `streaming: true` |
| `citations_check` | `logic.citations` | `mode: enforce` |
| `escalate_human` | `hitl.escalate` | `when: severidad=='alta' OR criterio_no_encontrado==true`, `assignee: clinical-reviewer`, `timeout: 4h` |
| `chat_output` | `io.output` | `format: markdown`, `streaming: true` |

---

## 6. Secretos (solo nombres)

```
ANTHROPIC_API_KEY   — LLM principal (agent.react vía model.llm)
OPENAI_API_KEY      — Embeddings (model.embedding)
DATABASE_URL        — PostgreSQL + pgvector (store.pgvector)
SERVICE_API_KEY     — EHR / historia del paciente (tool.service)
JWT_PUBLIC_KEY      — Validación de token del chat (io.input)
```

El Flow IR almacena **solo estos nombres**. Los valores viven en el gestor de secretos y se inyectan en deploy como variables de entorno. El archivo `.env.template` generado lista exactamente estos cinco nombres.

---

## 7. Qué genera el codegen

A partir del `flow.json`, RAGorbit emite un proyecto Python listo para ejecutar:

```
app/
  main.py                   # FastAPI con SSE/WebSocket (chat-service)
  graph.py                  # LangGraph: nodos y edges compilados
  nodes/
    chat_input.py           # io.input → valida JWT, recibe mensaje
    llm.py                  # model.llm → init_chat_model("anthropic:claude-opus-4-8")
    pdf_guidelines.py       # loader.pdf → PyMuPDF
    chunker.py              # ingest.chunker → RecursiveCharacterTextSplitter by-section
    metadata_tagger.py      # ingest.metadata → DocumentTransformer
    embedding_model.py      # model.embedding → OpenAIEmbeddings
    pgvector_store.py       # store.pgvector → PGVector
    guidelines_retrieval.py # retrieval.vector → hardFilters aplicados en metadata_filter
    guidelines_rag_tool.py  # tool.retriever → create_retriever_tool
    patient_history_tool.py # tool.service → StructuredTool con httpx
    prior_auth_agent.py     # agent.react → create_react_agent(llm, tools, system)
    citations_check.py      # logic.citations → post-processor enforce
    escalate_human.py       # hitl.escalate → interrupt() + assignee notification
    chat_output.py          # io.output → StreamingResponse markdown
mocks/
  patient_history_mock.py   # devuelve historia ficticia por patient_id
  guidelines_mock.py        # devuelve chunks de guía de muestra (plan: PPO-Gold)
  fixtures/
    patient_001.json        # historia de paciente de prueba
    guideline_mri_knee.txt  # criterios de RM de rodilla (muestra)
tests/
  test_prior_auth_flow.py   # test de integración completo con mocks
  test_citations_enforce.py # verifica que respuestas sin cita son rechazadas
  test_escalation.py        # verifica que severidad alta dispara hitl.escalate
Dockerfile
docker-compose.yml          # incluye postgres + pgvector
.env.template               # ANTHROPIC_API_KEY=, OPENAI_API_KEY=, DATABASE_URL=, ...
```

El codegen respeta las dos plantillas por nodo (real + mock): `MOCK=true` levanta el sistema completo sin ningún backend real.

---

## 8. Probarlo con mocks

### Levantar el entorno

```bash
# Generar el proyecto (desde la UI de RAGorbit o CLI)
ragorbit generate flow.json --out ./output

# Levantar con mocks activados
cd output
MOCK=true docker compose up
# → API disponible en http://localhost:8000
```

### Caso 1 — Aprobación con cita (camino feliz)

**Entrada:**
```json
{
  "message": "Solicito pre-autorización para resonancia magnética de rodilla derecha. Paciente: P-10042. Diagnóstico: M23.2 (lesión de menisco). Plan: PPO-Gold.",
  "session_id": "session-demo-001"
}
```

**Traza del agente (logs):**
```
[agent] Paso 1: llamando PatientHistoryService(patient_id="P-10042")
[mock]  → Historia: plan=PPO-Gold, diagnósticos=[M23.2], prev_auths=[]
[agent] Paso 2: llamando GuidelinesRAG(query="criterios RM rodilla menisco",
                                        plan="PPO-Gold", condition="M23.2")
[mock]  → 3 chunks de "Guía de Imágenes MSK — PPO-Gold, effective_date: 2025-01"
[agent] Paso 3: sintetizando decisión con citas
[citations] ✓ cita encontrada → sección 4.2.1 de la guía
[hitl]  severidad=normal → no escala
```

**Salida esperada (Markdown):**
```markdown
**DECISIÓN: APROBADO**

La solicitud de resonancia magnética de rodilla derecha para el paciente P-10042
(diagnóstico M23.2, plan PPO-Gold) **cumple los criterios de pre-autorización**
según la política vigente.

**Criterio aplicable:**
> "Se aprueba RM de rodilla sin contraste cuando existe diagnóstico confirmado
> de lesión meniscal (M23.x) y el tratamiento conservador ha sido de al menos
> 4 semanas o hay hallazgos clínicos que justifican urgencia diagnóstica."
> — *Guía de Imágenes MSK, PPO-Gold, sección 4.2.1, effective_date: 2025-01*

**Historia del paciente:** No existen autorizaciones previas para este procedimiento.

Número de referencia: AUTH-20260614-001
```

### Caso 2 — Escalación a revisor humano

**Entrada:**
```json
{
  "message": "Pre-autorización urgente: trasplante de médula ósea alogénico para paciente P-20081, leucemia mieloide aguda, plan PPO-Basic. Cirugía programada mañana.",
  "session_id": "session-demo-002"
}
```

**Traza del agente:**
```
[agent] Paso 1: llamando PatientHistoryService(patient_id="P-20081")
[mock]  → Historia: plan=PPO-Basic, diagnósticos=[C91.0], prev_auths=[]
[agent] Paso 2: llamando GuidelinesRAG(query="trasplante medula osea alogenico",
                                        plan="PPO-Basic", condition="C91.0")
[mock]  → 0 chunks (sin criterio explícito para PPO-Basic + C91.0)
[agent] Paso 3: criterio_no_encontrado=true, severidad=alta
[hitl]  → ESCALANDO a clinical-reviewer, timeout: 4h
```

**Salida esperada:**
```markdown
**CASO ESCALADO — Requiere revisión clínica**

Este caso ha sido asignado al revisor clínico certificado (**clinical-reviewer**)
con plazo de respuesta de **4 horas**.

**Motivo de escalación:** No se encontró criterio de pre-autorización explícito
para trasplante de médula ósea alogénico (C91.0) en el plan PPO-Basic.
Los casos sin criterio documentado requieren revisión manual según política interna.

**Datos del caso:**
- Paciente: P-20081 | Plan: PPO-Basic | Diagnóstico: C91.0
- Procedimiento solicitado: Trasplante de médula ósea alogénico
- Urgencia declarada: Alta (cirugía programada)

El solicitante será notificado en cuanto el revisor emita su decisión.
```

### Ejecutar los tests generados

```bash
# Test completo con mocks
pytest tests/ -v

# Test específico de citas obligatorias
pytest tests/test_citations_enforce.py -v
# → verifica que una respuesta sin cita es RECHAZADA por logic.citations

# Test de escalación
pytest tests/test_escalation.py -v
# → verifica que severidad=alta activa hitl.escalate
```

---

## 9. Conceptos staff-level

### Filtros duros por metadata como guardrail de seguridad

`retrieval.vector` acepta `hardFilters: [plan, condition]`. Esto no es un "soft hint" al LLM: es un filtro aplicado **directamente en la consulta SQL al pgvector** (`WHERE metadata->>'plan' = $1 AND metadata->>'condition' = $2`). El LLM nunca ve chunks de un plan o condición distintos a los del paciente, aunque la similitud semántica fuera alta.

¿Por qué importa? Sin filtros duros, una búsqueda por "criterios de RM de rodilla" podría devolver criterios del plan PPO-Platinum que son más permisivos que los de PPO-Basic, induciendo al agente a aprobar lo que no corresponde. En salud, esa confusión tiene consecuencias legales y clínicas. El guardrail es determinista: no depende de que el LLM "recuerde" usar solo los criterios correctos.

### Citas obligatorias: no alucinar en salud

`logic.citations` con `mode: enforce` actúa como un **post-processor fuera del LLM**. Parsea la respuesta del agente buscando referencias a fuentes. Si no hay ninguna, rechaza la respuesta y la re-solicita (o la bloquea). Esto crea una garantía estructural: ninguna decisión de pre-autorización puede llegar al usuario sin un fundamento citado, sin importar cómo respondió el LLM en esa llamada particular.

La alternativa (instruir al LLM a "citar siempre" en el system prompt) no es suficiente para entornos de alta consecuencia: los LLMs pueden olvidar la instrucción, reformular la cita hasta hacerla irreconocible, o fabricar una referencia plausible. El nodo de citas verifica la respuesta, no confía en ella.

### Human-in-the-loop hardcodeado: el LLM no decide cuándo escalar

`hitl.escalate` evalúa la condición `severidad == 'alta' OR criterio_no_encontrado == true` **fuera del LLM**, en la lógica del grafo. El agente puede señalar `severidad=alta` en su salida estructurada, pero la **decisión de interrumpir el flujo y asignar a un humano** es tomada por el nodo HITL de forma determinista.

Esto es deliberado: si la escalación fuera una "herramienta" que el LLM puede o no llamar, el modelo podría razonar "parece suficientemente claro para no escalar" y aprobarlo. En entornos regulados (pre-autorización médica, crédito, compliance), la escalación debe ser un **trip-wire estructural**, no una opción que el LLM evalúa. El nodo HITL es ese trip-wire.

### Privacidad y PHI (Protected Health Information)

El `io.input` requiere `auth: jwt`: ninguna solicitud entra sin token válido. La historia del paciente (PHI) fluye solo dentro del grafo, nunca se logea en texto plano ni se incluye en prompts de ingesta. En producción se agrega `observability.audit` apuntando a un sink cifrado con retención regulada (HIPAA / normativa local). El Flow IR no contiene valores de secretos ni datos de paciente: solo referencias a secretos y esquemas.

El `SERVICE_API_KEY` del EHR se inyecta en runtime como variable de entorno, nunca aparece en el JSON versionado en git.

---

⬅️ [Índice](../../README.md)
