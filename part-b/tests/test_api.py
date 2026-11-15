import hashlib
import hmac
import json
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.main import Runtime, create_app
from generator.generate import build_sample_alerts


class FakeRepository:
    def __init__(self):
        self.delivered = []

    def fuel(self):
        return [{"machine_id": "MCH-000001", "actual_lph": 12.0, "expected_lph": 10.0, "delta_pct": 20.0}]

    def alert(self, alert_id):
        return [{"alert_id": alert_id, "machine_id": "MCH-000001"}]

    def pending_alerts(self, limit):
        return build_sample_alerts()[:limit]

    def mark_alert_delivered(self, alert_id):
        self.delivered.append(alert_id)


class FakeAssistant:
    def explain(self, alert, role):
        return f"{role}: evidencia {alert['alert_id']}"


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.repository = FakeRepository()
        runtime = Runtime(self.repository, FakeAssistant(), "secret", "alert-secret", "")
        self.client = TestClient(create_app(runtime))

    def signed(self, method, target, body=b""):
        timestamp = str(int(time.time()))
        path, _, query = target.partition("?")
        path_and_query = path + (f"?{query}" if query else "")
        canonical = f"{timestamp}\n{method}\n{path_and_query}\n".encode() + body
        signature = hmac.new(b"secret", canonical, hashlib.sha256).hexdigest()
        return {
            "x-timestamp": timestamp,
            "x-signature": signature,
            "x-signature-version": "c-1",
        }

    def test_health_is_public_but_analytics_requires_signature(self):
        self.assertEqual(self.client.get("/healthz").status_code, 200)
        self.assertEqual(self.client.get("/v1/analytics/fuel").status_code, 401)
        response = self.client.get(
            "/v1/analytics/fuel",
            headers=self.signed("GET", "/v1/analytics/fuel"),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"][0]["machine_id"], "MCH-000001")

    def test_explanation_matches_contract_shape(self):
        target = "/v1/ai/explain?alert_id=ALT-000001&role=technician"
        response = self.client.get(target, headers=self.signed("GET", target))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"], {
            "role": "technician",
            "text": "technician: evidencia ALT-000001",
            "model": "gemini-2.0-flash",
            "grounded_on": ["ALT-000001", "MCH-000001"],
        })

    def test_invalid_alert_uses_shared_error_contract(self):
        body = json.dumps({"schema_version": "1.0"}, separators=(",", ":")).encode()
        response = self.client.post(
            "/v1/alerts/forward",
            content=body,
            headers={
                **self.signed("POST", "/v1/alerts/forward", body),
                "content-type": "application/json",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "VALIDATION_ERROR")
        self.assertIn("request_id", response.json()["error"])

    def test_job_dispatches_pending_alerts_with_a_signature(self):
        runtime = Runtime(self.repository, FakeAssistant(), "secret", "alert-secret", "https://aws.example")
        client = TestClient(create_app(runtime))

        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def read(self):
                return b'{"accepted":true}'

        target = "/v1/jobs/dispatch-alerts?limit=3"
        with patch("app.main.urllib.request.urlopen", return_value=FakeResponse()) as send:
            response = client.post(target, headers=self.signed("POST", target))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["delivered"], 3)
        self.assertEqual(len(self.repository.delivered), 3)
        outbound = send.call_args.args[0]
        expected = hmac.new(b"alert-secret", outbound.data, hashlib.sha256).hexdigest()
        self.assertEqual(outbound.get_header("X-signature"), expected)


if __name__ == "__main__":
    unittest.main()
