import argparse
import json
import uuid
from pathlib import Path

from google.cloud import bigquery


def read_jsonl(path):
    with path.open(encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]


def stage_and_merge(client, project, dataset, target, rows, schema, key_columns, columns):
    stage = f"{project}.{dataset}._stage_{target}_{uuid.uuid4().hex[:12]}"
    config = bigquery.LoadJobConfig(
        schema=schema,
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )
    try:
        client.load_table_from_json(rows, stage, job_config=config).result()
        on_clause = " AND ".join(f"T.{column} = S.{column}" for column in key_columns)
        update_columns = [column for column in columns if column not in key_columns]
        update = ", ".join(f"T.{column} = S.{column}" for column in update_columns)
        insert_columns = ", ".join(columns)
        insert_values = ", ".join(f"S.{column}" for column in columns)
        client.query(f"""
            MERGE `{project}.{dataset}.{target}` T
            USING `{stage}` S ON {on_clause}
            WHEN MATCHED THEN UPDATE SET {update}
            WHEN NOT MATCHED THEN INSERT ({insert_columns}) VALUES ({insert_values})
        """).result()
    finally:
        client.delete_table(stage, not_found_ok=True)


def load_sample(project, dataset, directory):
    client = bigquery.Client(project=project)
    telemetry = []
    for row in read_jsonl(directory / "telemetry.jsonl"):
        metrics = row["metrics"]
        telemetry.append({
            "schema_version": row["schema_version"],
            "machine_id": row["machine_id"],
            "timestamp": row["timestamp"],
            "ingested_at": row["ingested_at"],
            "latitude": row["location"]["lat"],
            "longitude": row["location"]["lon"],
            "zone_id": row["location"]["zone_id"],
            "status": row["status"],
            **metrics,
        })

    machine_rows = []
    for row in read_jsonl(directory / "machines.jsonl"):
        machine_rows.append({
            **{key: value for key, value in row.items() if key != "location"},
            "latitude": row["location"]["lat"],
            "longitude": row["location"]["lon"],
        })

    telemetry_schema = [
        bigquery.SchemaField("schema_version", "STRING"),
        bigquery.SchemaField("machine_id", "STRING"),
        bigquery.SchemaField("timestamp", "TIMESTAMP"),
        bigquery.SchemaField("ingested_at", "TIMESTAMP"),
        bigquery.SchemaField("latitude", "FLOAT"),
        bigquery.SchemaField("longitude", "FLOAT"),
        bigquery.SchemaField("zone_id", "STRING"),
        bigquery.SchemaField("status", "STRING"),
        *[bigquery.SchemaField(name, "FLOAT") for name in (
            "engine_temp_c", "vibration_mm_s", "pressure_bar", "fuel_rate_lph",
            "load_kg", "speed_kmh", "engine_rpm", "operating_hours_total",
        )],
    ]
    machine_schema = [
        bigquery.SchemaField(name, kind) for name, kind in (
            ("machine_id", "STRING"), ("model", "STRING"), ("type", "STRING"),
            ("sector", "STRING"), ("zone_id", "STRING"), ("status", "STRING"),
            ("last_seen", "TIMESTAMP"), ("operating_hours_total", "FLOAT"),
            ("last_maintenance_at", "TIMESTAMP"), ("latitude", "FLOAT"),
            ("longitude", "FLOAT"),
        )
    ]
    label_schema = [
        bigquery.SchemaField("machine_id", "STRING"),
        bigquery.SchemaField("timestamp", "TIMESTAMP"),
        bigquery.SchemaField("failure_within_48h", "BOOL"),
        bigquery.SchemaField("failure_type", "STRING"),
        bigquery.SchemaField("is_eval_machine", "BOOL"),
    ]
    event_schema = [
        bigquery.SchemaField("machine_id", "STRING"),
        bigquery.SchemaField("failure_type", "STRING"),
        bigquery.SchemaField("failure_at", "TIMESTAMP"),
        bigquery.SchemaField("suspected_component", "STRING"),
    ]
    alert_schema = [
        bigquery.SchemaField("alert_id", "STRING"),
        bigquery.SchemaField("machine_id", "STRING"),
        bigquery.SchemaField("zone_id", "STRING"),
        bigquery.SchemaField("created_at", "TIMESTAMP"),
        bigquery.SchemaField("type", "STRING"),
        bigquery.SchemaField("severity", "STRING"),
        bigquery.SchemaField("score", "INT64"),
        bigquery.SchemaField("confidence", "FLOAT"),
        bigquery.SchemaField("summary", "STRING"),
        bigquery.SchemaField("suspected_component", "STRING"),
        bigquery.SchemaField("recommended_action", "STRING"),
        bigquery.SchemaField("evidence", "RECORD", mode="REPEATED", fields=[
            bigquery.SchemaField("metric", "STRING"),
            bigquery.SchemaField("observed", "FLOAT"),
            bigquery.SchemaField("expected", "FLOAT"),
            bigquery.SchemaField("window", "STRING"),
            bigquery.SchemaField("trend", "STRING"),
        ]),
        bigquery.SchemaField("related_machine_ids", "STRING", mode="REPEATED"),
        bigquery.SchemaField("common_factor", "STRING"),
        bigquery.SchemaField("delivered_at", "TIMESTAMP"),
        bigquery.SchemaField("is_sample", "BOOL"),
    ]

    stage_and_merge(
        client, project, dataset, "telemetry", telemetry, telemetry_schema,
        ("machine_id", "timestamp"),
        ("schema_version", "machine_id", "timestamp", "ingested_at", "latitude", "longitude",
         "zone_id", "status", "engine_temp_c", "vibration_mm_s", "pressure_bar",
         "fuel_rate_lph", "load_kg", "speed_kmh", "engine_rpm", "operating_hours_total"),
    )
    stage_and_merge(
        client, project, dataset, "machines", machine_rows, machine_schema,
        ("machine_id",),
        ("machine_id", "model", "type", "sector", "zone_id", "status", "last_seen",
         "operating_hours_total", "last_maintenance_at", "latitude", "longitude"),
    )
    stage_and_merge(
        client, project, dataset, "failure_labels", read_jsonl(directory / "failure_labels.jsonl"),
        label_schema, ("machine_id", "timestamp"),
        ("machine_id", "timestamp", "failure_within_48h", "failure_type", "is_eval_machine"),
    )
    stage_and_merge(
        client, project, dataset, "failure_events", read_jsonl(directory / "failure_events.jsonl"),
        event_schema, ("machine_id",),
        ("machine_id", "failure_type", "failure_at", "suspected_component"),
    )
    stage_and_merge(
        client, project, dataset, "alerts_out", [
            {**alert, "delivered_at": None, "is_sample": True}
            for alert in read_jsonl(directory / "alerts.jsonl")
        ],
        alert_schema, ("alert_id",),
        ("alert_id", "machine_id", "zone_id", "created_at", "type", "severity", "score",
         "confidence", "summary", "suspected_component", "recommended_action", "evidence",
         "related_machine_ids", "common_factor", "delivered_at", "is_sample"),
    )
    print(f"Loaded sample records into {project}.{dataset} with idempotent MERGE.")


def main():
    parser = argparse.ArgumentParser(description="Idempotently load generated sample data to BigQuery")
    parser.add_argument("--project", required=True)
    parser.add_argument("--dataset", default="fleet")
    parser.add_argument(
        "--directory",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "data" / "sample",
    )
    args = parser.parse_args()
    if not args.directory.is_dir():
        raise SystemExit(f"Sample data directory does not exist: {args.directory}")
    load_sample(args.project, args.dataset, args.directory)


if __name__ == "__main__":
    main()
