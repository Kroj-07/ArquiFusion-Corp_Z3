import json
import os
import urllib.error
import urllib.request
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse

from .assistant import GeminiAssistant
from .repository import BigQueryRepository
from .security import request_path_and_query, sign_alert, verify_c_signature


ROLES = {"operator", "technician", "maintenance", "supervisor", "admin", "manager"}


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    role: str
    machine_id: str | None = None


class Runtime:
    def __init__(self, repository, assistant, auth_secret, alert_secret, aws_api_base):
        self.repository = repository
        self.assistant = assistant
        self.auth_secret = auth_secret
        self.alert_secret = alert_secret
        self.aws_api_base = aws_api_base.rstrip("/")


def create_app(runtime=None):
    @asynccontextmanager
    async def lifespan(app):
        if runtime is None:
            app.state.runtime = Runtime(
                BigQueryRepository.from_environment(),
                GeminiAssistant.from_environment(),
                os.environ.get("B_API_AUTH_SECRET", ""),
                os.environ.get("B_ALERT_HMAC_SECRET", ""),
                os.environ.get("A_API_BASE", ""),
            )
        else:
            app.state.runtime = runtime
        yield

    app = FastAPI(title="ArquiFusion Part B API", version="1.0.0", lifespan=lifespan)
    if runtime is not None:
        app.state.runtime = runtime

    @app.exception_handler(HTTPException)
    async def http_error_handler(request, error):
        del request
        code = {
            401: "UNAUTHORIZED",
            403: "FORBIDDEN",
            404: "NOT_FOUND",
            409: "CONFLICT",
            429: "RATE_LIMITED",
        }.get(error.status_code, "INTERNAL_ERROR" if error.status_code >= 500 else "VALIDATION_ERROR")
        return _json_error(error.status_code, code, str(error.detail))

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request, error):
        del request
        details = [
            {"field": ".".join(str(part) for part in item["loc"]), "message": item["msg"]}
            for item in error.errors()
        ]
        return _json_error(400, "VALIDATION_ERROR", "Request validation failed", details)

    @app.middleware("http")
    async def authenticate_backend(request: Request, call_next):
        if request.url.path == "/healthz":
            return await call_next(request)
        service = getattr(request.app.state, "runtime", runtime)
        if service is None or not service.auth_secret:
            return _json_error(503, "SERVICE_NOT_CONFIGURED", "Backend authentication is not configured")
        body = await request.body()
        path = request_path_and_query(request.scope)
        if not verify_c_signature(service.auth_secret, request.headers, path, request.method, body):
            return _json_error(401, "UNAUTHORIZED", "Invalid or expired backend signature")
        request._body = body
        return await call_next(request)

    @app.get("/healthz")
    def health():
        return {"status": "ok"}

    @app.get("/v1/analytics/fuel")
    def fuel(request: Request):
        return {"data": _repo(request).fuel()}

    @app.get("/v1/analytics/utilization")
    def utilization(request: Request):
        return {"data": _repo(request).utilization()}

    @app.get("/v1/analytics/spare-parts")
    def spare_parts(request: Request, zone_id: str | None = None):
        return {"data": _repo(request).spare_parts(zone_id)}

    @app.get("/v1/analytics/common-cause")
    def common_cause(request: Request):
        return {"data": _repo(request).common_cause()}

    @app.get("/v1/predictions/maintenance")
    def maintenance(request: Request):
        return {"data": _repo(request).maintenance()}

    @app.get("/v1/predictions/risk")
    def risk(request: Request, limit: int = 100):
        if not 1 <= limit <= 1000:
            raise HTTPException(400, "limit must be between 1 and 1000")
        return {"data": _repo(request).risk(limit)}

    @app.get("/v1/ai/explain")
    def explain(request: Request, alert_id: str, role: str):
        if role not in ROLES:
            raise HTTPException(400, "Invalid role")
        rows = _repo(request).alert(alert_id)
        if not rows:
            raise HTTPException(404, "Alert not found")
        alert = _json_safe(rows[0])
        text = request.app.state.runtime.assistant.explain(alert, role)
        return {
            "data": {
                "role": role,
                "text": text,
                "model": os.environ.get("GEMINI_MODEL", "gemini-2.0-flash"),
                "grounded_on": [alert_id, alert["machine_id"]],
            }
        }

    @app.post("/v1/ai/ask")
    def ask(request: Request, body: AskRequest):
        if body.role not in ROLES:
            raise HTTPException(400, "Invalid role")
        source_rows = _repo(request).history(body.machine_id, 20) if body.machine_id else []
        if not source_rows:
            raise HTTPException(404, "No history available for the requested machine")
        sources = _json_safe(source_rows)
        answer = request.app.state.runtime.assistant.ask(body.question, body.role, sources)
        return {"data": {"answer": answer, "sources": sources}}

    @app.post("/v1/alerts/forward")
    def forward_alert(request: Request, alert: dict):
        service = request.app.state.runtime
        _validate_alert(alert)
        result = _send_alert_to_aws(service, alert)
        return {"data": {"accepted": True, "alert_id": alert["alert_id"], "aws_response": result}}

    @app.post("/v1/jobs/dispatch-alerts")
    def dispatch_alerts(request: Request, limit: int = 100):
        if not 1 <= limit <= 1000:
            raise HTTPException(400, "limit must be between 1 and 1000")
        service = request.app.state.runtime
        if not service.alert_secret or not service.aws_api_base:
            raise HTTPException(503, "Alert forwarding is not configured")
        pending = _repo(request).pending_alerts(limit)
        delivered = []
        for row in pending:
            alert = _json_safe(row)
            _validate_alert(alert)
            _send_alert_to_aws(service, alert)
            _repo(request).mark_alert_delivered(alert["alert_id"])
            delivered.append(alert["alert_id"])
        return {"data": {"delivered": len(delivered), "alert_ids": delivered}}

    return app


def _send_alert_to_aws(service, alert):
    if not service.alert_secret or not service.aws_api_base:
        raise HTTPException(503, "Alert forwarding is not configured")
    raw_body = json.dumps(alert, separators=(",", ":"), ensure_ascii=False).encode()
    headers = {"content-type": "application/json", **sign_alert(service.alert_secret, raw_body)}
    outbound = urllib.request.Request(
        service.aws_api_base + "/v1/alerts",
        data=raw_body,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(outbound, timeout=10) as response:
            status = response.status
            result = response.read()
    except urllib.error.HTTPError as error:
        raise HTTPException(502, f"AWS alerts API returned HTTP {error.code}") from error
    except urllib.error.URLError as error:
        raise HTTPException(502, "AWS alerts API is unavailable") from error
    if status < 200 or status >= 300:
        raise HTTPException(502, "AWS alerts API rejected the alert")
    return result.decode()


def _repo(request):
    return request.app.state.runtime.repository


def _json_safe(value):
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if hasattr(value, "items"):
        return {key: _json_safe(item) for key, item in value.items()}
    if hasattr(value, "isoformat"):
        return value.isoformat().replace("+00:00", "Z")
    return value


def _json_error(status, code, message, details=None):
    return JSONResponse(status_code=status, content={
        "error": {
            "code": code,
            "message": message,
            "details": details,
            "request_id": f"req-{uuid.uuid4().hex[:12]}",
        }
    })


def _validate_alert(alert):
    required = {
        "schema_version", "alert_id", "machine_id", "zone_id", "created_at", "type",
        "severity", "score", "confidence", "summary", "suspected_component",
        "recommended_action", "evidence", "related_machine_ids",
    }
    if not isinstance(alert, dict) or not required.issubset(alert):
        raise HTTPException(400, "Alert is missing fields from contract 6.4")
    if alert["schema_version"] != "1.0":
        raise HTTPException(400, "Unsupported alert schema_version")
    allowed_types = {
        "predictive_failure", "anomaly", "fuel_drift", "low_utilization",
        "overuse", "common_cause", "maintenance_due",
    }
    allowed_severities = {"info": (0, 24), "low": (25, 49), "medium": (50, 74), "high": (75, 89), "critical": (90, 100)}
    allowed_actions = {"monitor", "inspect_within_72h", "inspect_within_24h", "stop_and_inspect_now"}
    if not isinstance(alert["type"], str) or not isinstance(alert["severity"], str):
        raise HTTPException(400, "Alert type and severity must be strings")
    if alert["type"] not in allowed_types or alert["severity"] not in allowed_severities:
        raise HTTPException(400, "Invalid alert type or severity")
    low, high = allowed_severities[alert["severity"]]
    if type(alert["score"]) is not int or not low <= alert["score"] <= high:
        raise HTTPException(400, "Alert score does not match severity range")
    if isinstance(alert["confidence"], bool) or not isinstance(alert["confidence"], (int, float)) or not 0 <= alert["confidence"] <= 1:
        raise HTTPException(400, "Alert confidence must be between 0 and 1")
    if not isinstance(alert["recommended_action"], str) or alert["recommended_action"] not in allowed_actions:
        raise HTTPException(400, "Invalid recommended_action")
    if not isinstance(alert["evidence"], list) or not isinstance(alert["related_machine_ids"], list):
        raise HTTPException(400, "Alert evidence and related_machine_ids must be arrays")
    if not all(isinstance(value, str) and value for value in alert["related_machine_ids"]):
        raise HTTPException(400, "related_machine_ids must contain non-empty strings")
    if not all(isinstance(alert.get(field), str) and alert[field] for field in (
        "alert_id", "machine_id", "zone_id", "created_at", "summary", "suspected_component",
    )):
        raise HTTPException(400, "Alert identifiers, timestamp and summary must be non-empty strings")
    if not alert["created_at"].endswith("Z"):
        raise HTTPException(400, "created_at must be an ISO 8601 UTC timestamp ending in Z")
    try:
        from datetime import datetime
        datetime.fromisoformat(alert["created_at"].replace("Z", "+00:00"))
    except ValueError as error:
        raise HTTPException(400, "created_at must be an ISO 8601 UTC timestamp") from error
    for item in alert["evidence"]:
        if not isinstance(item, dict) or not all(
            isinstance(item.get(field), str) and item[field]
            for field in ("metric", "window", "trend")
        ) or any(
            isinstance(item.get(field), bool) or not isinstance(item.get(field), (int, float))
            for field in ("observed", "expected")
        ):
            raise HTTPException(400, "Each evidence item must match contract 6.4")
    if alert["type"] == "common_cause" and not alert.get("common_factor"):
        raise HTTPException(400, "common_cause alerts require common_factor")


app = create_app()
