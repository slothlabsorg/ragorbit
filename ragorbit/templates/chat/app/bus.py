"""Bus de auditoría: Kafka si hay broker, si no memoria (stdlib)."""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List


class InMemoryBus:
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
    def __init__(self, broker: str, topic: str = "flight.audit"):
        from kafka import KafkaProducer  # type: ignore

        self.topic = topic
        self.producer = KafkaProducer(
            bootstrap_servers=broker,
            value_serializer=lambda v: json.dumps(v, ensure_ascii=False).encode("utf-8"),
        )
        self._local: List[Dict[str, Any]] = []

    def publish(self, event: Dict[str, Any]) -> None:
        self.producer.send(self.topic, event)
        self.producer.flush()
        self._local.append(event)

    def drain(self) -> List[Dict[str, Any]]:
        return list(self._local)

    @property
    def events(self) -> List[Dict[str, Any]]:
        return list(self._local)


def make_bus(topic: str = "flight.audit"):
    broker = os.environ.get("KAFKA_BROKER")
    if broker:
        try:
            return KafkaBus(broker, topic)
        except Exception as exc:
            print(f"[bus] Kafka no disponible ({exc}); memoria.")
    return InMemoryBus(topic)
