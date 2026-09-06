# Imagen para los servicios mock y el bot del e2e. Contexto de build = raíz del repo.
FROM python:3.12-slim
WORKDIR /repo
COPY . /repo
# kafka-python solo se necesita para publicar al Kafka real (modo bus Kafka).
# Si falla la instalación (sin red, proxy), el bot cae al bus en memoria automáticamente.
RUN pip install --no-cache-dir kafka-python || echo "kafka-python no instalado; bus en memoria"
ENV RAGORBIT_HOST=0.0.0.0
CMD ["python", "e2e/airline-chat/services/mock_services.py", "8900"]
