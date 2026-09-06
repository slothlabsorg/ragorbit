"""Consumidor opcional del topic de auditoría (docker-compose)."""
from __future__ import annotations

import json
import os
import time


def main():
    broker = os.environ.get("KAFKA_BROKER", "kafka:9092")
    topic = os.environ.get("AUDIT_TOPIC", "flight.audit")
    try:
        from kafka import KafkaConsumer  # type: ignore
    except Exception:
        print("[audit-consumer] kafka-python no instalado.")
        return
    consumer = None
    for _ in range(40):
        try:
            consumer = KafkaConsumer(
                topic,
                bootstrap_servers=broker,
                auto_offset_reset="earliest",
                value_deserializer=lambda v: json.loads(v.decode("utf-8")),
            )
            break
        except Exception:
            time.sleep(2)
    if not consumer:
        print("[audit-consumer] no conectó a Kafka.")
        return
    print(f"[audit-consumer] escuchando {topic} en {broker}")
    for msg in consumer:
        print("[AUDIT]", json.dumps(msg.value, ensure_ascii=False))


if __name__ == "__main__":
    main()
