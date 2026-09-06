# 01 · Conceptos centrales

> Este capítulo es **el contrato**. Define el vocabulario (Flow IR, nodos, puertos, tipos, secretos, deployment targets) que el resto del libro y los 10 ejemplos usan al pie de la letra. Si lees un solo capítulo, que sea este.

---

## 1. El modelo mental en una frase

> En RAGorbit dibujas un **grafo de nodos**, ese grafo se guarda como un **documento JSON portable (Flow IR)**, y un **generador de código** convierte ese JSON en un **proyecto Python ejecutable** que ya incluye **servicios mock y tests** para que funcione el primer día.

```
   Lienzo (drag & drop)          Flow IR (JSON portable)         Artefacto desplegable
 ┌───────────────────┐        ┌──────────────────────┐        ┌──────────────────────┐
 │  ◻── ◻── ◻         │  ───▶  │ { nodes:[…],          │  ───▶  │ app/  mocks/  tests/  │
 │   \   |   /        │  save  │   edges:[…],          │ codegen│ Dockerfile            │
 │      ◻             │        │   secrets:[…] }       │        │ docker-compose.yml    │
 └───────────────────┘        └──────────────────────┘        └──────────────────────┘
      diseño                     fuente de verdad                 corre con `up`
```

El lienzo es **desechable**: lo que importa es el Flow IR. Puedes versionarlo en git, revisarlo en un PR, generarlo a mano o con otra herramienta. **No hay lock-in**: el artefacto generado es código Python normal (LangGraph + LangChain) que corre sin RAGorbit.

---

## 2. Flow IR — la especificación portable

El **Flow IR** (Intermediate Representation) es un documento JSON versionado. Es la única fuente de verdad.

### 2.1 Estructura de alto nivel

```jsonc
{
  "irVersion": "1.0",
  "flow": {
    "id": "airline-flight-change",
    "name": "Agente de cambio de vuelo",
    "description": "Pasajero cambia su vuelo en lenguaje natural",
    "deploymentTarget": "chat-service",   // derivado de los nodos de I/O — ver §5
    "defaults": { "llm": "anthropic:claude-opus-4-8" }
  },
  "nodes": [ /* ver §3 */ ],
  "edges": [ /* ver §4 */ ],
  "secrets": [ /* ver §6 — solo nombres, nunca valores */ ]
}
```

### 2.2 Reglas de validez (un Flow IR es válido si…)

1. Todo `node.type` existe en el [catálogo de nodos](./02-node-catalog.md).
2. Todo `node.config` valida contra el `configSchema` (JSON Schema) de su manifest.
3. Todo `edge` conecta un puerto de salida con un puerto de entrada **de tipo compatible** (§4.2).
4. Cada puerto de entrada **requerido** está conectado.
5. Existe exactamente **un nodo de entrada** y al menos **un nodo de salida** (categoría `io`).
6. El grafo es **acíclico** salvo en aristas marcadas `loop: true` (p.ej. ReAct, feedback).
7. Todo secreto referenciado por un nodo aparece en `secrets[]`.

> RAGorbit valida estas reglas en vivo en el lienzo y de nuevo antes de generar código. Los mensajes de error son **accionables** (ver [06-ux-principles](./06-ux-principles.md)).

---

## 3. Nodos

Un **nodo** es una instancia de un **tipo** del catálogo, con su configuración y posición.

```jsonc
{
  "id": "policy_rag",                 // único dentro del flow
  "type": "retrieval.vector",         // referencia al manifest del catálogo
  "label": "PolicyRAG",               // nombre visible (editable por el usuario)
  "config": {                          // validado contra el configSchema del tipo
    "index": "fare_rules",
    "topK": 4,
    "hardFilters": ["fare_class", "route_type"]
  },
  "position": { "x": 320, "y": 180 }   // solo para el lienzo; el codegen lo ignora
}
```

Un nodo **no contiene** la lógica: la lógica vive en el **manifest** del tipo (cómo se ve, qué puertos tiene, cómo se genera su código). Esto es lo que hace al catálogo extensible — ver §7 y [05-extending](./05-extending.md).

---

## 4. Puertos, tipos y aristas

### 4.1 Puertos

Cada nodo declara **puertos de entrada y salida** con nombre y **tipo de dato del grafo**. Ejemplo del manifest de un vector store:

```yaml
ports:
  inputs:  [{ name: documents,  type: Documents,  required: true  }]
  outputs: [{ name: retriever,  type: Retriever }]
```

### 4.2 Tipos de dato del grafo (port types)

Los tipos son **abstractos** (no son tipos de Python): sirven para validar que dos nodos se pueden conectar. Tabla canónica:

| Tipo            | Qué representa                                          | Producido por (ej.)            | Consumido por (ej.)            |
|-----------------|--------------------------------------------------------|--------------------------------|--------------------------------|
| `Documents`     | Documentos/fragmentos cargados                         | loaders, chunker               | embedder, store                |
| `Embeddings`    | Función de embedding configurada                       | model.embedding                | store, retriever               |
| `Retriever`     | Algo que devuelve chunks dado un query                 | store, retrieval.*             | agent, prompt, reranker        |
| `Chunks`        | Resultado de una recuperación (texto + metadata)       | retrieval.*, reranker          | prompt, citations, structured  |
| `Model`         | LLM configurado                                        | model.llm                      | agent, prompt, structured      |
| `Tool`          | Una herramienta invocable por un agente                | tool.*, guardrail wrappers     | agent                          |
| `Message`       | Texto/mensaje (query o respuesta)                      | io.input, query.*, prompt      | casi todo                      |
| `Query`         | Consulta normalizada                                   | query.rewrite, query.intent    | retrieval.*, router            |
| `Decision`      | Salida estructurada (JSON con criterio/veredicto)      | logic.structured, logic.rules  | io.output, tool                |
| `Event`         | Mensaje de un stream (Kafka)                           | io.event-source                | router, agent                  |
| `Any`           | Comodín (acepta/produce cualquier tipo)                | —                              | —                              |

**Regla de compatibilidad:** un edge `A.out → B.in` es válido si `type(out) == type(in)` o alguno es `Any`. El lienzo solo deja soltar conexiones compatibles (los puertos válidos se iluminan).

### 4.3 Aristas (edges)

```jsonc
{ "source": "policy_rag", "sourcePort": "retriever",
  "target": "orchestrator", "targetPort": "tools",
  "loop": false }   // loop:true permite ciclos (ReAct, feedback)
```

---

## 5. Deployment targets (cómo se despliega)

El **target** se **deriva automáticamente** del nodo de **entrada** del flujo. El usuario no lo elige a mano (aunque puede forzarlo en Avanzado). Esto mantiene la UX simple: eliges *cómo entra el trabajo* y RAGorbit sabe qué esqueleto generar.

| Nodo de entrada            | `deploymentTarget` | Esqueleto generado                                   |
|----------------------------|--------------------|------------------------------------------------------|
| `io.input` (chat/voz)      | `chat-service`     | Servicio **FastAPI** con streaming SSE/WebSocket     |
| `io.event-source` (Kafka)  | `event-worker`     | Worker **consumidor de Kafka**, stateless, fan-out   |
| `io.trigger` (durable)     | `temporal`         | **Workflow + activities** de Temporal (durable)      |
| `io.batch` (archivos/cron) | `batch`            | **Job** ejecutable (CLI/cron/contenedor)             |

> Temporal y Kafka son **opcionales y derivados** — no el centro. La mayoría de bots conversacionales son `chat-service`.

Ver detalle de cada esqueleto en [04-codegen-and-deploy](./04-codegen-and-deploy.md).

---

## 6. Secretos

Las API keys y credenciales **nunca** se guardan en el Flow IR. El nodo referencia un **nombre de secreto**; el valor vive en el gestor de secretos (cifrado server-side) y se inyecta en deploy como variable de entorno.

```jsonc
// en el nodo:
"config": { "apiKeyRef": "ANTHROPIC_API_KEY" }

// en el flow:
"secrets": [
  { "name": "ANTHROPIC_API_KEY", "required": true,  "usedBy": ["llm"] },
  { "name": "RESERVATION_API_KEY", "required": false, "usedBy": ["reservation_tool"] }
]
```

El codegen produce un `.env.template` con **solo los nombres**. En modo mock (§ siguiente) los secretos de servicios externos no son necesarios.

---

## 7. Manifests — por qué el catálogo es extensible

Cada tipo de nodo está definido por un **manifest declarativo** (no por código en el core). Un manifest contiene:

```yaml
type: tool.service              # id único del tipo
category: tool                  # categoría para la paleta
title: External Service Tool
description: Llama a un servicio externo como tool del agente
ports:
  inputs:  [{ name: input,  type: Tool }]
  outputs: [{ name: tool,   type: Tool }]
configSchema:                   # JSON Schema → genera el formulario de la UI
  type: object
  required: [name, baseUrl, operation]
  properties:
    name:      { type: string, title: "Nombre del tool" }
    baseUrl:   { type: string, title: "Base URL" }
    operation: { type: string, title: "Operación" }
secrets: [SERVICE_API_KEY]
emitter: tool.service           # qué emisor genera su código real
mock:    { behavior: tool_service }   # qué comportamiento corre en modo mock
```

> Los manifests viven como JSON en `ragorbit/catalog/nodes/<categoría>.json`; aquí
> se muestran en YAML solo por legibilidad.

**Agregar una tecnología nueva = un manifest + un emisor + un behavior mock.** Cero cambios en el core. El registro los descubre y aparecen en la paleta automáticamente. Ver [05-extending](./05-extending.md).

> **Por qué dos implementaciones (real + mock):** así todo artefacto generado corre desde el minuto cero con datos de muestra (`MOCK=true`), y luego apuntas a los servicios reales con `MOCK=false`. Esta es la base del listón de UX "éxito al primer intento". Las dos comparten firma —reciben las entradas agrupadas por tipo de puerto y devuelven `{tipo_de_puerto: valor}`— así que se leen en paralelo y el flujo se comporta igual en los dos modos.

---

## 8. Glosario rápido

- **Flow IR**: el JSON portable que describe el grafo. Fuente de verdad.
- **Nodo / tipo / manifest**: instancia / clase / definición declarativa de un bloque.
- **Puerto / tipo de puerto**: punto de conexión / tipo de dato del grafo para validar conexiones.
- **Deployment target**: forma de despliegue derivada del nodo de entrada.
- **Secreto (ref)**: nombre de credencial; el valor nunca está en la IR.
- **Mock**: implementación de muestra de un servicio/loader para correr sin backends reales.

➡️ Siguiente: [02 · Catálogo de nodos](./02-node-catalog.md) — el libro de bloques que estos conceptos hacen posible.
