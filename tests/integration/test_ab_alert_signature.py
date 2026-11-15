"""Prueba de integración A<->B: la firma que genera B debe verificarla A.

Ejecutar desde la raíz del repo:  python -m unittest tests.integration.test_ab_alert_signature -v
Protege contra el conflicto detectado el 2026-11-15: B firmaba solo el cuerpo y A exige
"<timestamp>.<cuerpo>" (contrato v1.3), lo que daba 401 en todo POST /v1/alerts.
"""
import importlib.util
import json
import pathlib
import sys
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


b_security = _load("b_security", "part-b/app/security.py")
a_hmac = _load("a_hmac", "part-a/shared/hmac_utils.py")

SECRET = "secreto-de-prueba"
BODY = json.dumps({"alert_id": "ALT-000812", "severity": "high"}, separators=(",", ":")).encode()


class AlertSignatureAB(unittest.TestCase):
    def test_a_accepts_what_b_signs(self):
        headers = b_security.sign_alert(SECRET, BODY)
        self.assertTrue(a_hmac.verify_hmac(SECRET, BODY, headers["x-timestamp"], headers["x-signature"]))

    def test_a_rejects_tampered_body(self):
        headers = b_security.sign_alert(SECRET, BODY)
        self.assertFalse(a_hmac.verify_hmac(SECRET, BODY + b" ", headers["x-timestamp"], headers["x-signature"]))

    def test_a_rejects_old_timestamp(self):
        headers = b_security.sign_alert(SECRET, BODY, timestamp=int(time.time()) - 3600)
        self.assertFalse(a_hmac.verify_hmac(SECRET, BODY, headers["x-timestamp"], headers["x-signature"]))


if __name__ == "__main__":
    unittest.main()
