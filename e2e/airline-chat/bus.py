"""Bus de eventos para el audit trail del e2e.

Usa Kafka real si está disponible (`pip install kafka-python` + env KAFKA_BROKER),
y si no, cae a un bus en memoria (stdlib) para correr el e2e sin infraestructura.
El contrato es el mismo: `publish(event: dict)` y `drain() -> list`.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List


class InMemoryBus:
    """Bus stdlib (sin deps). Suficiente para tests y demo local."""

    def __init__(self, topic: str = "flight.audit"):
        self.topic = topic
        self.events: List[Dict[str, Any]] = []

    def publish(self, event: Dict[str, Any]) -> None:
        self.events.append(event)

    def drain(self) -> List[Dict[str, Any]]:
        out = list(self.events)
        self.events.clear()
        return out


class KafkaBus:
    """Bus sobre Kafka real (requiere kafka-python y un broker corriendo)."""

    def __init__(self, broker: str, topic: str = "flight.audit"):
        from kafka import KafkaProducer  # type: ignore
        self.topic = topic
        self.producer = KafkaProducer(
            bootstrap_servers=broker,
            value_serializer=lambda v: json.dumps(v, ensure_ascii=False).encode("utf-8"))

    def publish(self, event: Dict[str, Any]) -> None:
        self.producer.send(self.topic, event)
        self.producer.flush()

    def drain(self) -> List[Dict[str, Any]]:
        return []  # en Kafka real los consume otro proceso


def make_bus(topic: str = "flight.audit"):
    """Fábrica: Kafka si hay KAFKA_BROKER + kafka-python; si no, en memoria."""
    broker = os.environ.get("KAFKA_BROKER")
    if broker:
        try:
            return KafkaBus(broker, topic)
        except Exception as exc:  # broker caído o lib ausente -> fallback
            print(f"[bus] Kafka no disponible ({exc}); usando bus en memoria.")
    return InMemoryBus(topic)
