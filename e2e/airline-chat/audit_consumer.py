"""Consumidor del audit trail (topic flight.audit). Imprime cada evento que el bot
publica a Kafka — demuestra la trazabilidad regulatoria del escenario.
Requiere kafka-python y un broker (env KAFKA_BROKER). Solo se usa en docker-compose.
"""
from __future__ import annotations

import json
import os
import time


def main():
    broker = os.environ.get("KAFKA_BROKER", "kafka:9092")
    try:
        from kafka import KafkaConsumer  # type: ignore
    except Exception:
        print("[audit-consumer] kafka-python no instalado; nada que consumir.")
        return
    # reintenta hasta que el broker esté disponible
    consumer = None
    for _ in range(30):
        try:
            consumer = KafkaConsumer("flight.audit", bootstrap_servers=broker,
                                     auto_offset_reset="earliest",
                                     value_deserializer=lambda v: json.loads(v.decode("utf-8")))
            break
        except Exception:
            time.sleep(2)
    if not consumer:
        print("[audit-consumer] no se pudo conectar a Kafka."); return
    print(f"[audit-consumer] escuchando flight.audit en {broker} …")
    for msg in consumer:
        print("[AUDIT]", json.dumps(msg.value, ensure_ascii=False))


if __name__ == "__main__":
    main()
