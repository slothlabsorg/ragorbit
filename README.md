# 🛰️ RAGorbit

[![CI](https://github.com/slothlabsorg/ragorbit/actions/workflows/ci.yml/badge.svg)](https://github.com/slothlabsorg/ragorbit/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](./LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![Sin dependencias](https://img.shields.io/badge/dependencias-0-brightgreen.svg)](./pyproject.toml)

**Constructor visual de estrategias RAG y agénticas — que genera código desplegable, sin lock-in.**

🌐 **[slothlabs.org/ragorbit](https://slothlabs.org/ragorbit)** · 📖 **[Docs](https://slothlabs.org/ragorbit/docs)** · 🎓 **[Curso gratis (ES/EN)](https://slothlabs.org/rag-course)**

RAGorbit es una herramienta web tipo lienzo (drag & drop) donde un equipo —**sin necesidad de ser ingenieros de AI**— arma una estrategia de IA conectando bloques: cargas tus documentos, eliges un vector store o un knowledge graph, conectas tus servicios externos, pones la API key de tu LLM, agregas reglas y guardrails… y al final **RAGorbit genera un proyecto Python listo para desplegar**, que ya viene con **servicios mock y tests** para que funcione el primer día.

> Dibujas el grafo → se guarda como un **JSON portable (Flow IR)** → un generador lo convierte en un **artefacto ejecutable** (LangGraph + LangChain). El artefacto es código normal: corre **sin** RAGorbit. **Cero acoplamiento a la herramienta.**

```
   Lienzo (drag & drop)          Flow IR (JSON portable)         Artefacto desplegable
 ┌───────────────────┐        ┌──────────────────────┐        ┌──────────────────────┐
 │  ◻── ◻── ◻         │  ───▶  │ { nodes, edges,       │  ───▶  │ app/ mocks/ tests/    │
 │   \   |   /        │        │   secrets }           │        │ docker-compose.yml    │
 │      ◻             │        └──────────────────────┘        └──────────────────────┘
 └───────────────────┘            fuente de verdad               `docker compose up`
```

---

## ⬇️ Instalar

```bash
# Un solo archivo, cualquier python3 — sin pip, sin venv, sin dependencias
curl -fsSL https://slothlabs.org/install/ragorbit | sh

# o con Homebrew
brew install slothlabsorg/tap/ragorbit

# o con pipx / pip
pipx install ragorbit
```

También puedes bajar `ragorbit.pyz` de [Releases](https://github.com/slothlabsorg/ragorbit/releases)
y correrlo tal cual: `python3 ragorbit.pyz list-nodes`.

Se puede distribuir así porque **el engine no tiene dependencias**: catálogo,
validador, contratos, codegen y runtime mock son stdlib pura.

---

## ✅ Estado: sistema funcional

Este repo contiene **el libro de documentación + los 10 casos + el sistema RAGorbit implementado y verificado**. El curso vive en [`slothlabsorg/rag-course`](https://github.com/slothlabsorg/rag-course):

- **Engine** (`ragorbit/`, Python stdlib, **sin dependencias**): spec (JSON Schema), validador, catálogo de **53 tipos de nodo**, registro extensible, codegen y runtime mock.
- **CLI**: `python -m ragorbit {list-nodes | validate | generate | serve}`.
- **Webapp canvas** (`apps/web-lite/`): paleta, galería de los 10 templates, validación de conexiones por tipo, **Probar con mocks** y **Exportar** (zip). Servida por un backend stdlib (`python -m ragorbit serve`).
- **Stack de producción**: backend FastAPI (`apps/api/`) y frontend Next.js + React Flow (`apps/web/`).
- **Artefactos generados**: proyecto Python con `app/` + `mocks/` + `tests/`, que corre en **modo mock sin red ni LLM** y se promueve a modo real (LangChain/LangGraph) con una variable de entorno.

- **E2E con servicios corriendo** (`e2e/airline-chat/`): el bot llama **servicios HTTP reales** con sus contratos, **pago idempotente** y audit trail a **Kafka** (real vía docker, o en memoria sin nada). Corre en threads sin docker ni red.
- **Conciencia de contratos** (`ragorbit/contracts.py`): RAGorbit **no genera a lo loco** — rechaza flujos que no funcionarían (agente sin tools, store sin embeddings, guardrail que no envuelve un tool, secretos/auth faltantes).

**Verificación — un solo comando, sin instalar nada (ni docker):**
```bash
python3 tools/demo.py     # 10 casos (70 tests) + e2e con servicios reales + rechazo por contrato
python3 demo/run_demo.py  # demo narrativa aerolínea + auditoría (local)
```
**Artefacto exportado (chat aerolínea) con Docker realista:**
```bash
python3 tools/test_airline_docker.py   # genera + docker compose + 2 turnos HTTP
```
👉 **Cómo correrlo:** [RUNNING.md](./RUNNING.md). Webapp: `python3 -m ragorbit serve` → `http://127.0.0.1:8000` (UI **100% offline**, sin CDN ni `npm install`).

---

## 📖 El libro

| # | Capítulo | Para qué |
|---|----------|----------|
| 00 | [Overview](./docs/00-overview.md) | Filosofía, para quién es, cómo funciona de punta a punta |
| 01 | [Conceptos](./docs/01-concepts.md) | **El contrato**: Flow IR, nodos, puertos/tipos, secretos, deployment targets |
| 02 | [Catálogo de nodos](./docs/02-node-catalog.md) | **El libro de bloques**: todos los tipos de nodo con puertos y config |
| 03 | [Construye tu primer flujo](./docs/03-build-first-flow.md) | Tutorial cero-a-resultado (modo guiado, defaults, "Probar con mocks") |
| 04 | [Codegen y deploy](./docs/04-codegen-and-deploy.md) | Qué genera, cómo correrlo con mocks y desplegarlo |
| 05 | [Extender el catálogo](./docs/05-extending.md) | Agregar una tecnología nueva = un manifest + un emisor + un mock |
| 06 | [Principios de UX](./docs/06-ux-principles.md) | Cómo se logra el "éxito al primer intento, sin manual" |
| 07 | [Chat aerolínea: lienzo → prod](./docs/07-airline-chat-walkthrough.md) | **Tutorial video**: cada bloque, export, docker, GCP |

---

## 🧪 Los 10 casos de uso (industrias distintas)

Cada uno trae un `README.md` con: problema, arquitectura (diagrama), **construcción paso a paso**, config de cada nodo, secretos, qué genera y **cómo probarlo con mocks**. Más un `flow.json` (el Flow IR de ejemplo).

| # | Industria | Caso | Target | Conceptos destacados |
|---|-----------|------|--------|----------------------|
| 01 | Aerolíneas | [Agente de cambio de vuelo](./examples/01-airline-flight-change/) | chat-service | tools, idempotencia, confirm-gate, audit |
| 02 | Banca | [Evaluación de potencial de crédito](./examples/02-banking-credit-scoring/) | batch | ingesta PDF/tabular, salida estructurada |
| 03 | Salud | [Asistente de pre-autorización](./examples/03-healthcare-prior-auth/) | chat-service | filtros duros, HITL, citas |
| 04 | Seguros | [Adjudicación de reclamos](./examples/04-insurance-claims/) | batch | multimodal (vision), reglas + citas |
| 05 | Legal | [Revisión de contratos](./examples/05-legal-contract-review/) | chat-service | multi-index, riesgos con citas |
| 06 | Retail | [Bot de post-venta](./examples/06-retail-postsale-bot/) | chat-service | tools Order/Return, guardrail de monto |
| 07 | Telecom | [Copilot de call center](./examples/07-telecom-callcenter-copilot/) | chat-service | STT, intent, multi-index, feedback loop |
| 08 | Manufactura | [RAG técnico de mantenimiento](./examples/08-manufacturing-maintenance-rag/) | chat-service | multimodal, citas obligatorias, HITL |
| 09 | RRHH | [Asistente de políticas/beneficios](./examples/09-hr-policy-assistant/) | chat-service | el más simple → "primer intento" |
| 10 | Logística | [Rebooking en disrupción](./examples/10-logistics-disruption-rebooking/) | event-worker | Kafka, fan-out stateless, auto-confirm vs LLM |

> ¿Primera vez? Lee [03 · Construye tu primer flujo](./docs/03-build-first-flow.md) y luego el ejemplo [09 · RRHH](./examples/09-hr-policy-assistant/) — son el camino más corto a un resultado funcionando.

---

## 🧭 Principios

- **Sin lock-in** — el artefacto generado es Python estándar (LangGraph/LangChain) y corre solo.
- **Funciona el día 1** — todo artefacto trae mocks + tests; `docker compose up` y ya chateas.
- **Extensible por diseño** — agregar una tecnología = un manifest declarativo, sin tocar el core.
- **Claude por defecto** — vía `init_chat_model`, así que cambiar de modelo o de proveedor es cambiar una cadena. Multi-proveedor por diseño.
- **UX de primer intento** — empiezas desde un template, con defaults sensatos y validación que te dice qué hacer.

---

## 🎓 El curso

RAGorbit tiene un curso propio, gratis y bilingüe, que enseña desde cero todo lo que
la herramienta usa — cada tema anclado a un nodo del catálogo y a uno de los 10
templates, con talleres que se ejecutan en el navegador:

**[slothlabs.org/rag-course](https://slothlabs.org/rag-course)** · repo: [`slothlabsorg/rag-course`](https://github.com/slothlabsorg/rag-course)

Doce módulos (M0–M11) más una base de conocimiento vendor-neutral, cada tema en tres
capas: concepto → desde cero en Python puro → framework real.

---

## 🤝 Contribuir

Agregar una tecnología al catálogo son tres piezas pequeñas y ningún cambio en el
core: un manifest, un emisor de código y un behavior mock. La receta completa está en
[docs/05 · Extender el catálogo](./docs/05-extending.md).

Antes de abrir un PR:

```bash
python3 tools/verify.py    # los 10 casos: validan, generan, tests mock verdes, código real auditado
python3 tools/demo.py      # + e2e con servicios HTTP reales + rechazo por contrato
```

`verify.py` audita también el código real generado: falla si un nodo queda vacío, como
un `return state`, o lanzando `NotImplementedError`. Un nodo que no hace nada es un
fallo de CI, no un detalle que se descubre en producción.

## Licencia

[MIT](./LICENSE) · hecho por [SlothLabs](https://slothlabs.org)
