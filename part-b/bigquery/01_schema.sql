CREATE SCHEMA IF NOT EXISTS fleet
OPTIONS(location = "US");

CREATE TABLE IF NOT EXISTS fleet.telemetry (
  schema_version STRING NOT NULL,
  machine_id STRING NOT NULL,
  timestamp TIMESTAMP NOT NULL,
  ingested_at TIMESTAMP,
  latitude FLOAT64,
  longitude FLOAT64,
  zone_id STRING,
  status STRING,
  engine_temp_c FLOAT64,
  vibration_mm_s FLOAT64,
  pressure_bar FLOAT64,
  fuel_rate_lph FLOAT64,
  load_kg FLOAT64,
  speed_kmh FLOAT64,
  engine_rpm FLOAT64,
  operating_hours_total FLOAT64
)
PARTITION BY DATE(timestamp)
CLUSTER BY machine_id;

CREATE TABLE IF NOT EXISTS fleet.machines (
  machine_id STRING NOT NULL,
  model STRING,
  type STRING,
  sector STRING,
  zone_id STRING,
  status STRING,
  last_seen TIMESTAMP,
  operating_hours_total FLOAT64,
  last_maintenance_at TIMESTAMP,
  latitude FLOAT64,
  longitude FLOAT64
)
CLUSTER BY zone_id, machine_id;

CREATE TABLE IF NOT EXISTS fleet.failure_labels (
  machine_id STRING NOT NULL,
  timestamp TIMESTAMP NOT NULL,
  failure_within_48h BOOL NOT NULL,
  failure_type STRING,
  is_eval_machine BOOL
)
PARTITION BY DATE(timestamp)
CLUSTER BY machine_id;

CREATE TABLE IF NOT EXISTS fleet.failure_events (
  machine_id STRING NOT NULL,
  failure_type STRING,
  failure_at TIMESTAMP,
  suspected_component STRING
)
PARTITION BY DATE(failure_at)
CLUSTER BY machine_id;

CREATE TABLE IF NOT EXISTS fleet.alerts_out (
  alert_id STRING NOT NULL,
  machine_id STRING NOT NULL,
  zone_id STRING NOT NULL,
  created_at TIMESTAMP NOT NULL,
  type STRING NOT NULL,
  severity STRING NOT NULL,
  score INT64 NOT NULL,
  confidence FLOAT64 NOT NULL,
  summary STRING NOT NULL,
  suspected_component STRING NOT NULL,
  recommended_action STRING NOT NULL,
  evidence ARRAY<STRUCT<metric STRING, observed FLOAT64, expected FLOAT64, `window` STRING, trend STRING>>,
  related_machine_ids ARRAY<STRING>,
  common_factor STRING,
  delivered_at TIMESTAMP,
  is_sample BOOL
)
PARTITION BY DATE(created_at)
CLUSTER BY machine_id, severity;

CREATE TABLE IF NOT EXISTS fleet.model_runs (
  model STRING NOT NULL,
  trained_at TIMESTAMP NOT NULL,
  precision FLOAT64,
  recall FLOAT64,
  mean_lead_time_h FLOAT64,
  promoted BOOL NOT NULL,
  evaluation_notes STRING
)
PARTITION BY DATE(trained_at)
CLUSTER BY model;
