"""Aplana una lectura de telemetría al esquema de BigQuery `fleet.telemetry` (contrato 6.12).

El ítem de DynamoDB es anidado (location{lat,lon}, metrics{...}), pero la tabla de B es plana
(latitude, longitude, engine_temp_c, ...). Una suscripción BigQuery de Pub/Sub con
`use_table_schema` NO transforma ni aplana: si llega JSON anidado, el mensaje se rechaza.
Por eso el puente aplana antes de publicar. Solo stdlib (se prueba sin AWS ni Google).
"""
from decimal import Decimal

METRIC_COLUMNS = (
    "engine_temp_c", "vibration_mm_s", "pressure_bar", "fuel_rate_lph",
    "load_kg", "speed_kmh", "engine_rpm", "operating_hours_total",
)


def _num(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def is_telemetry_item(item):
    return isinstance(item, dict) and "machine_id" in item and "timestamp" in item and isinstance(item.get("metrics"), dict)


def flatten_telemetry(item):
    """Devuelve la fila plana, o None si el ítem no es telemetría (p. ej. otra tabla)."""
    if not is_telemetry_item(item):
        return None
    location = item.get("location") if isinstance(item.get("location"), dict) else {}
    row = {
        "schema_version": str(item.get("schema_version") or "1.0"),
        "machine_id": item["machine_id"],
        "timestamp": item["timestamp"],
        "ingested_at": item.get("ingested_at"),
        "latitude": _num(location.get("lat")),
        "longitude": _num(location.get("lon")),
        "zone_id": item.get("zone_id") or location.get("zone_id"),
        "status": item.get("status"),
    }
    metrics = item["metrics"]
    for name in METRIC_COLUMNS:
        row[name] = _num(metrics.get(name))
    return row
