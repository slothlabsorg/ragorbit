FROM python:3.12-slim
WORKDIR /app
COPY . /app
ENV PORT=8000
ENV MOCK=false
ENV INTEGRATION=true
EXPOSE 8000
# Sin pip en build — servidor HTTP stdlib (app/server_stdlib.py)
CMD ["python", "-m", "app.server_stdlib"]
