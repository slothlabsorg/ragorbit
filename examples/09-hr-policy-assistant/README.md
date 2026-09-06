# 09 · Asistente de políticas y beneficios para empleados (RRHH)

> Tiempo estimado para tener el bot funcionando: **~10 minutos**.

---

## 1. Problema, industria y a quién sirve

**Industria:** Recursos Humanos / cualquier empresa con más de 50 empleados.

**El problema:** Los empleados hacen las mismas preguntas una y otra vez al equipo de RRHH — vacaciones, bajas médicas, beneficios de salud, proceso de onboarding — y el equipo pierde horas respondiendo. Los manuales existen, pero nadie los lee.

**A quién sirve:**

- **Empleados** que quieren una respuesta inmediata sin abrir un PDF de 80 páginas.
- **Equipos de RRHH** que quieren reducir preguntas repetitivas y redirigir su tiempo a casos complejos.
- **IT / equipos de plataforma** que necesitan desplegar el bot rápido, sin infraestructura de base de datos externa.

Este ejemplo es **el más simple del catálogo**: un RAG conversacional con un solo índice, Chroma local y cero backends externos. Es el punto de partida recomendado si es tu primera vez con RAGorbit.

---

## 2. Resultado esperado

El empleado abre un chat, escribe su pregunta en lenguaje natural y recibe:

1. Una **respuesta clara en markdown** basada exclusivamente en los documentos de la empresa.
2. Una **cita a la sección exacta** de la política que respalda la respuesta (p.ej. `[Política de Vacaciones, §3.1]`).
3. Si la información no está en los documentos, el bot lo dice explícitamente — sin inventar.

```
Empleado: ¿Cuántos días de vacaciones tengo el primer año?

Asistente: Durante tu primer año de servicio tienes derecho a **12 días hábiles**
de vacaciones, prorrateados a partir del mes de inicio.

> Fuente: Política de Vacaciones y Descansos, §3.1 — "Acumulación durante el
> primer año de servicio".
```

---

## 3. Arquitectura (con puertos)

```
                         ┌──────────────┐   Documents   ┌───────────────┐
                         │  loader.pdf  │──────────────▶│ ingest.chunker│
                         │ (data/hr_docs│               └───────┬───────┘
                         └──────────────┘                       │ Documents
                                                                 ▼
                         ┌──────────────┐  Embeddings   ┌───────────────┐  Retriever
                         │model.embedding│─────────────▶│ store.chroma  │──────────────┐
                         └──────────────┘               │ (hr_policies) │              │
                                                         └───────────────┘              │
                                                                                        ▼
  io.input ──Message──▶ retrieval.vector ◀──────────────────────────────── Retriever ──┘
  (chat)       │        (topK 4)
               │             │ Chunks
               │             ▼
               │        logic.prompt ◀── Model ── model.llm
               │        (síntesis)
               │             │ Message           │ Chunks
               └─────────────┘                   │
                   Message                        │
                         ▼                        ▼
                    logic.citations ◀─────────────┘
                    (mode: enforce)
                         │ Message
                         ▼
                      io.output
                     (markdown)
```

**Tipos de puerto en las conexiones clave:**

| Arista | Puerto origen | Tipo | Puerto destino |
|--------|--------------|------|----------------|
| `loader.pdf` → `ingest.chunker` | `Documents` | `Documents` | `Documents` |
| `model.embedding` → `store.chroma` | `Embeddings` | `Embeddings` | `Embeddings` |
| `store.chroma` → `retrieval.vector` | `Retriever` | `Retriever` | `Retriever` |
| `retrieval.vector` → `logic.prompt` | `Chunks` | `Chunks` | `Chunks` |
| `model.llm` → `logic.prompt` | `Model` | `Model` | `Model` |
| `logic.prompt` → `logic.citations` | `Message` | `Message` | `Message` |
| `logic.citations` → `io.output` | `Message` | `Any` | `Any` |

---

## 4. Construirlo paso a paso

### Paso 0 — Empieza desde el template (nunca lienzo en blanco)

Abre RAGorbit y elige **Crear desde template → "Asistente de preguntas sobre documentos (RAG)"**. El lienzo aparece **pre-cableado** con los 10 nodos y todas las conexiones ya hechas. No arrastres nada todavía.

> El template ya incluye `logic.citations` en modo `enforce`. Esta es la versión "con citas" del tutorial básico de [03-build-first-flow](../../docs/03-build-first-flow.md).

### Solo tienes que configurar 3 cosas

**Eso es todo.** El resto de campos tiene defaults que ya funcionan.

**Cosa 1 — Tus documentos:** Haz clic en el nodo `loader.pdf` (etiqueta "Docs RRHH"). En el campo `path` escribe la carpeta que contiene tus PDFs, o arrastra los archivos al panel. Puedes empezar con un solo PDF.

```
path: data/hr_docs/
```

Los archivos de muestra que incluye el template (fixtures del mock) ya simulan un manual de empleado con secciones de vacaciones y beneficios, así que puedes probar antes de subir los tuyos.

**Cosa 2 — Nombre de tu colección:** Haz clic en `store.chroma` (etiqueta "Chroma hr_policies"). Cambia `collection` si quieres un nombre distinto, o déjalo como `hr_policies`. Chroma corre **en local dentro del contenedor generado** — no necesitas credenciales ni un servidor separado.

```
collection: hr_policies
```

**Cosa 3 — Tu API key:** Haz clic en `model.llm` (etiqueta "Claude Opus 4.8"). El campo `apiKeyRef` ya dice `ANTHROPIC_API_KEY`. Ve a **Secretos**, agrega ese nombre y pega tu clave. El valor se guarda cifrado del lado servidor y nunca entra al `flow.json`.

### Paso 1 — Valida

Pulsa **Validar**. Si algo falta, el mensaje te dice exactamente qué hacer. Un flujo válido muestra todos los nodos en verde.

### Paso 2 — Prueba con mocks

Pulsa **Probar con mocks**. El bot arranca en el panel de chat del navegador con los fixtures del template. Escribe `¿Cuántos días de vacaciones tengo el primer año?` y mira la respuesta con cita. No necesitas la API key real para este paso.

### Paso 3 — Exporta o despliega

- **Local:** Exporta el `.zip`, descomprime y ejecuta `docker compose up`. El bot queda en `http://localhost:8000` listo para chatear.
- **Producción:** Pon `MOCK=false`, asegúrate de que `ANTHROPIC_API_KEY` esté disponible como variable de entorno, y despliega el contenedor donde quieras.

---

## 5. Configuración de cada nodo (tabla)

| Nodo | `type` | Campo | Valor en este ejemplo | Por qué |
|------|--------|-------|-----------------------|---------|
| Entrada Chat | `io.input` | `channel` | `chat` | Conversación de texto |
| | | `auth` | `none` | Intranet sin autenticación extra |
| | | `streaming` | `true` | Respuesta progresiva |
| Docs RRHH | `loader.pdf` | `path` | `data/hr_docs/` | Carpeta con los PDFs de políticas |
| | | `ocr` | `false` | PDFs digitales, no escaneados |
| Troceador | `ingest.chunker` | `strategy` | `by-section` | Respeta encabezados de sección del manual |
| | | `chunkSize` | `800` | Default — funciona bien para políticas |
| | | `overlap` | `120` | Default |
| Modelo Embedding | `model.embedding` | `model` | `text-embedding-3-large` | Default — alta calidad |
| | | `apiKeyRef` | `ANTHROPIC_API_KEY` | Reutiliza el mismo secreto del LLM |
| Chroma | `store.chroma` | `collection` | `hr_policies` | Nombre del índice local |
| Recuperador | `retrieval.vector` | `topK` | `4` | 4 fragmentos más relevantes |
| Modelo LLM | `model.llm` | `model` | `anthropic:claude-opus-4-8` | Default |
| | | `temperature` | `0.2` | Respuestas precisas, poca creatividad |
| | | `apiKeyRef` | `ANTHROPIC_API_KEY` | La única credencial necesaria |
| Síntesis | `logic.prompt` | `system` | Ver flow.json | Instrucción al LLM para ceñirse a los docs |
| | | `template` | Ver flow.json | Plantilla con `{message}` y `{chunks}` |
| Citas | `logic.citations` | `mode` | `enforce` | Rechaza respuestas sin cita a la fuente |
| Salida | `io.output` | `format` | `markdown` | Respuesta formateada en el chat |
| | | `streaming` | `true` | Aparece progresivamente |

---

## 6. Secretos

Solo se necesita **uno**:

| Nombre | Usado por | Requerido |
|--------|-----------|-----------|
| `ANTHROPIC_API_KEY` | `model.llm`, `model.embedding` | Sí |

Chroma corre en local — no necesita credenciales. Esta es la mayor ventaja de este ejemplo para un primer intento.

---

## 7. Qué genera el codegen

Al exportar o desplegar, RAGorbit genera un proyecto Python con esta estructura:

```
hr-policy-assistant/
├── app/
│   ├── main.py              # FastAPI con endpoint SSE /chat
│   ├── graph.py             # Grafo LangGraph con los 10 nodos cableados
│   ├── nodes/
│   │   ├── loader_pdf.py
│   │   ├── chunker.py
│   │   ├── embedding.py
│   │   ├── chroma_store.py
│   │   ├── retrieval_vector.py
│   │   ├── llm.py
│   │   ├── prompt.py
│   │   ├── citations.py
│   │   └── output.py
│   └── config.py            # Lee variables de entorno / secretos
├── mocks/
│   ├── loader_pdf_mock.py   # Devuelve fixtures sin leer archivos reales
│   └── fixtures/
│       └── hr_docs.yaml     # Fragmentos de muestra de política de RRHH
├── tests/
│   └── test_hr_flow.py      # Tests de integración con mocks
├── data/
│   └── hr_docs/             # Carpeta vacía — aquí van tus PDFs
├── .env.template            # Solo nombres: ANTHROPIC_API_KEY=
├── docker-compose.yml       # Levanta app + Chroma local
└── Dockerfile
```

**Puntos clave del código generado:**

- `graph.py` usa `create_graph()` de LangGraph. El grafo refleja exactamente el `flow.json` — cada nodo es una función Python que el generador emitió a partir del manifest.
- La variable `MOCK` controla si los loaders leen archivos reales o devuelven fixtures. Por defecto es `true` al arrancar con `docker compose up`.
- `logic.citations` se genera como un paso de post-procesamiento que verifica que la respuesta de `logic.prompt` contenga al menos una referencia a los chunks recuperados; si no, regenera con una instrucción explícita de citar.
- El código no tiene dependencia de RAGorbit en runtime — es Python + LangGraph + LangChain estándar.

---

## 8. Probarlo con mocks

### Arrancar

```bash
# Descarga el ZIP exportado y descomprime, o clona solo este directorio
docker compose up
# El servicio queda en http://localhost:8000
```

### Entrada de prueba

```bash
curl -N -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "¿Cuántos días de vacaciones tengo el primer año?"}'
```

O abre `http://localhost:8000` en el navegador — incluye un panel de chat básico.

### Salida esperada (streaming SSE, modo mock)

```
data: Durante tu primer año de servicio tienes derecho a **12 días hábiles**
data: de vacaciones, prorrateados a partir del mes de inicio. Los días se
data: acumulan mensualmente a razón de 1 día por mes completo trabajado.
data:
data: > **Fuente:** Política de Vacaciones y Descansos, §3.1 —
data: > "Acumulación durante el primer año de servicio"
data: > *(Manual del Empleado, pág. 14)*
data: [DONE]
```

### Verificar que las citas son obligatorias

```bash
# Esta pregunta está fuera del ámbito de los documentos mock:
curl -N -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "¿Cuál es el precio de las acciones de la empresa hoy?"}'
```

Respuesta esperada:

```
data: Lo siento, esa información no está disponible en los documentos de
data: política de RRHH que tengo acceso. Para consultas sobre acciones o
data: información financiera, contacta al departamento de Finanzas o
data: Relaciones con Inversores.
data: [DONE]
```

El bot no inventa — si no hay chunks relevantes, `logic.citations` en modo `enforce` bloquea cualquier respuesta sin respaldo documental y el LLM indica la limitación.

---

## 9. Conceptos staff-level

### Citas a la fuente para construir confianza

En RRHH la confianza es todo: si el bot dice "tienes 15 días de vacaciones" sin citar de dónde lo saca, nadie le cree. El nodo `logic.citations` con `mode: enforce` no es opcional en este dominio — garantiza que **cada afirmación sea trazable**. Si el LLM no puede citar, el paso falla internamente y se fuerza una regeneración con instrucción explícita. Esto elimina las alucinaciones con consecuencias laborales.

### Chroma local para cero fricción en el primer intento

La elección de `store.chroma` en lugar de `store.pgvector` o `store.qdrant` es deliberada: Chroma corre embebido dentro del contenedor, sin servidor separado, sin credenciales, sin migraciones. Para un primer despliegue en intranet es suficiente para cientos de empleados y decenas de miles de chunks. El índice persiste en un volumen Docker entre reinicios.

### Defaults sensatos como filosofía de diseño

Este flujo no toca `chunkSize`, `overlap`, `topK` ni `temperature` más allá de los valores por defecto del catálogo. Esos defaults no son arbitrarios — son el resultado de pruebas sobre dominios documentales estándar. La norma en RAGorbit es: **no cambies un default hasta que tengas una métrica que justifique el cambio** (p.ej. precisión en un eval set propio). Empezar con defaults reduce el espacio de variables al mínimo.

### Cómo escalar cuando el caso crece

Este ejemplo es el mínimo viable. Cuando el caso madure:

- **Más colecciones / multi-index:** Si tienes documentos de distintas áreas (RRHH, Legal, IT), reemplaza `store.chroma` por `store.multi-index` y `retrieval.vector` por `retrieval.router`. El router elige el índice por keyword o intención antes de recuperar — menos ruido, menos tokens.
- **Agente con tools:** Si los empleados necesitan *accionar* (p.ej. solicitar vacaciones, consultar su saldo de días), conecta el flujo a un `agent.react` con un `tool.service` hacia el HRIS (Workday, BambooHR, etc.). El ejemplo [01 · Aerolínea](../01-airline-flight-change/) muestra este patrón.
- **Feedback loop:** Agrega `observability.feedback` para recoger thumbs-up/down y, con el tiempo, afinar el reranker con señales reales de relevancia de los empleados.
- **Embeddings locales:** Si la privacidad es crítica, cambia `model.embedding` a `local: true` con un modelo SBERT embebido — cero llamadas externas.

---

⬅️ [Índice](../../README.md)
