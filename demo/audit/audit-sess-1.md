# Auditoría · sesión sess-1

- **Generado:** 2026-06-15T17:35:42

## Turno 1 — solicitud (no cobra)

- **Usuario:** Quiero cambiar mi vuelo SCL-BOG del 15 al 17
- **Bot:** He procesado: «Quiero cambiar mi vuelo SCL-BOG del 15 al 17». Consulté: policy_rag, ReservationService, InventoryService, PricingService. [fuente: policy_pdf#sec1] El costo total es USD 130. ¿Confirmas la operación?

| # | servicio/op | response | guardrail |
|---|---|---|---|
| 1 | `reservation/lookup` | `{"pnr": "ABC123", "route": "SCL-BOG", "date": "2026-06-15", "fareClass": "Plus", "passenger": "J. Pérez"}` |  |
| 2 | `inventory/search` | `{"options": [{"flightId": "LA-441", "date": "2026-06-17", "seats": 9}, {"flightId": "LA-447", "date": "2026-06-17", "seats": 3}]}` |  |
| 3 | `pricing/quote` | `{"currency": "USD", "penalty": 50, "fareDifference": 80, "amount": 130}` |  |
| – | `PaymentService` | _no ejecutado_ | ⚠ pendiente-confirmación |

## Turno 2 — confirmación (cobra)

- **Usuario:** Sí, confirmo el cambio.
- **Bot:** He procesado: «Sí, confirmo el cambio.». Consulté: policy_rag, ReservationService, InventoryService, PricingService, PaymentService. [fuente: policy_pdf#sec1] Operación confirmada y ejecutada.

| # | servicio/op | response | guardrail |
|---|---|---|---|
| 1 | `reservation/lookup` | `{"pnr": "ABC123", "route": "SCL-BOG", "date": "2026-06-15", "fareClass": "Plus", "passenger": "J. Pérez"}` |  |
| 2 | `inventory/search` | `{"options": [{"flightId": "LA-441", "date": "2026-06-17", "seats": 9}, {"flightId": "LA-447", "date": "2026-06-17", "seats": 3}]}` |  |
| 3 | `pricing/quote` | `{"currency": "USD", "penalty": 50, "fareDifference": 80, "amount": 130}` |  |
| 4 | `payment/charge` | `{"txnId": "TXN-0001", "amount": 130, "currency": "USD", "status": "captured", "deduplicated": false}` |  |

## Idempotencia

Reintento del pago con la misma key → `{"txnId": "TXN-0001", "amount": 130, "currency": "USD", "status": "captured", "deduplicated": true}` (**deduplicado, sin doble cobro**).

## Eventos de auditoría (bus / Kafka)

- `{"node": "audit", "sink": "kafka", "payload": "He procesado: «Quiero cambiar mi vuelo SCL-BOG del 15 al 17». Consulté: policy_rag, ReservationService, InventoryService, PricingService. [fuente: policy_pdf#sec1] El costo total es USD 130. ¿Confirmas la operación?"}`
- `{"node": "audit", "sink": "kafka", "payload": "He procesado: «Sí, confirmo el cambio.». Consulté: policy_rag, ReservationService, InventoryService, PricingService, PaymentService. [fuente: policy_pdf#sec1] Operación confirmada y ejecutada."}`

## Bitácora server-side

| # | servicio/op | dedup |
|---|---|---|
| 1 | `reservation/lookup` |  |
| 2 | `inventory/search` |  |
| 3 | `pricing/quote` |  |
| 4 | `reservation/lookup` |  |
| 5 | `inventory/search` |  |
| 6 | `pricing/quote` |  |
| 7 | `payment/charge` |  |
| 8 | `payment/charge` | sí |
