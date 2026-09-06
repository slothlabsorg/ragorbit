# demo · Chat de aerolínea funcionando + auditoría

Carpeta para **ver cómo funciona** el bot que genera RAGorbit y **cómo se audita**:
qué herramienta se llamó, en qué orden, con qué request/response, qué decidieron
los guardrails (confirmación, idempotencia) y qué quedó en el audit trail.

## Verlo YA (sin docker, sin instalar nada)

```bash
python3 demo/run_demo.py
# o con tu propio mensaje:
python3 demo/run_demo.py "Quiero cambiar mi vuelo SCL-BOG del 15 al 17"
```

Levanta los servicios mock en un hilo, corre el bot en **dos turnos** y muestra el rastro:

1. **Turno 1 (solicitud):** llama `reservation`, `inventory`, `pricing` y deja **`payment` PENDIENTE** — el *confirm-gate* exige confirmación. **No cobra.**
2. **Turno 2 (confirmación):** el usuario dice "Sí, confirmo" → ahora **sí** llama `payment` → `TXN-0001 captured`.
3. **Idempotencia:** reintento del pago con la misma `Idempotency-Key` → **deduplicado, sin doble cobro**.
4. **Audit trail:** eventos publicados al bus (`flight.audit`) + **bitácora server-side** (`GET /audit`) con cada request recibido.

El rastro se guarda en `demo/audit/audit-sess-1.json` y `.md`.

## Cómo se audita "qué se llamó / qué pasó"

- **Rastro de cliente:** cada llamada del bot a un servicio (servicio/operación + request → response), en orden.
- **Guardrails por tool:** ves `[idempotency, confirm, resilience]` sobre `PaymentService` y su estado (`pendiente-confirmación` → `ejecutado`).
- **Bus de auditoría (`flight.audit`):** lo que iría a Kafka — un evento por interacción.
- **Bitácora server-side (`GET /audit`):** lo que **cada servicio** registró que recibió, incluida la llamada `[DEDUP]` que no recobró.

## Con Kafka REAL (docker)

```bash
cd demo
docker compose up --build
# 'demo' corre los 2 turnos contra el contenedor de servicios y publica a Kafka;
# 'audit-consumer' imprime los eventos [AUDIT] del topic flight.audit.
```

## El código generado del bot

`demo/generated/airline-chat/` es el **artefacto exportado** (mismo que descargas con *Exportar*):

```bash
cd demo/generated/airline-chat
python3 -m unittest discover -s tests
docker compose -f docker-compose.integration.yml up --build
# → http://localhost:8888
```

Guía paso a paso: [docs/07-airline-chat-walkthrough.md](../docs/07-airline-chat-walkthrough.md)
