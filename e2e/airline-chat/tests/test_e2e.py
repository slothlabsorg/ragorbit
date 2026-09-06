"""Test end-to-end del chat de aerolínea CON SERVICIOS REALES CORRIENDO.

Levanta los servicios mock HTTP en un thread, corre el bot de RAGorbit en modo
integración contra ellos, y verifica el flujo completo. Runnable sin red ni docker:

    python -m unittest e2e.airline-chat.tests.test_e2e      # desde el repo
    # o:  cd e2e/airline-chat && python -m unittest discover -s tests
"""
from __future__ import annotations

import json
import sys
import threading
import time
import unittest
import urllib.request
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_E2E = _HERE.parent
_REPO = _E2E.parents[1]
for p in (str(_REPO), str(_E2E), str(_E2E / "services")):
    if p not in sys.path:
        sys.path.insert(0, p)

import mock_services  # noqa: E402
from bus import InMemoryBus  # noqa: E402
import run_bot  # noqa: E402

PORT = 8911
BASE = f"http://127.0.0.1:{PORT}"


def _post(path, body, headers=None):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(),
                                 method="POST", headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


class TestAirlineE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        mock_services.reset_payment_state()
        cls.httpd = mock_services.build_server(PORT)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        # espera a que el servicio esté listo
        for _ in range(50):
            try:
                urllib.request.urlopen(BASE + "/health", timeout=1); break
            except Exception:
                time.sleep(0.05)

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def test_services_are_live(self):
        r = _post("/reservation/lookup", {"message": "x"})
        self.assertEqual(r["fareClass"], "Plus")

    def test_full_flow_runs_against_real_services(self):
        bus = InMemoryBus()
        res = run_bot.run("Quiero cambiar mi vuelo SCL-BOG del 15 al 17", services_base=BASE, bus=bus)
        # el agente llamó a las herramientas reales
        names = [c["name"] for c in res["trace"]["agent"]["tool_calls"]]
        self.assertTrue(any("ayment" in n or "ago" in n.lower() for n in names) or len(names) >= 3,
                        f"esperaba varias tool calls, vi {names}")
        # el bot pide confirmación (confirm-gate sobre el pago)
        self.assertIn("onfirm", res["response"].lower())
        # se publicaron eventos de auditoría al bus
        self.assertGreaterEqual(len(bus.events), 1, "el audit debe publicar al bus (Kafka/memoria)")

    def test_payment_is_idempotent(self):
        # mismo Idempotency-Key dos veces => un solo cobro
        k = {"Idempotency-Key": "pnr-ABC123:sess-9"}
        first = _post("/payment/charge", {"amount": 130, "currency": "USD"}, k)
        second = _post("/payment/charge", {"amount": 130, "currency": "USD"}, k)
        self.assertFalse(first["deduplicated"])
        self.assertTrue(second["deduplicated"], "el segundo cobro con misma key debe deduplicarse")
        self.assertEqual(first["txnId"], second["txnId"], "mismo txn, no doble cobro")

    def test_pricing_contract(self):
        r = _post("/pricing/quote", {})
        self.assertEqual(r["amount"], r["penalty"] + r["fareDifference"])


if __name__ == "__main__":
    unittest.main()
