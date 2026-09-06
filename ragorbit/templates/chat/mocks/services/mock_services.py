"""Servicios mock del escenario "chat de aerolínea" — HTTP real (stdlib, sin deps).

Cada servicio implementa un CONTRATO (operación + I/O). El PaymentService es
IDEMPOTENTE por cabecera `Idempotency-Key` (no cobra dos veces). Sirve para el
e2e con servicios corriendo de verdad (en docker-compose o en threads locales).

Rutas:  POST /{service}/{operation}   con body JSON  ->  respuesta JSON
Servicios: reservation, inventory, pricing, payment, policy-rag
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Estado de idempotencia del pago (compartido entre requests del servidor).
_PAID: dict = {}
_PAID_LOCK = threading.Lock()

# Bitácora de auditoría server-side: cada request recibido con su respuesta.
_CALLS: list = []
_CALLS_LOCK = threading.Lock()
_SEQ = [0]


def _record(service, op, request, response, extra=None):
    with _CALLS_LOCK:
        _SEQ[0] += 1
        _CALLS.append({"seq": _SEQ[0], "service": service, "operation": op,
                        "request": request, "response": response, **(extra or {})})


def _reservation(op, body):
    # Contrato: lookup(PNR/message) -> itinerario + tarifa
    return {"pnr": "ABC123", "route": "SCL-BOG", "date": "2026-06-15",
            "fareClass": "Plus", "passenger": "J. Pérez"}


def _inventory(op, body):
    # Contrato: search(route, date) -> opciones disponibles
    return {"options": [
        {"flightId": "LA-441", "date": "2026-06-17", "seats": 9},
        {"flightId": "LA-447", "date": "2026-06-17", "seats": 3}]}


def _pricing(op, body):
    # Contrato: quote(currentFlight, newFlight, fareClass) -> diferencia + penalidad
    penalty, diff = 50, 80
    return {"currency": "USD", "penalty": penalty, "fareDifference": diff,
            "amount": penalty + diff}


def _payment(op, body, idem_key):
    # Contrato: charge(amount, currency) -> txn. IDEMPOTENTE por Idempotency-Key.
    amount = body.get("amount", 130)
    with _PAID_LOCK:
        if idem_key and idem_key in _PAID:
            prev = _PAID[idem_key]
            return {**prev, "deduplicated": True}
        txn = {"txnId": f"TXN-{len(_PAID) + 1:04d}", "amount": amount,
               "currency": body.get("currency", "USD"), "status": "captured",
               "deduplicated": False}
        if idem_key:
            _PAID[idem_key] = {k: v for k, v in txn.items() if k != "deduplicated"}
        return txn


def _policy_rag(op, body):
    # Contrato: search(query, fareClass) -> reglas de cambio (con cita)
    return {"chunks": [
        {"text": "Cambio permitido en tarifa Plus internacional con penalidad de USD 50 más diferencia tarifaria.",
         "source": "fare-rules-IATA#Plus-INTL"}]}


_SERVICES = {
    "reservation": _reservation,
    "inventory": _inventory,
    "pricing": _pricing,
    "policy-rag": _policy_rag,
}


class Handler(BaseHTTPRequestHandler):
    server_version = "RAGorbitMockSvc/0.1"

    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Idempotency-Key")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Idempotency-Key")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self):
        if self.path == "/health":
            self._send(200, {"ok": True})
        elif self.path.startswith("/audit"):
            with _CALLS_LOCK:
                self._send(200, list(_CALLS))
        else:
            self._send(404, {"error": "use POST /{service}/{operation} o GET /audit"})

    def do_POST(self):
        parts = [p for p in self.path.split("/") if p]
        if len(parts) < 1:
            self._send(404, {"error": "ruta inválida"}); return
        service = parts[0]
        op = parts[1] if len(parts) > 1 else "invoke"
        n = int(self.headers.get("Content-Length", 0) or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            body = {}
        if service == "payment":
            idem = self.headers.get("Idempotency-Key")
            resp = _payment(op, body, idem)
            _record(service, op, body, resp, {"idempotencyKey": idem, "deduplicated": resp.get("deduplicated")})
            self._send(200, resp); return
        fn = _SERVICES.get(service)
        if not fn:
            self._send(404, {"error": f"servicio desconocido '{service}'"}); return
        resp = fn(op, body)
        _record(service, op, body, resp)
        self._send(200, resp)


def build_server(port: int = 8900, host: str = "127.0.0.1") -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), Handler)


def serve(port: int = 8900):
    import os
    host = os.environ.get("RAGORBIT_HOST", "127.0.0.1")  # 0.0.0.0 en docker
    httpd = build_server(port, host)
    print(f"Mock services en http://127.0.0.1:{port}  (reservation, inventory, pricing, payment, policy-rag)")
    httpd.serve_forever()


def reset_payment_state():
    with _PAID_LOCK:
        _PAID.clear()
    with _CALLS_LOCK:
        _CALLS.clear()
        _SEQ[0] = 0


def _port() -> int:
    import os
    import sys
    if len(sys.argv) > 1:
        return int(sys.argv[1])
    return int(os.environ.get("PORT", "8900"))


if __name__ == "__main__":
    serve(_port())
