# infra · Servicios para probar/generar con RAGorbit

Stack de desarrollo con **todo lo que un flujo puede necesitar en modo real**. El
**modo mock no requiere nada de esto** (corre con stdlib). Úsalo cuando quieras
ejecutar un artefacto generado contra backends reales (`MOCK=false`).

```bash
docker compose -f infra/docker-compose.yml up -d
```

| Servicio | Para | Puerto | Credenciales |
|----------|------|--------|--------------|
| postgres (pgvector) | `store.pgvector` | 5432 | ragorbit / ragorbit |
| qdrant | `store.qdrant` | 6333 | — |
| neo4j | `store.neo4j` (GraphRAG) | 7474 / 7687 | neo4j / ragorbit123 |
| kafka (redpanda) | `io.event-source`, `observability.audit` | 9092 | — |
| mock-services | `tool.service` (Reservation/Inventory/Pricing/Payment/PolicyRAG) | 8900 | — |

Variables de entorno típicas para un artefacto en modo real:
```bash
export MOCK=false
export DATABASE_URL=postgresql://ragorbit:ragorbit@localhost:5432/ragorbit
export QDRANT_URL=http://localhost:6333
export NEO4J_URI=bolt://localhost:7687
export NEO4J_AUTH=neo4j/ragorbit123
export KAFKA_BROKER=localhost:9092
export ANTHROPIC_API_KEY=...    # tu API key del LLM
```

> Para el e2e concreto del chat de aerolínea (con Kafka + idempotencia), ver [`e2e/airline-chat/`](../e2e/airline-chat/).
