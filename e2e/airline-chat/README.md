# E2E · Chat de aerolínea con servicios corriendo

Prueba de extremo a extremo del escenario **agente de cambio de vuelo** con
**servicios HTTP reales** y **Kafka** corriendo — no el mock en-proceso, sino los
servicios levantados como procesos/contenedores, llamados por el bot que genera RAGorbit.

## Qué demuestra

- El bot de RAGorbit (flujo `examples/01-airline-flight-change`) ejecutándose en **modo integración**: cada `tool.service` hace HTTP real a su servicio.
- **Contratos** por servicio: `reservation/lookup`, `inventory/search`, `pricing/quote`, `payment/charge`, `policy-rag/search`.
- **Idempotencia** del pago: dos `charge` con la misma `Idempotency-Key` ⇒ un solo cobro.
- **Confirm-gate**: el bot pide confirmación antes de cobrar.
- **Audit trail** publicado a **Kafka** (topic `flight.audit`), consumido y mostrado.

## Correr sin nada instalado (stdlib, sin red ni docker)

```bash
cd e2e/airline-chat
python3 -m unittest discover -s tests        # levanta los servicios en threads y valida el flujo -> OK
```

O manualmente:
```bash
python3 services/mock_services.py 8900 &      # servicios reales en :8900
python3 run_bot.py "Quiero cambiar mi vuelo SCL-BOG del 15 al 17"
```

## Correr con Kafka real (docker)

```bash
cd e2e/airline-chat
docker compose up --build
# kafka (redpanda) + servicios + audit-consumer + bot
# verás en logs del bot la conversación, y en audit-consumer los eventos [AUDIT] del topic flight.audit
```

## Piezas

- `services/mock_services.py` — los 5 servicios con sus contratos; pago idempotente por `Idempotency-Key`.
- `bus.py` — bus de auditoría: **Kafka** si hay `KAFKA_BROKER`, si no en memoria.
- `run_bot.py` — corre el flujo de RAGorbit en modo integración (HTTP real + bus).
- `audit_consumer.py` — consume e imprime el topic `flight.audit`.
- `tests/test_e2e.py` — test e2e ejecutable (servicios en threads).
- `docker-compose.yml` — stack con Kafka real.

> Para el stack completo de dev (pgvector, Qdrant, Neo4j, Kafka, gateway), ver [`infra/`](../../infra/).
