import argparse
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path


ZONES = {
    "ZONA-NORTE-02": (-12.0464, -77.0428),
    "ZONA-SUR-01": (-12.1366, -77.0207),
    "ZONA-CENTRO-01": (-12.0580, -77.0365),
    "ZONA-ESTE-03": (-12.0350, -76.9500),
}
STATUSES = ("operating", "idle", "stopped", "maintenance", "fault")
FAILURE_TYPES = (
    "cooling_system",
    "bearing",
    "hydraulic_leak",
    "injectors",
)
ALERT_TYPES = (
    "predictive_failure",
    "anomaly",
    "fuel_drift",
    "low_utilization",
    "overuse",
    "common_cause",
    "maintenance_due",
)
SEVERITIES = ("info", "low", "medium", "high", "critical")
SCORES = {"info": 12, "low": 37, "medium": 62, "high": 82, "critical": 95}
COMPONENTS = {
    "cooling_system": "cooling_system",
    "bearing": "bearing",
    "hydraulic_leak": "hydraulic_system",
    "injectors": "fuel_injectors",
}


def iso(value):
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def build_dataset(seed=17, machines=50, days=30, start=None):
    rng = random.Random(seed)
    start = start or datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) - timedelta(days=days - 1)
    start = start.astimezone(timezone.utc)
    machine_rows = []
    events = {}
    telemetry = []
    labels = []

    for index in range(1, machines + 1):
        machine_id = f"MCH-{index:06d}"
        zone_id = tuple(ZONES)[(index - 1) % len(ZONES)]
        lat, lon = ZONES[zone_id]
        lat += rng.uniform(-0.02, 0.02)
        lon += rng.uniform(-0.02, 0.02)
        kind = ("excavator", "truck", "loader")[(index - 1) % 3]
        base_temp = rng.uniform(78, 89)
        base_vibration = rng.uniform(2.2, 4.2)
        base_pressure = rng.uniform(8.5, 11.5)
        base_fuel = rng.uniform(17, 34)
        base_load = rng.uniform(8000, 17000)
        start_hours = rng.uniform(1200, 9000)
        machine_rows.append({
            "machine_id": machine_id,
            "model": f"AF-{kind[:3].upper()}-{(index % 4) + 1}",
            "type": kind,
            "sector": zone_id.split("-")[1].lower(),
            "zone_id": zone_id,
            "status": "operating",
            "last_seen": iso(start + timedelta(days=days - 1, hours=18)),
            "operating_hours_total": round(start_hours + days * rng.uniform(5, 13), 1),
            "last_maintenance_at": iso(start - timedelta(days=rng.randint(10, 90))),
            "location": {"lat": round(lat, 6), "lon": round(lon, 6)},
        })
        if index <= max(8, machines // 4):
            event_day = rng.randint(max(7, days // 2), days - 2)
            events[machine_id] = {
                "failure_type": FAILURE_TYPES[(index - 1) % len(FAILURE_TYPES)],
                "failure_at": start + timedelta(days=event_day, hours=12),
            }

    for machine in machine_rows:
        machine_id = machine["machine_id"]
        zone_id = machine["zone_id"]
        lat = machine["location"]["lat"]
        lon = machine["location"]["lon"]
        issue = events.get(machine_id)
        base = rng.uniform(18, 33)
        initial_hours = rng.uniform(1200, 9000)
        for day in range(days):
            for sample in range(4):
                timestamp = start + timedelta(days=day, hours=sample * 6)
                hours_to_failure = (
                    (issue["failure_at"] - timestamp).total_seconds() / 3600
                    if issue else None
                )
                progress = max(0.0, min(1.0, (120 - hours_to_failure) / 120)) if issue else 0.0
                metrics = {
                    "engine_temp_c": round(base + rng.gauss(0, 1.8), 1),
                    "vibration_mm_s": round(rng.uniform(2.0, 4.5), 2),
                    "pressure_bar": round(rng.uniform(8.2, 11.8), 2),
                    "fuel_rate_lph": round(rng.uniform(18, 34), 1),
                    "load_kg": round(rng.uniform(6500, 18000), 1),
                    "speed_kmh": round(rng.uniform(0, 28), 1),
                    "engine_rpm": round(rng.uniform(800, 2200), 1),
                    "operating_hours_total": round(initial_hours + day * 8 + sample * 1.5, 1),
                }
                if issue:
                    if issue["failure_type"] == "cooling_system":
                        metrics["engine_temp_c"] = round(metrics["engine_temp_c"] + progress * 24, 1)
                        metrics["vibration_mm_s"] = round(metrics["vibration_mm_s"] + progress * 3, 2)
                    elif issue["failure_type"] == "bearing":
                        metrics["vibration_mm_s"] = round(metrics["vibration_mm_s"] + progress * 6, 2)
                    elif issue["failure_type"] == "hydraulic_leak":
                        metrics["pressure_bar"] = round(max(1, metrics["pressure_bar"] - progress * 5), 2)
                    else:
                        metrics["fuel_rate_lph"] = round(metrics["fuel_rate_lph"] + progress * 13, 1)
                if zone_id == "ZONA-NORTE-02" and day == days - 3:
                    metrics["fuel_rate_lph"] = round(metrics["fuel_rate_lph"] * 1.18, 1)

                status = "fault" if issue and hours_to_failure is not None and hours_to_failure <= 0 else (
                    STATUSES[rng.choices(range(len(STATUSES)), weights=(78, 14, 4, 3, 1))[0]]
                )
                telemetry.append({
                    "schema_version": "1.0",
                    "machine_id": machine_id,
                    "timestamp": iso(timestamp),
                    "location": {"lat": lat, "lon": lon, "zone_id": zone_id},
                    "status": status,
                    "metrics": metrics,
                    "ingested_at": iso(timestamp + timedelta(seconds=rng.randint(1, 45))),
                })
                labels.append({
                    "machine_id": machine_id,
                    "timestamp": iso(timestamp),
                    "failure_within_48h": bool(issue and 0 < hours_to_failure <= 48),
                    "failure_type": issue["failure_type"] if issue else None,
                    "is_eval_machine": int(machine_id.split("-")[1]) % 5 == 0,
                })

    failure_events = [{
        "machine_id": machine_id,
        "failure_type": event["failure_type"],
        "failure_at": iso(event["failure_at"]),
        "suspected_component": COMPONENTS[event["failure_type"]],
    } for machine_id, event in sorted(events.items())]
    return machine_rows, telemetry, labels, failure_events


def build_sample_alerts(seed=17, base_time=None):
    rng = random.Random(seed)
    base_time = base_time or datetime(2026, 11, 14, 15, 20, tzinfo=timezone.utc)
    alerts = []
    for index in range(20):
        alert_type = ALERT_TYPES[index % len(ALERT_TYPES)]
        severity = SEVERITIES[index % len(SEVERITIES)]
        score = max(0, min(100, SCORES[severity] + rng.randint(-3, 3)))
        zone = tuple(ZONES)[index % len(ZONES)]
        machine_number = index + 1
        machine_id = f"MCH-{machine_number:06d}"
        evidence = [{
            "metric": "engine_temp_c",
            "observed": round(88 + rng.uniform(1, 20), 1),
            "expected": 88.0,
            "window": "6h",
            "trend": "rising",
        }]
        alert = {
            "schema_version": "1.0",
            "alert_id": f"ALT-{index + 1:06d}",
            "machine_id": machine_id,
            "zone_id": zone,
            "created_at": iso(base_time - timedelta(minutes=index)),
            "type": alert_type,
            "severity": severity,
            "score": score,
            "confidence": round(rng.uniform(0.62, 0.98), 2),
            "summary": f"Alerta simulada de {alert_type.replace('_', ' ')} para {machine_id}",
            "suspected_component": "cooling_system" if alert_type == "predictive_failure" else "fleet",
            "recommended_action": (
                "stop_and_inspect_now" if severity == "critical" else
                "inspect_within_24h" if severity == "high" else
                "inspect_within_72h" if severity == "medium" else "monitor"
            ),
            "evidence": evidence,
            "related_machine_ids": [],
        }
        if alert_type == "common_cause":
            alert["related_machine_ids"] = [machine_id, f"MCH-{machine_number + 1:06d}"]
            alert["common_factor"] = "fuel_batch"
        alerts.append(alert)
    return alerts


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def main():
    parser = argparse.ArgumentParser(description="Generate deterministic ArquiFusion sample data")
    parser.add_argument("--out", default=str(Path(__file__).resolve().parents[1] / "data" / "sample"))
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--machines", type=int, default=50)
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--start", help="UTC ISO timestamp, e.g. 2026-10-15T00:00:00Z")
    args = parser.parse_args()
    if args.machines < 2 or args.days < 10:
        parser.error("--machines must be at least 2 and --days at least 10")
    start = datetime.fromisoformat(args.start.replace("Z", "+00:00")) if args.start else None
    machines, telemetry, labels, failures = build_dataset(args.seed, args.machines, args.days, start)
    out = Path(args.out)
    write_jsonl(out / "machines.jsonl", machines)
    write_jsonl(out / "telemetry.jsonl", telemetry)
    write_jsonl(out / "failure_labels.jsonl", labels)
    write_jsonl(out / "failure_events.jsonl", failures)
    alert_time = start + timedelta(days=args.days - 1, hours=18)
    write_jsonl(out / "alerts.jsonl", build_sample_alerts(args.seed, alert_time))
    print(f"Generated {len(machines)} machines, {len(telemetry)} readings, {len(failures)} injected failures, 20 alerts at {out}")


if __name__ == "__main__":
    main()
