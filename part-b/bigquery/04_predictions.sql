CREATE OR REPLACE VIEW fleet.risk_predictions AS
WITH latest_features AS (
  SELECT *
  FROM fleet.telemetry_features
  QUALIFY ROW_NUMBER() OVER (PARTITION BY machine_id ORDER BY timestamp DESC) = 1
),
scored AS (
  SELECT *
  FROM ML.PREDICT(
    MODEL fleet.failure_risk_model,
    (
      SELECT
        machine_id,
        zone_id,
        timestamp,
        engine_temp_c,
        vibration_mm_s,
        pressure_bar,
        fuel_rate_lph,
        temp_mean_24h,
        vibration_mean_24h,
        pressure_mean_24h,
        fuel_mean_24h,
        load_per_machine_hour,
        operating_samples_24h
      FROM latest_features
    )
  )
)
SELECT
  machine_id,
  zone_id,
  timestamp AS generated_at,
  engine_temp_c,
  temp_mean_24h,
  vibration_mm_s,
  vibration_mean_24h,
  pressure_bar,
  pressure_mean_24h,
  fuel_rate_lph,
  fuel_mean_24h,
  CAST(ROUND(100 * (
    SELECT prob
    FROM UNNEST(predicted_failure_within_48h_probs)
    WHERE CAST(label AS STRING) IN ("TRUE", "true", "1")
  )) AS INT64) AS score,
  (
    SELECT prob
    FROM UNNEST(predicted_failure_within_48h_probs)
    WHERE CAST(label AS STRING) IN ("TRUE", "true", "1")
  ) AS confidence,
  CASE
    WHEN vibration_mean_24h > 6 THEN "bearing"
    WHEN pressure_mean_24h < 6 THEN "hydraulic_system"
    WHEN fuel_mean_24h > 35 THEN "fuel_injectors"
    ELSE "cooling_system"
  END AS suspected_component
FROM scored;

MERGE fleet.alerts_out AS target
USING (
  SELECT
    FORMAT(
      "ALT-%06d%010d",
      CAST(REGEXP_EXTRACT(machine_id, r"([0-9]+)$") AS INT64),
      MOD(UNIX_SECONDS(generated_at), 10000000000)
    ) AS alert_id,
    machine_id,
    zone_id,
    generated_at AS created_at,
    "predictive_failure" AS type,
    CASE
      WHEN score >= 90 THEN "critical"
      WHEN score >= 75 THEN "high"
      ELSE "medium"
    END AS severity,
    score,
    confidence,
    FORMAT("Riesgo estimado de falla en las próximas 48 horas para %s", machine_id) AS summary,
    suspected_component,
    CASE
      WHEN score >= 90 THEN "stop_and_inspect_now"
      WHEN score >= 75 THEN "inspect_within_24h"
      ELSE "inspect_within_72h"
    END AS recommended_action,
    ARRAY<STRUCT<metric STRING, observed FLOAT64, expected FLOAT64, `window` STRING, trend STRING>>[
      STRUCT(
        "engine_temp_c",
        engine_temp_c,
        temp_mean_24h,
        "24h",
        IF(engine_temp_c >= temp_mean_24h, "rising", "stable")
      ),
      STRUCT(
        "vibration_mm_s",
        vibration_mm_s,
        vibration_mean_24h,
        "24h",
        IF(vibration_mm_s >= vibration_mean_24h, "rising", "stable")
      ),
      STRUCT(
        "pressure_bar",
        pressure_bar,
        pressure_mean_24h,
        "24h",
        IF(pressure_bar <= pressure_mean_24h, "falling", "stable")
      ),
      STRUCT(
        "fuel_rate_lph",
        fuel_rate_lph,
        fuel_mean_24h,
        "24h",
        IF(fuel_rate_lph >= fuel_mean_24h, "rising", "stable")
      )
    ] AS evidence,
    ARRAY<STRING>[] AS related_machine_ids,
    CAST(NULL AS STRING) AS common_factor
  FROM fleet.risk_predictions AS candidate
  WHERE candidate.score >= 50
    AND NOT EXISTS (
      SELECT 1
      FROM fleet.alerts_out AS previous
      WHERE previous.machine_id = candidate.machine_id
        AND previous.type = "predictive_failure"
        AND previous.created_at >= TIMESTAMP_SUB(candidate.generated_at, INTERVAL 24 HOUR)
        AND previous.created_at < candidate.generated_at
        AND previous.score >= candidate.score
    )
) AS source
ON target.alert_id = source.alert_id
WHEN NOT MATCHED THEN
  INSERT (
    alert_id, machine_id, zone_id, created_at, type, severity, score, confidence,
    summary, suspected_component, recommended_action, evidence, related_machine_ids,
    common_factor, delivered_at, is_sample
  )
  VALUES (
    source.alert_id, source.machine_id, source.zone_id, source.created_at, source.type,
    source.severity, source.score, source.confidence, source.summary,
    source.suspected_component, source.recommended_action, source.evidence,
    source.related_machine_ids, source.common_factor, NULL, FALSE
  );

SELECT *
FROM ML.DETECT_ANOMALIES(
  MODEL fleet.engine_temp_arima,
  STRUCT(0.90 AS anomaly_prob_threshold),
  (
    SELECT
      DATE(timestamp) AS day,
      machine_id,
      AVG(engine_temp_c) AS engine_temp_c
    FROM fleet.telemetry
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
    GROUP BY day, machine_id
  )
)
WHERE is_anomaly;

SELECT * FROM ML.PREDICT(MODEL fleet.machine_peers, (SELECT * FROM fleet.telemetry_features LIMIT 100));
