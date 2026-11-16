-- Problema 12 (planificación con histórico): qué pasó en las 72 h anteriores a cada falla.
-- Versión mínima del plan inicial: resume las métricas previas y su pendiente (últimas 24 h vs. 48-72 h antes).
-- Requiere 01_schema.sql (fleet.telemetry, fleet.failure_events). Es una vista: no cuesta nada en reposo.

CREATE OR REPLACE VIEW fleet.failure_precursors AS
WITH window_rows AS (
  SELECT
    e.machine_id,
    e.failure_type,
    e.failure_at,
    e.suspected_component,
    TIMESTAMP_DIFF(e.failure_at, t.timestamp, HOUR) AS hours_before,
    t.engine_temp_c,
    t.vibration_mm_s,
    t.pressure_bar,
    t.fuel_rate_lph
  FROM fleet.failure_events AS e
  JOIN fleet.telemetry AS t
    ON t.machine_id = e.machine_id
   AND t.timestamp >= TIMESTAMP_SUB(e.failure_at, INTERVAL 72 HOUR)
   AND t.timestamp < e.failure_at
)
SELECT
  machine_id,
  failure_type,
  failure_at,
  suspected_component,
  AVG(IF(hours_before < 24, engine_temp_c, NULL)) AS temp_last_24h,
  AVG(IF(hours_before >= 48, engine_temp_c, NULL)) AS temp_48_72h,
  SAFE_DIVIDE(AVG(IF(hours_before < 24, engine_temp_c, NULL)) - AVG(IF(hours_before >= 48, engine_temp_c, NULL)), 48) AS temp_slope_per_h,
  AVG(IF(hours_before < 24, vibration_mm_s, NULL)) AS vibration_last_24h,
  AVG(IF(hours_before >= 48, vibration_mm_s, NULL)) AS vibration_48_72h,
  SAFE_DIVIDE(AVG(IF(hours_before < 24, vibration_mm_s, NULL)) - AVG(IF(hours_before >= 48, vibration_mm_s, NULL)), 48) AS vibration_slope_per_h,
  AVG(IF(hours_before < 24, pressure_bar, NULL)) AS pressure_last_24h,
  AVG(IF(hours_before >= 48, pressure_bar, NULL)) AS pressure_48_72h,
  AVG(IF(hours_before < 24, fuel_rate_lph, NULL)) AS fuel_last_24h,
  AVG(IF(hours_before >= 48, fuel_rate_lph, NULL)) AS fuel_48_72h,
  COUNT(*) AS samples
FROM window_rows
GROUP BY machine_id, failure_type, failure_at, suspected_component;

-- Resumen por tipo de falla: el "patrón precursor" típico que se muestra en el video.
CREATE OR REPLACE VIEW fleet.failure_precursor_patterns AS
SELECT
  failure_type,
  COUNT(*) AS failures,
  AVG(temp_slope_per_h) AS avg_temp_slope_per_h,
  AVG(vibration_slope_per_h) AS avg_vibration_slope_per_h,
  AVG(pressure_last_24h - pressure_48_72h) AS avg_pressure_change,
  AVG(fuel_last_24h - fuel_48_72h) AS avg_fuel_change
FROM fleet.failure_precursors
GROUP BY failure_type;
