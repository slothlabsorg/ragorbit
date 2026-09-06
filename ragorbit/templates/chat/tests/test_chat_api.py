"""Tests del API HTTP (requiere fastapi instalado: pip install -e '.[server]')."""
from __future__ import annotations

import unittest

try:
    from fastapi.testclient import TestClient
    from app.main import app
except ImportError:
    TestClient = None  # type: ignore
    app = None


@unittest.skipUnless(TestClient is not None, "pip install -e '.[server]' para tests HTTP")
class TestChatAPI(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_health(self):
        r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json().get("ok"))

    def test_chat_mock_mode(self):
        r = self.client.post("/chat", json={"message": "Hola", "session_id": "t1"})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("response", data)
        self.assertIsNotNone(data["response"])

    def test_index_html(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)


if __name__ == "__main__":
    unittest.main()
