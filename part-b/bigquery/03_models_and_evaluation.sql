CREATE OR REPLACE MODEL fleet.failure_risk_model
OPTIONS (
  MODEL_TYPE = "BOOSTED_TREE_CLASSIFIER",
  INPUT_LABEL_COLS = ["failure_within_48h"],
  AUTO_CLASS_WEIGHTS = TRUE,
  MAX_ITERATIONS = 30,
  DATA_SPLIT_METHOD = "NO_SPLIT"
) AS
SELECT
  temp_mean_24h,
  vibration_mean_24h,
  pressure_mean_24h,
  fuel_mean_24h,
  load_per_machine_hour,
  operating_samples_24h,
  failure_within_48h
FROM fleet.telemetry_features
WHERE NOT is_eval_machine;

SELECT *
FROM ML.EVALUATE(
  MODEL fleet.failure_risk_model,
  (
    SELECT
      temp_mean_24h,
      vibration_mean_24h,
      pressure_mean_24h,
      fuel_mean_24h,
      load_per_machine_hour,
      operating_samples_24h,
      failure_within_48h
    FROM fleet.telemetry_features
    WHERE is_eval_machine
  )
);

CREATE OR REPLACE MODEL fleet.engine_temp_arima
OPTIONS (
  MODEL_TYPE = "ARIMA_PLUS",
  TIME_SERIES_TIMESTAMP_COL = "day",
  TIME_SERIES_DATA_COL = "engine_temp_c",
  TIME_SERIES_ID_COL = "machine_id",
  DATA_FREQUENCY = "DAILY",
  AUTO_ARIMA = TRUE
) AS
SELECT
  DATE(timestamp) AS day,
  machine_id,
  AVG(engine_temp_c) AS engine_temp_c
FROM fleet.telemetry
GROUP BY day, machine_id;

CREATE OR REPLACE MODEL fleet.machine_peers
OPTIONS (
  MODEL_TYPE = "KMEANS",
  NUM_CLUSTERS = 5,
  STANDARDIZE_FEATURES = TRUE
) AS
SELECT
  temp_mean_24h,
  vibration_mean_24h,
  pressure_mean_24h,
  fuel_mean_24h,
  load_per_machine_hour
FROM fleet.telemetry_features
WHERE NOT is_eval_machine;

INSERT INTO fleet.model_runs (
  model, trained_at, precision, recall, mean_lead_time_h, promoted, evaluation_notes
)
SELECT
  "failure_risk_model",
  CURRENT_TIMESTAMP(),
  precision,
  recall,
  NULL,
  FALSE,
  "Evaluación en máquinas separadas por machine_id; revisar métricas antes de promover"
FROM ML.EVALUATE(
  MODEL fleet.failure_risk_model,
  (
    SELECT
      temp_mean_24h,
      vibration_mean_24h,
      pressure_mean_24h,
      fuel_mean_24h,
      load_per_machine_hour,
      operating_samples_24h,
      failure_within_48h
    FROM fleet.telemetry_features
    WHERE is_eval_machine
  )
);
