# Cómo correr RAGorbit

> **TL;DR — no necesitas instalar ni correr docker.** Con solo Python 3.10+:
> ```bash
> python3 tools/demo.py        # corre TODO: 10 casos + e2e con servicios reales + contratos
> python3 -m ragorbit serve    # abre la webapp canvas en http://127.0.0.1:8000 (UI 100% offline)
> ```
> La UI trae React/React Flow **vendorizados** en `apps/web-lite/vendor/` — sin CDN, sin `npm install`.
> Docker, FastAPI, Next.js y un LLM real son **opcionales** (solo para producción).

RAGorbit tiene dos caminos: el **engine + demo stdlib** (corre YA, sin instalar nada) y el **stack de producción** (Next.js + FastAPI, opcional).

---

## A) Demo inmediato — sin instalar nada (stdlib puro)

Requisito: solo Python 3.10+. No requiere red, pip, ni node.

```bash
cd ragorbit

# 1) Ver el catálogo de nodos (53 tipos, 13 categorías)
python3 -m ragorbit list-nodes

# 2) Validar los 10 casos de ejemplo
python3 -m ragorbit validate examples/*/flow.json

# 3) Generar un artefacto desplegable desde un flujo
python3 -m ragorbit generate examples/01-airline-flight-change/flow.json --out build/airline

# 4) Correr el artefacto en modo mock (sin LLM ni servicios reales)
cd build/airline
python3 -m unittest discover -s tests        # tests e2e -> verde
python3 -m app.mockrun "Quiero cambiar mi vuelo SCL-BOG del 15 al 17"
```

### La webapp (canvas visual)

```bash
python3 -m ragorbit serve --port 8000      # backend stdlib + UI canvas
# abre http://127.0.0.1:8000 en el navegador
```

En la UI: elige un **template** de la galería (los 10 casos), arrástralo/edítalo en el canvas, pulsa **Validar**, **Probar con mocks** (ves la respuesta del bot al instante) y **Exportar** (descarga el proyecto `.zip` con `app/`, `mocks/`, `tests/`).

> La UI canvas (`apps/web-lite/index.html`) trae React y React Flow **vendorizados** en `apps/web-lite/vendor/`: funciona **sin red y sin `npm install`**. El backend y el codegen tampoco necesitan red.

### Verificación reproducible (CI sin deps)

```bash
python3 tools/verify.py     # valida + genera + corre tests de los 10. Debe imprimir "✅ TODO OK"
```

---

## B) Stack de producción (Next.js + React Flow + FastAPI)

Requiere instalar dependencias con `pip` y `npm`/`pnpm`.

### Backend (FastAPI)
```bash
pip install -e ".[api]"                          # fastapi + uvicorn (el engine es stdlib)
uvicorn apps.api.main:app --reload --port 8000
```

### Frontend (Next.js)
```bash
cd apps/web
pnpm install        # o npm install
pnpm dev            # http://localhost:3000  (proxy /api -> :8000)
```

El artefacto generado, en modo real:
```bash
cd <proyecto-generado>
pip install -e ".[real]"      # langgraph + langchain + langchain-anthropic
export MOCK=false
export ANTHROPIC_API_KEY=...  # y demás secretos del .env.template
python -m app.main
# o: docker compose up
```

---

## C) ¿Qué necesitas instalar? Para ver RAGorbit funcionando, NADA.

Todo lo esencial corre con Python stdlib y ya está ejecutado y verificado:
- ✅ engine, validador, contratos, codegen, runtime mock
- ✅ los 10 casos: validan + generan artefacto + 70 tests en verde (`tools/verify.py`)
- ✅ e2e del chat de aerolínea con **servicios HTTP reales** + idempotencia (`e2e/airline-chat`)
- ✅ webapp canvas **offline** (`ragorbit serve`)
- ✅ backend API (vía `ragorbit serve`, mismos endpoints que FastAPI)

**Opcional, solo para producción** (no hace falta para el demo):
- **Kafka real** en el e2e: `cd e2e/airline-chat && docker compose up --build`.
- **FastAPI**: `pip install -e ".[api]" && uvicorn apps.api.main:app` (mismos endpoints que el server stdlib).
- **Next.js**: `cd apps/web && pnpm install && pnpm dev` (variante de producción del canvas).
- **LLM real** en un artefacto: `pip install -e ".[real]"`, `MOCK=false`, `ANTHROPIC_API_KEY=...`.

> El camino por defecto es 100% stdlib **por diseño**, no por limitación: quien clona
> el repo tiene que poder ver RAGorbit funcionando sin instalar nada ni pelearse con
> un proxy corporativo. Docker y pip son para producción.
