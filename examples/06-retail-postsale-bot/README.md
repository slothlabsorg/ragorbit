# 06 · Bot de post-venta retail

## 1. Problema / industria y a quién sirve

**Industria:** E-commerce / retail en línea.

**Problema:** Después de completar una compra, el cliente tiene preguntas que antes requerían llamar a un agente humano o navegar paneles complejos: _¿dónde está mi pedido?_, _quiero devolver este artículo_, _¿qué más me recomiendan?_ Los tiempos de espera en soporte son altos, los costos por contacto son elevados y la satisfacción post-venta impacta directamente la recompra.

**A quién sirve:**
- **Clientes finales** que quieren autoservicio inmediato en cualquier canal (web, app, WhatsApp).
- **Equipos de soporte** que necesitan descargar volumen de consultas repetitivas y reservar agentes humanos para casos complejos.
- **Producto y datos** que buscan un audit trail completo de cada interacción para analizar motivos de devolución y mejorar recomendaciones.

---

## 2. Resultado esperado

Un cliente escribe su email (o ID de pedido) en el chat y el bot:

1. Trae automáticamente el historial y el estado actual de sus pedidos.
2. Ofrece iniciar una devolución; si el reembolso supera **$200**, pide confirmación explícita antes de ejecutar.
3. La operación de devolución es **idempotente**: si el cliente envía el mismo mensaje dos veces (doble clic, reconexión), no se generan dos devoluciones.
4. Sugiere productos complementarios al pedido consultado.
5. Cada tool call queda registrado en el audit trail para trazabilidad y análisis posterior.

Todo el flujo corre en **streaming markdown** con autenticación JWT.

---

## 3. Arquitectura (ASCII con puertos)

```
                         Model (Model)
  llm ──────────────────────────────────────────────────────▶┐
                                                              │
  chat_input ──(Message)──▶ postsale_agent ◀──(Tool)── order_tool
                                  │   ▲
                                  │   └──(Tool)── return_idempotency ◀──(Tool)── return_confirm ◀──(Tool)── return_tool
                                  │
                                  ├──(Tool)── recommendation_tool
                                  │
                                  └──(Message)──▶ audit ──(Any)──▶ chat_output
                                  ↑loop
                                  └──────────────────────────────────────────────────────────────(Message, loop:true)

Cadena de guardrails para ReturnService:
  return_tool ──(Tool)──▶ return_confirm ──(Tool)──▶ return_idempotency ──(Tool)──▶ postsale_agent

Puertos involucrados:
  io.input          → sourcePort: Message
  model.llm         → sourcePort: Model
  tool.service      → sourcePort: Tool
  guardrail.confirm → targetPort: Tool / sourcePort: Tool
  guardrail.idempotency → targetPort: Tool / sourcePort: Tool
  agent.react       → targetPort: Model, Tool (n), Message / sourcePort: Message
  observability.audit → targetPort: Any / sourcePort: Any
  io.output         → targetPort: Any
```

---

## 4. Construirlo paso a paso

**Paso 1 — Nodo de entrada**
Arrastra `io.input` al lienzo. Configura `channel: chat`, `auth: jwt`, `streaming: true`. RAGorbit derivará automáticamente `deploymentTarget: chat-service`.

**Paso 2 — Modelo**
Añade `model.llm`. El default `anthropic:claude-opus-4-8` es adecuado para razonamiento multi-turno. Conecta su puerto `Model →` al puerto `→ Model` del agente (paso 5).

**Paso 3 — Tools de negocio**
Añade tres nodos `tool.service`:
- `OrderService` — operación `getOrdersByCustomer`.
- `ReturnService` — operación `initiateReturn`.
- `RecommendationService` — operación `getRecommendations`.

Cada uno expone un puerto `Tool →` que más adelante conectarás al agente (directamente o a través de guardrails).

**Paso 4 — Cadena de guardrails sobre ReturnService**
El puerto `Tool →` de `ReturnService` no va directo al agente; primero pasa por dos guardrails en serie:
1. Arrastra `guardrail.confirm`. Conecta `ReturnService.Tool →` a `→ Tool` del confirm. Configura `threshold: "amount > 200"`.
2. Arrastra `guardrail.idempotency`. Conecta `confirm.Tool →` a `→ Tool` del idempotency. Configura `keyFields: [order_id, session_id]`.
3. Conecta `idempotency.Tool →` al agente.

**Paso 5 — Agente ReAct**
Arrastra `agent.react`. Conecta: `chat_input.Message →`, `llm.Model →`, los tres tools (incluyendo el extremo de `idempotency` para ReturnService). Escribe el prompt de sistema.

**Paso 6 — Observabilidad**
Añade `observability.audit`. Conecta `postsale_agent.Message →` a `→ Any` del audit. Activa `sink: log`.

**Paso 7 — Salida**
Añade `io.output`. Conecta `audit.Any →` a `→ Any` de output. Configura `format: markdown`, `streaming: true`.

**Paso 8 — Secretos**
Declara los cuatro nombres de secreto en la sección `secrets[]` del Flow IR. Nunca pongas valores.

---

## 5. Config de cada nodo (tabla)

| Nodo | `type` | Campo clave | Valor |
|------|--------|-------------|-------|
| chat_input | `io.input` | `channel` | `chat` |
| | | `auth` | `jwt` |
| | | `streaming` | `true` |
| llm | `model.llm` | `model` | `anthropic:claude-opus-4-8` |
| | | `temperature` | `0.2` |
| | | `apiKeyRef` | `ANTHROPIC_API_KEY` |
| order_tool | `tool.service` | `name` | `OrderService` |
| | | `baseUrl` | `https://api.retail.internal/orders` |
| | | `operation` | `getOrdersByCustomer` |
| return_tool | `tool.service` | `name` | `ReturnService` |
| | | `baseUrl` | `https://api.retail.internal/returns` |
| | | `operation` | `initiateReturn` |
| return_confirm | `guardrail.confirm` | `threshold` | `amount > 200` |
| | | `message` | _"El reembolso supera $200. ¿Confirmas...?"_ |
| return_idempotency | `guardrail.idempotency` | `keyFields` | `[order_id, session_id]` |
| | | `ttl` | `24h` |
| recommendation_tool | `tool.service` | `name` | `RecommendationService` |
| | | `baseUrl` | `https://api.retail.internal/recommendations` |
| | | `operation` | `getRecommendations` |
| postsale_agent | `agent.react` | `system` | Prompt de post-venta (ver flow.json) |
| | | `maxSteps` | `8` |
| | | `streaming` | `true` |
| audit | `observability.audit` | `sink` | `log` |
| | | `topic` | `postsale-audit` |
| chat_output | `io.output` | `format` | `markdown` |
| | | `streaming` | `true` |

---

## 6. Secretos (solo nombres)

```
ANTHROPIC_API_KEY        — modelo LLM
ORDER_SERVICE_API_KEY    — OrderService
RETURN_SERVICE_API_KEY   — ReturnService
RECOMMENDATION_API_KEY   — RecommendationService
```

El codegen produce un `.env.template` con estos nombres. En modo mock (`MOCK=true`) los tres secretos de servicios externos son opcionales; solo `ANTHROPIC_API_KEY` es necesario si el LLM no está mockeado.

---

## 7. Qué genera el codegen

```
06-retail-postsale-bot/
├── app/
│   ├── main.py                   # FastAPI con SSE streaming
│   ├── agent.py                  # create_agent() con herramientas registradas
│   ├── tools/
│   │   ├── order_service.py      # cliente HTTP + esquema I/O
│   │   ├── return_service.py     # cliente HTTP + esquema I/O
│   │   └── recommendation_service.py
│   └── guardrails/
│       ├── confirm.py            # lógica threshold amount > 200
│       └── idempotency.py        # cache con TTL 24h por order_id+session_id
├── mocks/
│   ├── order_service_mock.py     # devuelve pedidos de muestra por email/order_id
│   ├── return_service_mock.py    # simula devolución exitosa y caso de duplicado
│   └── recommendation_service_mock.py  # catálogo fijo de productos sugeridos
├── tests/
│   ├── test_order_flow.py        # consulta pedidos por email
│   ├── test_return_below_threshold.py  # devolución < $200 sin confirmación
│   ├── test_return_above_threshold.py  # devolución > $200 exige confirmación
│   └── test_return_idempotency.py      # segunda llamada igual no duplica devolución
├── fixtures/
│   ├── orders.yaml               # pedidos de muestra (cliente demo@example.com)
│   └── returns.yaml              # respuestas mock de devolución
├── .env.template
├── Dockerfile
└── docker-compose.yml            # levanta la app + mocks en un solo `docker compose up`
```

La suite de tests cubre los cuatro escenarios clave del caso de uso sin necesidad de conectar servicios reales.

---

## 8. Probarlo con mocks (comandos + entrada + salida)

### Levantar el entorno

```bash
# Generar el artefacto (desde el directorio ragorbit)
ragorbit codegen examples/06-retail-postsale-bot/flow.json --out /tmp/postsale

# Levantar con mocks activados
cd /tmp/postsale
MOCK=true docker compose up
# → API disponible en http://localhost:8000
```

### Escenario A — Consulta de pedido por email

```bash
curl -N -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <jwt-test-token>" \
  -d '{"message": "Hola, mi email es demo@example.com. ¿Cuál es el estado de mis pedidos?"}'
```

**Salida esperada (streaming markdown):**
```
Hola, encontré tus pedidos más recientes:

| # | Pedido | Fecha | Estado | Total |
|---|--------|-------|--------|-------|
| 1 | ORD-1001 | 2026-06-10 | **En tránsito** | $85.00 |
| 2 | ORD-0998 | 2026-05-28 | **Entregado** | $240.00 |

¿Te gustaría ver más detalles de alguno o necesitas ayuda con una devolución?
```

### Escenario B — Devolución por debajo del umbral (sin confirmación)

```bash
curl -N -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <jwt-test-token>" \
  -d '{"message": "Quiero devolver el pedido ORD-1001, el artículo llegó dañado."}'
```

**Salida esperada:**
```
Entendido. He iniciado la devolución del pedido ORD-1001 ($85.00).

- **ID de devolución:** RET-4421
- **Motivo registrado:** artículo dañado
- **Reembolso estimado:** $85.00 en 3-5 días hábiles

¿Hay algo más en lo que pueda ayudarte?
```

_(El reembolso es $85 < $200, el guardrail de confirmación no se activa.)_

### Escenario C — Devolución por encima del umbral (pide confirmación)

```bash
curl -N -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <jwt-test-token>" \
  -d '{"message": "Quiero devolver el pedido ORD-0998."}'
```

**Salida esperada (turno 1 — bot pide confirmación):**
```
El pedido ORD-0998 tiene un total de $240.00.

El reembolso supera $200. ¿Confirmas que deseas iniciar la devolución por este monto?

Responde **sí** para continuar o **no** para cancelar.
```

```bash
# El cliente responde "sí"
curl -N -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <jwt-test-token>" \
  -d '{"message": "sí"}'
```

**Salida esperada (turno 2 — devolución ejecutada):**
```
Perfecto. He iniciado la devolución del pedido ORD-0998 ($240.00).

- **ID de devolución:** RET-4422
- **Reembolso estimado:** $240.00 en 3-5 días hábiles

¿Te puedo ayudar con algo más?
```

### Escenario D — Idempotencia (envío duplicado)

```bash
# Mismo mensaje dos veces (simula doble clic o reconexión)
for i in 1 2; do
  curl -s -X POST http://localhost:8000/chat \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer <jwt-test-token>" \
    -d '{"message": "Confirmo, inicia la devolución de ORD-0998", "session_id": "sess-abc123"}'
done
```

**Salida esperada (ambas llamadas retornan el mismo ID de devolución, sin duplicar):**
```
RET-4422  ← primera llamada (devolución creada)
RET-4422  ← segunda llamada (operación idempotente, misma respuesta)
```

---

## 9. Conceptos staff-level

### Traer contexto del cliente con solo id/email

El agente recibe únicamente el email o el ID del pedido y desde ese dato único recupera todo el historial relevante. Este patrón — _context hydration_ — reduce drásticamente la fricción: el cliente no tiene que repetir su situación ni el agente humano de escalada tiene que buscar en múltiples sistemas. El `OrderService` actúa como agregador; el LLM sintetiza la información en lenguaje natural.

### Guardrail de monto en reembolsos

`guardrail.confirm` implementa el patrón _human-in-the-loop ligero_: no escala a un humano, pero sí interrumpe la ejecución del tool y devuelve control al usuario para que valide explícitamente. El umbral (`amount > 200`) es un parámetro de negocio configurable sin tocar código. La confirmación se resuelve en el mismo turno de conversación; el agente reanuda automáticamente al recibir la respuesta afirmativa. Esto es esencial en transacciones financieras donde la reversión es costosa.

### Idempotencia en transacciones

`guardrail.idempotency` envuelve el tool de devolución con una caché de operaciones ejecutadas, indexada por `(order_id, session_id)` con TTL de 24 horas. Si el mismo par de claves llega dos veces (por reconexión del cliente, reintento del frontend o doble clic), el guardrail devuelve el resultado almacenado en lugar de ejecutar de nuevo el tool. El servicio subyacente no necesita implementar su propia idempotencia. Este patrón es el mismo que usan sistemas de pagos como Stripe con `Idempotency-Key`: la clave garantiza _at-most-once semantics_ a nivel de operación de negocio.

### Audit trail como requisito no funcional

`observability.audit` no es logging de aplicación genérico: persiste específicamente cada _tool call_ con su input, output y timestamp. En un contexto de e-commerce, esto es la fuente de verdad regulatoria en disputas de clientes, el insumo para análisis de motivos de devolución y la base para detectar fraude (p.ej. patrones de devolución repetida por el mismo email). Al estar separado del agente como nodo independiente, es posible cambiar el sink (`log` → `kafka`) sin tocar la lógica del agente.

---

⬅️ [Índice](../../README.md)
