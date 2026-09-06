# 00 · Overview

## El problema

Construir una solución de RAG o un agente con tools hoy exige pegar muchas piezas: loaders, chunking, embeddings, un vector store, un orquestador, tools hacia servicios internos, guardrails, observabilidad… y *además* decidir cómo desplegarlo. Eso deja la IA en manos de un puñado de equipos con ingenieros senior, y cada solución termina **acoplada** al framework de moda o a una plataforma cerrada.

RAGorbit existe para que **un equipo de producto, un analista o un dev no especializado en IA** pueda armar esa solución visualmente y obtener **código real, portable y desplegable** — sin quedar atrapado en la herramienta.

## La idea en tres movimientos

1. **Dibujas** el grafo en un lienzo: arrastras bloques (un loader de PDF, un vector store, un LLM, un agente, tus servicios externos como tools) y los conectas.
2. **Se guarda** como un [Flow IR](./01-concepts.md#2-flow-ir--la-especificación-portable): un JSON portable que es la única fuente de verdad. Versionable en git, revisable en un PR.
3. **Se genera** un proyecto Python ejecutable (LangGraph + LangChain) con **mocks + tests** incluidos. `docker compose up` y ya funciona; cambias `MOCK=false` para apuntar a tus servicios reales.

## Por qué "sin lock-in"

- El **artefacto generado** no depende de RAGorbit en runtime: es código que cualquiera puede leer, modificar y desplegar donde quiera.
- El **Flow IR** es un formato abierto y documentado ([01](./01-concepts.md)); podrías generarlo con otra herramienta o a mano.
- El **catálogo de nodos** es declarativo ([manifests](./01-concepts.md#7-manifests--por-qué-el-catálogo-es-extensible)): no hay lógica escondida en un core monolítico, y agregar una tecnología nueva no requiere tocar el core ([05](./05-extending.md)).

Esto es deliberadamente lo contrario a un estudio cerrado donde tu flujo solo corre dentro de su plataforma.

## Para quién es

- **Equipos sin ingenieros de IA** que necesitan un bot o un job de análisis y hoy no pueden construirlo.
- **Equipos con devs** que quieren prototipar rápido y luego **quedarse con el código** para producción.
- **Plataformas internas** que quieren un catálogo de bloques aprobados (sus servicios, sus guardrails) que el resto de la empresa reusa.

## Qué puedes construir (resumen de los 10 ejemplos)

Bots conversacionales transaccionales (cambio de vuelo, post-venta), copilots para humanos (call center), jobs de análisis (scoring de crédito, adjudicación de reclamos), RAG de alta exigencia regulatoria (mantenimiento, salud, legal) y pipelines event-driven a escala (rebooking en disrupciones). Ver el [índice de ejemplos](../README.md#-los-10-casos-de-uso-industrias-distintas).

## Cómo está hecho (vista de 10.000 pies)

| Capa | Tecnología | Rol |
|------|-----------|-----|
| Lienzo web | Next.js + React Flow | editar el grafo |
| Formularios | JSON Schema → auto-form | configurar cada nodo sin saber código |
| Fuente de verdad | Flow IR (JSON) | portabilidad, versionado |
| Catálogo | manifests declarativos | extensibilidad sin tocar el core |
| Codegen | plantillas (Jinja2) | IR → proyecto Python |
| Runtime generado | LangGraph + LangChain | agentes, RAG, tools |
| Targets | FastAPI / Kafka worker / Temporal / batch | despliegue derivado del nodo de entrada |
| Modelos | `init_chat_model` (Claude por defecto) | multi-proveedor, sin lock-in |

➡️ Siguiente: [01 · Conceptos](./01-concepts.md).
