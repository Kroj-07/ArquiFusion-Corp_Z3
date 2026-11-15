import hashlib
import hmac
import time
from urllib.parse import urlsplit


def verify_c_signature(secret, headers, path_and_query, method, body=b"", now=None):
    normalized = {key.lower(): value for key, value in headers.items()}
    stamp = normalized.get("x-timestamp", "")
    try:
        if abs((time.time() if now is None else now) - int(stamp)) > 300:
            return False
    except (ValueError, TypeError):
        return False
    if normalized.get("x-signature-version") != "c-1":
        return False
    canonical = f"{stamp}\n{method.upper()}\n{path_and_query}\n".encode() + body
    expected = hmac.new(secret.encode(), canonical, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, normalized.get("x-signature", ""))


def sign_alert(secret, body, timestamp=None):
    stamp = str(int(time.time()) if timestamp is None else timestamp)
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return {"x-timestamp": stamp, "x-signature": signature}


def request_path_and_query(scope):
    path = scope.get("raw_path", scope.get("path", "").encode()).decode()
    query = scope.get("query_string", b"").decode()
    return urlsplit(path + (f"?{query}" if query else "")).geturl()
