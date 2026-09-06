# 03 · Construye tu primer flujo (cero a resultado)

> Objetivo: que **sin haber usado RAGorbit antes** llegues a un bot funcionando. Usaremos el caso más simple — un asistente de preguntas sobre documentos — que es la base del ejemplo [09 · RRHH](../examples/09-hr-policy-assistant/). Tiempo estimado: ~10 minutos.

## Paso 0 · Empieza desde un template (nunca lienzo en blanco)

Al abrir RAGorbit eliges **Crear desde template**. Para este tutorial: **"Asistente de preguntas sobre documentos (RAG)"**. El lienzo aparece **pre-cableado** con los nodos mínimos y valores por defecto que ya funcionan. Tu trabajo es solo personalizar 3 cosas: tus documentos, tu índice y tu API key.

> Si prefieres, el **modo guiado** te hace 4 preguntas ("¿qué quieres construir?", "¿dónde están tus docs?", "¿qué LLM?", "¿cómo entra el trabajo: chat / evento / lote?") y arma el flujo por ti.

## Paso 1 · El flujo que verás

```
 io.input ──Message──▶ retrieval.vector ──Chunks──▶ logic.prompt ──Message──▶ io.output
                            ▲                            ▲
                  Retriever │                     Model  │
              store.chroma ─┘                  model.llm ┘
                  ▲   ▲
       Documents  │   │ Embeddings
   loader.pdf ────┘   └──── model.embedding
```

Siete nodos. El template ya los trae conectados. Los puertos compatibles se iluminan al conectar, así que si mueves algo, el lienzo te guía.

## Paso 2 · Configura solo lo tuyo

Haz clic en cada nodo resaltado y llena el formulario (auto-generado, con ayuda en cada campo):

| Nodo | Campo | Qué poner |
|------|-------|-----------|
| `loader.pdf` | `path` | la carpeta con tus PDFs (o súbelos) |
| `store.chroma` | `collection` | un nombre, p.ej. `mis_docs` (Chroma es local, no requiere credenciales) |
| `model.llm` | `model` | déjalo en `anthropic:claude-opus-4-8` (default) |
| `model.llm` | `apiKeyRef` | `ANTHROPIC_API_KEY` (lo defines en el gestor de secretos) |

Todo lo demás (chunk size, topK, temperatura) tiene **defaults sensatos**. No los toques aún.

## Paso 3 · Guarda tu secreto

En **Secretos**, agrega `ANTHROPIC_API_KEY` con tu API key. Se guarda cifrado del lado servidor; **nunca** entra al Flow IR. Para *Probar con mocks* (siguiente paso) ni siquiera necesitas servicios externos.

## Paso 4 · Valida

Pulsa **Validar**. Si falta algo, el mensaje te dice exactamente qué hacer ("conecta un `Retriever` al `logic.prompt`", "falta el secreto `ANTHROPIC_API_KEY`"). No avanzas con un flujo roto.

## Paso 5 · Probar con mocks (sin desplegar nada)

Pulsa **Probar con mocks**. RAGorbit ejecuta el flujo generado en modo mock dentro de un panel de chat en el navegador. Escribe una pregunta sobre tus documentos y mira la respuesta **al instante**. Aquí los loaders/servicios usan datos de muestra, así que funciona aunque aún no hayas conectado nada real.

## Paso 6 · Exporta o despliega

- **Exportar**: descargas un `.zip` con el proyecto. Su `README.md` indica el comando exacto: `docker compose up`. Arranca en modo mock y ya puedes chatear en `localhost`.
- **Producción**: pon `MOCK=false`, completa los secretos reales y despliega el contenedor donde quieras.

## Qué acabas de lograr

Un servicio de chat RAG, en código Python portable, con tests y datos de muestra, **sin escribir código** y sin leer un manual. Ese es el listón ([06 · UX](./06-ux-principles.md)).

### A dónde ir ahora

- Agrega **citas obligatorias** con un nodo [`logic.citations`](./02-node-catalog.md#logic--razonamiento-y-reglas) → ejemplo [09](../examples/09-hr-policy-assistant/).
- Convierte el prompt en un **agente con tools** [`agent.react`](./02-node-catalog.md#agent--agentes) → ejemplo [01](../examples/01-airline-flight-change/).
- Cambia la entrada a **evento** para procesar a escala → ejemplo [10](../examples/10-logistics-disruption-rebooking/).

➡️ Siguiente: [04 · Codegen y deploy](./04-codegen-and-deploy.md).
