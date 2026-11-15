import hashlib
import hmac
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.security import sign_alert, verify_c_signature


class SignatureTests(unittest.TestCase):
    def test_accepts_c_contract_signature(self):
        secret = "local-test-secret"
        timestamp = "1700000000"
        path = "/v1/ai/explain?alert_id=ALT-000001&role=technician"
        canonical = f"{timestamp}\nGET\n{path}\n".encode()
        signature = hmac.new(secret.encode(), canonical, hashlib.sha256).hexdigest()
        headers = {
            "x-timestamp": timestamp,
            "x-signature": signature,
            "x-signature-version": "c-1",
        }
        self.assertTrue(verify_c_signature(secret, headers, path, "GET", now=1700000000))

    def test_rejects_stale_request_and_tampered_body(self):
        secret = "local-test-secret"
        body = b'{"question":"status"}'
        timestamp = "1700000000"
        path = "/v1/ai/ask"
        canonical = f"{timestamp}\nPOST\n{path}\n".encode() + body
        headers = {
            "x-timestamp": timestamp,
            "x-signature": hmac.new(secret.encode(), canonical, hashlib.sha256).hexdigest(),
            "x-signature-version": "c-1",
        }
        self.assertFalse(verify_c_signature(secret, headers, path, "POST", body, now=1700000400))
        self.assertFalse(verify_c_signature(secret, headers, path, "POST", b"{}", now=1700000000))

    def test_alert_signature_is_for_exact_body(self):
        headers = sign_alert("shared", b'{"alert_id":"ALT-000001"}', timestamp=1700000000)
        expected = hmac.new(b"shared", b'1700000000.{"alert_id":"ALT-000001"}', hashlib.sha256).hexdigest()
        self.assertEqual(headers, {"x-timestamp": "1700000000", "x-signature": expected})


if __name__ == "__main__":
    unittest.main()
