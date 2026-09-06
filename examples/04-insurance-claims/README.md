# 04 · Adjudicación de reclamos de seguros

## 1. Problema, industria y a quién sirve

**Industria:** Seguros de automóviles, hogar y salud.

**Problema:** Un ajustador de siniestros recibe decenas de reclamos al día. Cada expediente llega como carpeta de archivos: la póliza en PDF (con tablas de cobertura, montos, deducibles, exclusiones) y fotografías del daño. Revisar manualmente cada póliza, identificar la cláusula aplicable, verificar el deducible y redactar la decisión toma entre 20 y 45 minutos por caso. Además, las decisiones son difíciles de auditar: el ajustador a veces no cita la cláusula exacta o aplica reglas de forma inconsistente.

**A quién sirve:**
- Aseguradoras que procesan reclamos de colisión, robo, daños por agua o incendio.
- Equipos de operaciones de siniestros que necesitan consistencia regulatoria en sus decisiones.
- Auditores internos que deben verificar que cada pago cita la cláusula y respeta el deducible pactado.

---

## 2. Resultado esperado

El sistema recibe una carpeta con la póliza del asegurado y las fotos del daño y produce un documento JSON por reclamo con:

- `cubierto`: booleano que indica si el daño está amparado por la póliza.
- `monto_estimado`: importe a pagar en USD, ya descontado el deducible.
- `deducible_aplicado`: monto del deducible que se restó.
- `clausula_aplicada`: referencia textual exacta a la cláusula de la póliza (p.ej. `"Art. 12.3 — Cobertura de Colisión"`).
- `razon`: explicación en lenguaje natural de la decisión.

Cada campo de decisión está obligatoriamente **citado** desde el texto de la póliza. Las reglas deterministas (deducible, exclusiones, vigencia) se aplican antes del LLM para garantizar consistencia.

---

## 3. Arquitectura

```
                         ┌─────────────────────────────────────────────────────────┐
                         │  PIPELINE DE INGESTA (indexa la póliza)                 │
                         │                                                          │
io.batch                 │  loader.multimodal ──► ingest.chunker                   │
  source: s3://          │    extractTables:true     strategy: by-clause           │
  glob: **/*.{pdf,…}     │    describeImages:true ──► ingest.metadata              │
    │                    │                              fields:[policy_type,        │
    │ Documents          │                                       coverage_section]  │
    ▼                    │                                  │                       │
loader.multimodal ───────┘                                  │ Documents             │
    │ Documents                                             ▼                       │
    └──────────────────────────────────────────► store.pgvector (index: policies)  │
                                                            │ Retriever             │
                         ┌──────────────────────────────────┘                      │
                         │                                                          │
model.vision ──Model──┐  │  retrieval.vector                                       │
                      │  │    hardFilters:[policy_type]                            │
model.llm ────Model──►│  │        │ Chunks                                         │
                      │  ▼        ▼                                                 │
                      ├─► logic.rules ──Decision──►  logic.structured              │
                      │   (deducible,                  schema: {cubierto,           │
                      │    exclusiones,                  monto_estimado,            │
                      │    vigencia)                     deducible_aplicado,        │
                      │                                  clausula_aplicada,         │
                      │                                  razon}                     │
                      │                                requireCitations: true       │
                      │                                        │ Decision           │
                      └────────────────────────────────────────┘                   │
                                                               ▼                   │
                                                          io.output                │
                                                           format: json            │
```

Flujo de puertos clave:

| Arista | Puerto fuente | Puerto destino |
|--------|---------------|----------------|
| `batch_input → multimodal_loader` | `Documents` | `Documents` |
| `multimodal_loader → chunker` | `Documents` | `Documents` |
| `chunker → metadata_tagger` | `Documents` | `Documents` |
| `metadata_tagger → policy_store` | `Documents` | `Documents` |
| `embedding_model → policy_store` | `Embeddings` | `Embeddings` |
| `policy_store → policy_retrieval` | `Retriever` | `Retriever` |
| `policy_retrieval → eligibility_rules` | `Chunks` | `Any` |
| `policy_retrieval → coverage_decision` | `Chunks` | `Chunks` |
| `eligibility_rules → coverage_decision` | `Decision` | `Chunks` |
| `llm → coverage_decision` | `Model` | `Model` |
| `vision_model → coverage_decision` | `Model` | `Model` |
| `coverage_decision → json_output` | `Decision` | `Any` |

---

## 4. Construirlo paso a paso

**Paso 1 — Entrada por lote.**
Arrastra `io.batch` al lienzo. Configura `source` con la ruta del bucket (p.ej. `s3://insurance-claims/incoming`) y `glob` con `**/*.{pdf,jpg,jpeg,png}`. Este nodo fija el `deploymentTarget` en `batch` automáticamente.

**Paso 2 — Carga multimodal.**
Agrega `loader.multimodal`. Activa `extractTables: true` para que las tablas de prima y cobertura se conviertan a JSON estructurado, y `describeImages: true` para que las fotografías de daños sean procesadas por visión. Conecta `batch_input.Documents → multimodal_loader.Documents`.

**Paso 3 — Modelo de visión.**
Agrega `model.vision` (Claude Opus 4.8). Este modelo se usará en `logic.structured` para interpretar las descripciones visuales de los daños. No conectes aún; su puerto `Model` irá a `coverage_decision`.

**Paso 4 — Pipeline de ingesta.**
Encadena: `loader.multimodal → ingest.chunker` (estrategia `by-clause`, chunkSize 800) → `ingest.metadata` (fields `policy_type`, `coverage_section`). Esto etiqueta cada chunk con el tipo de póliza para poder filtrar después.

**Paso 5 — Almacenamiento y embeddings.**
Agrega `model.embedding` y `store.pgvector` (index `policies`). Conecta:
- `metadata_tagger.Documents → policy_store.Documents`
- `embedding_model.Embeddings → policy_store.Embeddings`

**Paso 6 — Recuperación con filtro duro.**
Agrega `retrieval.vector` con `topK: 5` y `hardFilters: ["policy_type"]`. El filtro duro garantiza que solo se recuperen cláusulas de la póliza del asegurado (no de pólizas de otro tipo). Conecta `policy_store.Retriever → policy_retrieval.Retriever`.

**Paso 7 — Reglas deterministas.**
Agrega `logic.rules`. Define tres reglas: deducible no alcanzado, exclusión aplicada y póliza vencida. La salida `Decision` de este nodo alimenta `logic.structured`. Conecta `policy_retrieval.Chunks → eligibility_rules.Any`.

**Paso 8 — Decisión estructurada con citas.**
Agrega `logic.structured`. Define el schema JSON con los cinco campos requeridos y activa `requireCitations: true`. Conecta:
- `llm.Model → coverage_decision.Model`
- `vision_model.Model → coverage_decision.Model`
- `policy_retrieval.Chunks → coverage_decision.Chunks`
- `eligibility_rules.Decision → coverage_decision.Chunks`

**Paso 9 — Salida.**
Agrega `io.output` con `format: json`. Conecta `coverage_decision.Decision → json_output.Any`.

---

## 5. Configuración de cada nodo

| Nodo (id) | `type` | Campo | Valor |
|-----------|--------|-------|-------|
| `batch_input` | `io.batch` | `source` | `s3://insurance-claims/incoming` |
| | | `glob` | `**/*.{pdf,jpg,jpeg,png}` |
| `multimodal_loader` | `loader.multimodal` | `extractTables` | `true` |
| | | `describeImages` | `true` |
| | | `sectionScheme` | `insurance-policy` |
| `vision_model` | `model.vision` | `model` | `anthropic:claude-opus-4-8` |
| `chunker` | `ingest.chunker` | `strategy` | `by-clause` |
| | | `chunkSize` | `800` |
| | | `overlap` | `100` |
| `metadata_tagger` | `ingest.metadata` | `fields` | `["policy_type", "coverage_section"]` |
| `embedding_model` | `model.embedding` | `model` | `text-embedding-3-large` |
| | | `local` | `false` |
| | | `apiKeyRef` | `OPENAI_API_KEY` |
| `policy_store` | `store.pgvector` | `index` | `policies` |
| | | `distance` | `cosine` |
| `policy_retrieval` | `retrieval.vector` | `topK` | `5` |
| | | `hardFilters` | `["policy_type"]` |
| `llm` | `model.llm` | `model` | `anthropic:claude-opus-4-8` |
| | | `temperature` | `0.1` |
| | | `apiKeyRef` | `ANTHROPIC_API_KEY` |
| `eligibility_rules` | `logic.rules` | `rules` | 3 reglas: deducible, exclusión, vigencia |
| | | `else` | `{ "elegible": true }` |
| `coverage_decision` | `logic.structured` | `schema` | `{cubierto, monto_estimado, deducible_aplicado, clausula_aplicada, razon}` |
| | | `requireCitations` | `true` |
| `json_output` | `io.output` | `format` | `json` |
| | | `streaming` | `false` |

---

## 6. Secretos

El Flow IR solo contiene nombres. Los valores se inyectan en tiempo de despliegue como variables de entorno.

| Nombre | Obligatorio | Usado por |
|--------|-------------|-----------|
| `ANTHROPIC_API_KEY` | sí | `llm`, `vision_model` |
| `OPENAI_API_KEY` | sí | `embedding_model` |
| `DATABASE_URL` | sí | `policy_store` |
| `STORAGE_KEY` | no | `batch_input` |

El codegen produce un `.env.template` con estos cuatro nombres. En modo `MOCK=true` solo `DATABASE_URL` es necesaria (el bucket S3 se simula con archivos locales de muestra).

---

## 7. Qué genera el codegen

Al ejecutar `ragorbit generate flow.json` se produce la siguiente estructura:

```
insurance-claims/
├── app/
│   ├── pipeline.py          # Grafo LangGraph con todos los nodos
│   ├── nodes/
│   │   ├── batch_input.py
│   │   ├── multimodal_loader.py   # extrae tablas y describe imágenes
│   │   ├── vision_model.py
│   │   ├── chunker.py
│   │   ├── metadata_tagger.py
│   │   ├── embedding_model.py
│   │   ├── policy_store.py
│   │   ├── policy_retrieval.py
│   │   ├── llm.py
│   │   ├── eligibility_rules.py   # lógica determinista pura
│   │   ├── coverage_decision.py   # structured output + citas
│   │   └── json_output.py
│   └── schemas/
│       └── coverage_decision_schema.json
├── mocks/
│   ├── multimodal_loader_mock.py  # fixture: póliza de prueba con tablas
│   ├── vision_model_mock.py       # fixture: descripción de parachoques
│   └── fixtures/
│       ├── poliza_sample.pdf
│       ├── dano_parachoques.jpg
│       └── coverage_decision_expected.json
├── tests/
│   ├── test_eligibility_rules.py  # tests deterministas sin LLM
│   ├── test_coverage_decision.py  # tests con mocks
│   └── test_pipeline_e2e.py
├── .env.template
├── Dockerfile
└── docker-compose.yml
```

Los tests deterministas de `eligibility_rules` no requieren ningún secreto y sirven como punto de partida para CI. El archivo `coverage_decision_expected.json` contiene la salida esperada para el reclamo de parachoques de la sección 8.

---

## 8. Probarlo con mocks

Levanta el pipeline en modo mock (sin backends reales):

```bash
# 1. Copiar y completar variables requeridas
cp .env.template .env
# Solo DATABASE_URL es necesaria en modo mock
echo "DATABASE_URL=postgresql://localhost:5432/claims_test" >> .env

# 2. Levantar servicios
MOCK=true docker compose up

# 3. Enviar reclamo de prueba (carpeta con póliza + foto)
docker compose exec app python -m app.pipeline \
  --input mocks/fixtures/poliza_sample.pdf \
  --input mocks/fixtures/dano_parachoques.jpg \
  --claim-id RECL-2024-001
```

**Entrada simulada:**
- `poliza_sample.pdf`: póliza de automóvil con cobertura de colisión (Art. 12.3), deducible USD 500, exclusiones por uso comercial.
- `dano_parachoques.jpg`: fotografía de parachoques trasero abollado por colisión en estacionamiento.

**Salida esperada:**

```json
{
  "cubierto": true,
  "monto_estimado": 1200.00,
  "deducible_aplicado": 500.00,
  "clausula_aplicada": "Art. 12.3 — Cobertura de Colisión: daños materiales al vehículo asegurado causados por choque, vuelco o colisión con otro vehículo u objeto fijo.",
  "razon": "El daño al parachoques trasero corresponde a una colisión en estacionamiento, amparada por el Art. 12.3 de la póliza. Se aplica el deducible pactado de USD 500. El monto estimado de reparación es USD 1.700, por lo que el pago neto es USD 1.200. No se identificaron exclusiones aplicables."
}
```

Para verificar las reglas deterministas en aislamiento:

```bash
# Caso: deducible no alcanzado (daño USD 200, deducible USD 500)
pytest tests/test_eligibility_rules.py::test_deducible_no_alcanzado -v

# Caso: exclusión por uso comercial
pytest tests/test_eligibility_rules.py::test_exclusion_uso_comercial -v

# Suite completa sin LLM
pytest tests/test_eligibility_rules.py -v
```

---

## 9. Conceptos staff-level

### Ingesta multimodal: visión para daños, tablas como JSON estructurado

Las pólizas de seguros no son texto plano: contienen tablas de coberturas, cuadros de primas y exclusiones que un `loader.pdf` estándar convertiría en texto ambiguo. `loader.multimodal` con `extractTables: true` convierte cada tabla a JSON estructurado antes de chunkar, preservando la semántica de columnas (cobertura, monto máximo, deducible). Las fotos de daños son procesadas por `model.vision` que produce una descripción textual detallada del daño visible; esa descripción se incorpora al contexto de `logic.structured`.

### Citas obligatorias a la cláusula (`requireCitations: true`)

`logic.structured` con `requireCitations: true` instruye al codegen a generar una plantilla de prompt que exige que cada campo de decisión esté sustentado en un fragmento literal de los chunks recuperados. Si el LLM no puede citar, el campo se deja vacío y el pipeline lo reporta como decisión incompleta. Esto es indispensable en seguros: una decisión sin cláusula citada no es admisible para auditoría regulatoria ni para disputas.

### Reglas deterministas para deducible y exclusiones (no delegar al LLM)

`logic.rules` ejecuta código Python puro, sin LLM. Las condiciones de elegibilidad (¿el daño supera el deducible?, ¿aplica una exclusión de la póliza?) son **invariantes de negocio** que no deben depender del criterio del modelo: el resultado debe ser reproducible y auditable al 100%. El LLM solo interviene en `logic.structured` para redactar la justificación y citar la cláusula; nunca para decidir si pagar o no. Esto separa con claridad la lógica determinista (reglas) de la síntesis de lenguaje natural (LLM).

### Filtros duros por tipo de póliza (`hardFilters: ["policy_type"]`)

Sin filtro duro, el retriever podría devolver cláusulas de una póliza de hogar al evaluar un reclamo de auto, o mezclar coberturas de pólizas de distintos asegurados. `hardFilters` en `retrieval.vector` actúa como guardrail estructural: la búsqueda vectorial ocurre **solo dentro** del subconjunto de chunks cuyo metadata `policy_type` coincide con el reclamo en curso. Esto no es un refinamiento de relevancia; es un requisito de corrección del sistema.

---

⬅️ [Índice](../../README.md)
