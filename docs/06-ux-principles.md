# 06 · Principios de UX — éxito al primer intento, sin manual

> El listón de aceptación de RAGorbit: **una persona que nunca usó la herramienta debe poder construir cualquiera de los [10 casos](../README.md#-los-10-casos-de-uso-industrias-distintas) y llegar a un artefacto que corre, sin leer documentación.** Cada decisión de producto se mide contra esto.

## Los 8 principios

### 1. Nunca un lienzo en blanco
Se arranca desde **templates** (los 10 casos + "desde cero"). El template viene **pre-cableado** y solo pide lo mínimo (tus docs, tu índice, tu API key). El lienzo vacío es para expertos, no el punto de entrada.

### 2. Modo guiado (wizard) como primera puerta
"¿Qué quieres construir?" → 4 preguntas (objetivo, dónde están los datos, qué LLM, cómo entra el trabajo) → RAGorbit **arma el flujo**. La curva de aprendizaje del lienzo es opcional, no obligatoria.

### 3. Defaults inteligentes + divulgación progresiva
Cada nodo trae valores por defecto que **ya funcionan** (chunk size, topK, temperatura, Claude como modelo). La config avanzada se esconde tras "Avanzado". El usuario solo ve lo que debe decidir.

### 4. Ayuda en contexto, no documentación externa
Cada nodo y cada campo trae descripción + ejemplo (vienen del `manifest`/`configSchema`). Tooltips e *inline hints*. Si tienes que abrir el manual, fallamos.

### 5. Validación en tiempo real y **accionable**
Los mensajes dicen *qué hacer*, no *qué está mal*:
- ❌ "Edge inválido" → ✅ "Conecta un **Retriever** a la entrada del nodo *Síntesis*."
- ❌ "Falta config" → ✅ "Define el secreto **ANTHROPIC_API_KEY** en Secretos."
- ❌ "Agente sin tools" → ✅ "Este agente no tiene tools; arrastra un **tool.service** o un **tool.retriever**."
Los puertos compatibles se **iluminan** al arrastrar una conexión; no puedes crear una conexión inválida.

### 6. Probar **sin desplegar**
Botón **"Probar con mocks"**: ejecuta el flujo generado en modo mock dentro de un panel de chat/preview en el navegador. El usuario ve el resultado **al instante**, sin deploy, sin servicios reales, sin secretos de terceros. El "¿funciona?" se responde en segundos, no en horas.

### 7. Exportar con instrucciones exactas
El `.zip` trae un `README.md` con el comando preciso (`docker compose up`) y arranca en modo mock. De diseño a "lo estoy usando" sin pasos implícitos.

### 8. Red de seguridad: estados vacíos, undo/redo, autosave
Estados vacíos que explican el siguiente paso; deshacer/rehacer en el lienzo; autoguardado del Flow IR. Equivocarse nunca es costoso.

## Cómo se mide (prueba de "primer intento")

Para **cada** uno de los 10 ejemplos existe una prueba de usabilidad: una persona sin contexto sigue el `README` del ejemplo y debe llegar a un artefacto corriendo con mocks **sin preguntar**. Los ejemplos más sensibles a esta prueba son [09 · RRHH](../examples/09-hr-policy-assistant/) (el más simple) y el tutorial [03](./03-build-first-flow.md): si esos no se leen como "cero-a-resultado" sin saltos, hay un defecto de UX que arreglar.

## Anti-patrones que evitamos

- Pedir al usuario que "elija el deployment target" → se **deriva** del nodo de entrada.
- Pedir credenciales para *probar* → el modo mock no las necesita.
- Errores genéricos de validación → siempre accionables.
- Empezar en blanco → siempre desde template/wizard.
- Documentación obligatoria para tareas comunes → ayuda en contexto.

➡️ Volver al [índice](../README.md) · Ver los [ejemplos](../README.md#-los-10-casos-de-uso-industrias-distintas).
