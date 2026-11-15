CREATE OR REPLACE VIEW fleet.telemetry_features AS
WITH windows AS (
  SELECT
    t.machine_id,
    t.timestamp,
    t.zone_id,
    t.engine_temp_c,
    t.vibration_mm_s,
    t.pressure_bar,
    t.fuel_rate_lph,
    t.load_kg,
    t.speed_kmh,
    t.operating_hours_total,
    AVG(t.engine_temp_c) OVER sample_window AS temp_mean_24h,
    AVG(t.vibration_mm_s) OVER sample_window AS vibration_mean_24h,
    AVG(t.pressure_bar) OVER sample_window AS pressure_mean_24h,
    AVG(t.fuel_rate_lph) OVER sample_window AS fuel_mean_24h,
    COUNTIF(t.status = "operating") OVER sample_window AS operating_samples_24h
  FROM fleet.telemetry AS t
  WINDOW sample_window AS (
    PARTITION BY t.machine_id ORDER BY t.timestamp
    ROWS BETWEEN 3 PRECEDING AND CURRENT ROW
  )
)
SELECT
  w.*,
  SAFE_DIVIDE(w.load_kg, NULLIF(m.operating_hours_total, 0)) AS load_per_machine_hour,
  COALESCE(l.failure_within_48h, FALSE) AS failure_within_48h,
  COALESCE(l.is_eval_machine, MOD(ABS(FARM_FINGERPRINT(w.machine_id)), 5) = 0) AS is_eval_machine
FROM windows AS w
LEFT JOIN fleet.machines AS m USING (machine_id)
LEFT JOIN fleet.failure_labels AS l USING (machine_id, timestamp);

CREATE OR REPLACE VIEW fleet.fuel_analytics AS
WITH latest AS (
  SELECT
    machine_id,
    AVG(fuel_rate_lph) AS actual_lph,
    MAX(timestamp) AS last_seen
  FROM fleet.telemetry
  WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
  GROUP BY machine_id
)
SELECT
  l.machine_id,
  ROUND(l.actual_lph, 2) AS actual_lph,
  ROUND(AVG(l.actual_lph) OVER (PARTITION BY m.type), 2) AS expected_lph,
  ROUND(100 * SAFE_DIVIDE(
    l.actual_lph - AVG(l.actual_lph) OVER (PARTITION BY m.type),
    NULLIF(AVG(l.actual_lph) OVER (PARTITION BY m.type), 0)
  ), 2) AS delta_pct
FROM latest AS l
JOIN fleet.machines AS m USING (machine_id);

CREATE OR REPLACE VIEW fleet.utilization_analytics AS
SELECT
  machine_id,
  ROUND(100 * SAFE_DIVIDE(
    COUNTIF(status = "operating"),
    COUNT(*)
  ), 2) AS sampled_operating_pct,
  ROUND(100 * SAFE_DIVIDE(
    COUNTIF(status IN ("fault", "maintenance", "stopped")),
    COUNT(*)
  ), 2) AS cost_index
FROM fleet.telemetry
WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY machine_id;

CREATE OR REPLACE VIEW fleet.maintenance_predictions AS
WITH latest AS (
  SELECT machine_id, operating_hours_total
  FROM fleet.telemetry
  QUALIFY ROW_NUMBER() OVER (PARTITION BY machine_id ORDER BY timestamp DESC) = 1
)
SELECT
  machine_id,
  GREATEST(0, 500 - MOD(operating_hours_total, 500)) AS remaining_operating_hours,
  "Intervalo base de mantenimiento de 500 horas; validar con el fabricante" AS basis
FROM latest;

CREATE OR REPLACE VIEW fleet.spare_parts_analytics AS
WITH recent_failures AS (
  SELECT
    m.zone_id,
    e.suspected_component AS component,
    COUNT(*) AS expected_demand
  FROM fleet.failure_events AS e
  JOIN fleet.machines AS m USING (machine_id)
  WHERE e.failure_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
  GROUP BY m.zone_id, component
)
SELECT
  zone_id,
  component,
  expected_demand,
  GREATEST(1, CAST(CEIL(expected_demand * 1.25) AS INT64)) AS suggested_min_stock,
  expected_demand >= 3 AS irregular
FROM recent_failures;

CREATE OR REPLACE VIEW fleet.common_cause_analytics AS
WITH daily_fuel AS (
  SELECT
    t.machine_id,
    m.zone_id,
    DATE(t.timestamp) AS event_day,
    m.latitude,
    m.longitude,
    AVG(t.fuel_rate_lph) AS actual_lph,
    AVG(AVG(t.fuel_rate_lph)) OVER (PARTITION BY m.type) AS expected_lph,
    m.type
  FROM fleet.telemetry AS t
  JOIN fleet.machines AS m USING (machine_id)
  WHERE t.timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
  GROUP BY t.machine_id, m.zone_id, event_day, m.latitude, m.longitude, m.type
),
candidates AS (
  SELECT
    *,
    ST_CLUSTERDBSCAN(ST_GEOGPOINT(longitude, latitude), 5000, 2)
      OVER (PARTITION BY zone_id, event_day) AS cluster_id
  FROM daily_fuel
  WHERE SAFE_DIVIDE(actual_lph - expected_lph, NULLIF(expected_lph, 0)) > 0.15
)
SELECT
  zone_id,
  ARRAY_AGG(machine_id ORDER BY machine_id) AS machine_ids,
  "Consumo de combustible elevado en máquinas cercanas; revisar lote de combustible o condiciones del terreno" AS hypothesis
FROM candidates
WHERE cluster_id IS NOT NULL
GROUP BY zone_id, event_day, cluster_id
HAVING COUNT(*) >= 2;
