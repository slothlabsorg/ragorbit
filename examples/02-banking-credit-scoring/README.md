# 02 · Banca — Evaluación de potencial de crédito

---

## 1. Problema, industria y a quién sirve

**Industria:** banca minorista y crédito al consumo.

Un oficial de crédito recibe cada día un lote de solicitudes de préstamo. Cada expediente contiene documentos heterogéneos: declaraciones fiscales en PDF, estados de cuenta bancarios en PDF y datos financieros estructurados (ingresos, deudas, historial) en CSV. El proceso manual es lento, inconsistente y difícil de auditar: distintos analistas ponderan los mismos factores de forma diferente.

**A quién sirve:**

- **Equipos de originación de crédito** que quieren escalar el volumen de evaluaciones sin ampliar plantilla.
- **Equipos de cumplimiento y riesgo** que necesitan que cada decisión sea reproducible, trazable y justificada con citas explícitas a los documentos del solicitante.
- **Ingenieros de ML/data** que quieren un pipeline batch versionable en git, sin lógica de negocio enterrada en notebooks.

---

## 2. Resultado esperado

El job produce, por cada solicitante, un objeto JSON con:

| Campo | Descripción |
|---|---|
| `score` | Entero 0–100 calculado por el LLM a partir de los documentos |
| `decision` | `"aprobar"` / `"revisar"` / `"rechazar"` — fijado por reglas deterministas sobre el score |
| `factores` | Lista de factores que sustentan la puntuación (con citas a los docs fuente) |
| `justificacion` | Razonamiento detallado que referencia fragmentos recuperados |

La salida es apta para ingestarse directamente en un sistema core bancario o una cola de revisión humana.

---

## 3. Arquitectura (diagrama ASCII con puertos)

```
                           Documents           Documents
 io.batch ──────────────▶ loader.pdf ──────┐
 (source, glob)                             │
                          loader.tabular ───┘
 (Documents →)             (Documents →)    │
                                            ▼
                                      ingest.chunker
                                       (documents →)
                                            │ Documents
                                            ▼
                                      ingest.metadata
                                    fields:[doc_type,period]
                                       (documents →)
                                            │ Documents
                          Embeddings        ▼
  model.embedding ───────────────────▶ store.pgvector
  (embeddings →)                       index:credit_docs
                                       (retriever →)
                                            │ Retriever
                                            ▼
                                     retrieval.vector
                                       topK:6
                                       (chunks →)
                                            │ Chunks
                           Model            ▼
  model.llm ─────────────────────────▶ logic.structured
  (model →)                            schema:{score,decision,
                                        factores,justificacion}
                                        requireCitations:true
                                       (decision →)
                                            │ Decision
                                            ▼
                                      logic.rules
                                       >=70 → aprobar
                                       40-69 → revisar
                                       <40  → rechazar
                                       (decision →)
                                            │ Decision
                                            ▼
                                       io.output
                                       format:json
```

**Puertos clave:**

| Arista | Puerto origen | Puerto destino | Tipo |
|---|---|---|---|
| `pdf_loader` → `chunker` | `documents` | `documents` | `Documents` |
| `tabular_loader` → `chunker` | `documents` | `documents` | `Documents` |
| `chunker` → `metadata_tagger` | `documents` | `documents` | `Documents` |
| `metadata_tagger` → `vector_store` | `documents` | `documents` | `Documents` |
| `embedder` → `vector_store` | `embeddings` | `embeddings` | `Embeddings` |
| `vector_store` → `retriever` | `retriever` | `retriever` | `Retriever` |
| `retriever` → `structured_decision` | `chunks` | `chunks` | `Chunks` |
| `llm` → `structured_decision` | `model` | `model` | `Model` |
| `structured_decision` → `rules_engine` | `decision` | `input` | `Decision` |
| `rules_engine` → `output` | `decision` | `input` | `Decision` |

---

## 4. Construirlo paso a paso

1. **Añadir `io.batch`** — fuente del lote. Configura `source` apuntando al directorio del expediente (`data/applicants/`) y `glob` a `**/*.{pdf,csv}`. Este nodo define el `deploymentTarget: batch`.
2. **Añadir `loader.pdf`** — arrastra desde la paleta. Conecta `io.batch → loader.pdf` (puerto `documents`). Configura `path` al mismo directorio.
3. **Añadir `loader.tabular`** — para los CSV. Conecta `io.batch → loader.tabular`. Añade `schemaHint: "financial_data"` para guiar la interpretación de columnas.
4. **Añadir `ingest.chunker`** — conecta ambos loaders (`pdf_loader.documents` y `tabular_loader.documents`). Elige `strategy: by-section` para respetar la estructura de los documentos financieros.
5. **Añadir `ingest.metadata`** — conecta `chunker → metadata_tagger`. Define `fields: [doc_type, period]` para poder filtrar por tipo de documento y período fiscal.
6. **Añadir `model.embedding`** — nodo independiente. Proporciona la función de embedding al store.
7. **Añadir `store.pgvector`** — conecta `metadata_tagger.documents` y `embedder.embeddings`. Configura `index: credit_docs`.
8. **Añadir `retrieval.vector`** — conecta `vector_store.retriever`. Configura `topK: 6` y `hardFilters: [doc_type, period]` para acotar la recuperación al expediente correcto.
9. **Añadir `model.llm`** — configura `model: anthropic:claude-opus-4-8` y `temperature: 0.1` (baja para reproducibilidad).
10. **Añadir `logic.structured`** — conecta `retriever.chunks` y `llm.model`. Define el `schema` con `score`, `decision`, `factores` y `justificacion`. Activa `requireCitations: true`.
11. **Añadir `logic.rules`** — conecta `structured_decision.decision`. Define los tres umbrales deterministas (`>= 70`, `40–69`, `< 40`).
12. **Añadir `io.output`** — conecta `rules_engine.decision`. Elige `format: json` y `streaming: false` (batch, no necesita streaming).
13. **Revisar secretos** — el lienzo muestra los tres nombres requeridos: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `DATABASE_URL`.

---

## 5. Config de cada nodo

| Nodo (id) | type | Config destacada |
|---|---|---|
| `batch_source` | `io.batch` | `source: "data/applicants/"`, `glob: "**/*.{pdf,csv}"` |
| `pdf_loader` | `loader.pdf` | `path: "data/applicants/"`, `ocr: false` |
| `tabular_loader` | `loader.tabular` | `path: "data/applicants/"`, `schemaHint: "financial_data"` |
| `chunker` | `ingest.chunker` | `strategy: "by-section"`, `chunkSize: 800`, `overlap: 120` |
| `metadata_tagger` | `ingest.metadata` | `fields: ["doc_type", "period"]` |
| `embedder` | `model.embedding` | `model: "text-embedding-3-large"`, `local: false`, `apiKeyRef: "OPENAI_API_KEY"` |
| `vector_store` | `store.pgvector` | `index: "credit_docs"`, `distance: "cosine"` |
| `retriever` | `retrieval.vector` | `topK: 6`, `hardFilters: ["doc_type", "period"]` |
| `llm` | `model.llm` | `model: "anthropic:claude-opus-4-8"`, `temperature: 0.1`, `apiKeyRef: "ANTHROPIC_API_KEY"` |
| `structured_decision` | `logic.structured` | `schema: {score, decision, factores, justificacion}`, `requireCitations: true` |
| `rules_engine` | `logic.rules` | `rules: [>=70→aprobar, 40-69→revisar]`, `else: rechazar` |
| `output` | `io.output` | `format: "json"`, `streaming: false` |

---

## 6. Secretos requeridos

```
ANTHROPIC_API_KEY
OPENAI_API_KEY
DATABASE_URL
```

El codegen genera `.env.template` con solo estos nombres. En modo mock (`MOCK=true`) solo `DATABASE_URL` es necesario (el store mock corre en memoria y los modelos usan stubs).

---

## 7. Qué genera el codegen

**Target:** `batch` — el artefacto es un **job CLI ejecutable** (también empaquetable como contenedor o tarea cron).

```
02-banking-credit-scoring/
├── app/
│   ├── main.py              # Punto de entrada: itera sobre expedientes, ejecuta el grafo
│   ├── graph.py             # Grafo LangGraph compilado a partir del Flow IR
│   ├── nodes/
│   │   ├── batch_source.py
│   │   ├── pdf_loader.py
│   │   ├── tabular_loader.py
│   │   ├── chunker.py
│   │   ├── metadata_tagger.py
│   │   ├── embedder.py
│   │   ├── vector_store.py
│   │   ├── retriever.py
│   │   ├── llm.py
│   │   ├── structured_decision.py
│   │   ├── rules_engine.py
│   │   └── output.py
│   └── schemas.py           # Pydantic models derivados del schema de logic.structured
├── mocks/
│   ├── loader_pdf_mock.py   # Devuelve fixtures de declaraciones PDF de muestra
│   ├── loader_tabular_mock.py
│   ├── embedding_mock.py    # Embeddings aleatorios normalizados para tests
│   └── pgvector_mock.py     # Store en memoria (sin Postgres real)
├── tests/
│   ├── test_graph.py        # Ejecuta el grafo completo con mocks; afirma schema de salida
│   ├── test_rules.py        # Prueba los tres umbrales de logic.rules de forma aislada
│   └── fixtures/
│       └── applicant_001/   # Expediente de muestra (PDFs y CSV sintéticos)
├── .env.template
├── Dockerfile
└── docker-compose.yml
```

---

## 8. Probarlo con mocks

### Requisitos previos

```bash
cd examples/02-banking-credit-scoring
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### Ejecutar el batch sobre el fixture de muestra

```bash
MOCK=true python app/main.py --applicant fixtures/applicant_001
```

### Ejecutar los tests con pytest

```bash
MOCK=true pytest tests/ -v
```

### Entrada (fixture `applicant_001`)

```
fixtures/applicant_001/
├── declaracion_2023.pdf    # Declaración fiscal año 2023
├── estado_cuenta_q3.pdf    # Estado de cuenta bancario Q3 2023
└── datos_financieros.csv   # Ingresos, deudas, historial de pagos
```

Fragmento del CSV de muestra:

```csv
concepto,valor,periodo
ingreso_anual,85000,2023
deuda_total,12000,2023
pagos_puntuales_pct,97,2023
antiguedad_laboral_anos,6,2023
```

### Salida JSON esperada

```json
{
  "score": 72,
  "decision": "aprobar",
  "factores": [
    "Ingresos anuales de $85,000 con estabilidad laboral de 6 años [declaracion_2023.pdf §Ingresos]",
    "Ratio deuda/ingreso del 14%, por debajo del umbral de riesgo [datos_financieros.csv:deuda_total]",
    "Tasa de pagos puntuales del 97% en los últimos 12 meses [estado_cuenta_q3.pdf §Historial]"
  ],
  "justificacion": "El solicitante presenta un perfil financiero sólido. Los ingresos documentados en la declaración 2023 superan el umbral mínimo requerido. La baja ratio deuda/ingreso y el historial de pagos casi impecable reducen el riesgo de impago. Score 72 → regla determinista: decisión 'aprobar'."
}
```

La regla `score >= 70 → "aprobar"` en `logic.rules` sobreescribe cualquier valor en el campo `decision` producido por el LLM, garantizando que el umbral sea siempre determinista.

---

## 9. Conceptos staff-level

### Salida estructurada con esquema

`logic.structured` fuerza al LLM a emitir JSON validado contra un JSON Schema de Pydantic en lugar de texto libre. Esto transforma la salida del modelo en un objeto con contrato fuerte: si el LLM omite `score` o emite un `decision` fuera del enum, el nodo falla antes de propagar datos corruptos. En producción, esta validación es la primera línea de defensa contra alucinaciones estructurales.

### Citas obligatorias a los documentos fuente

`requireCitations: true` instruye al nodo a rechazar respuestas que no anclen cada factor a un fragmento concreto recuperado. Esto crea una cadena de trazabilidad: `decision → factores → chunks → documento original`. Un auditor puede reproducir exactamente qué párrafo del estado de cuenta justifica un factor de riesgo específico, requisito habitual en marcos regulatorios como ECOA/Reg B o equivalentes europeos (EBA Guidelines on Internal Governance).

### Reglas deterministas sobre la decisión del LLM — no delegar el umbral al LLM

El LLM emite un `score` numérico y una `decision` tentativa. `logic.rules` reemplaza ese campo `decision` con la salida de una función determinista pura (`score >= 70 → "aprobar"`). Este diseño es intencional: los LLM son probabilísticos y no deben ser el árbitro final de un umbral de negocio con consecuencias legales. La separación es análoga al patrón juez/árbitro en sistemas de trading: el modelo razona, la regla decide. Esto también simplifica las auditorías — "¿por qué se aprobó?" tiene siempre una respuesta de una sola línea (`score = 72 >= 70`), independientemente de la respuesta narrativa del LLM.

### Reproducibilidad y auditoría del batch

El job batch tiene tres propiedades que lo hacen reproducible:

1. **Determinismo del pipeline de ingesta:** los mismos PDFs y CSVs producen el mismo índice vectorial (mismo modelo de embedding, mismos metadatos). Versionando los fixtures en git se puede re-ejecutar cualquier evaluación histórica.
2. **Temperatura baja (`0.1`):** reduce la varianza de la salida del LLM para el mismo contexto recuperado. No la elimina, pero la acota a niveles aceptables para auditoría interna.
3. **Flow IR versionado:** el `flow.json` es la fuente de verdad. Un cambio en los umbrales de `logic.rules` es un diff en git con autor, fecha y mensaje de commit — exactamente el rastro de auditoría que exige un comité de riesgo cuando modifica criterios de crédito.

---

⬅️ [Índice](../../README.md)
