# Parte B · Datos, analítica e IA

Base implementable para el contrato del equipo: genera telemetría y alertas sintéticas, prepara BigQuery/BigQuery ML y publica las rutas que consume C. El simulador produce datos reproducibles; no son lecturas de máquinas reales ni prueban precisión en producción.

## Datos de prueba locales

Requiere Python 3.12. Desde la raíz del repo:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe part-b\generator\generate.py --seed 17 --machines 50 --days 30 --start 2026-10-15T00:00:00Z
```

Genera `part-b/data/sample/` con:

- `telemetry.jsonl`: lecturas con el formato 6.2, además de `ingested_at`.
- `machines.jsonl`: catálogo de flota.
- `failure_labels.jsonl` y `failure_events.jsonl`: verdad-terreno separada de la telemetría para entrenar y evaluar.
- `alerts.jsonl`: 20 ejemplos del formato 6.4; cubren los siete tipos y las cinco severidades.

## BigQuery

Selecciona el proyecto GCP activo con `gcloud config set project PROJECT_ID` y configura Application Default Credentials. Ejecuta los SQL en orden (el dataset debe existir antes de cargar):

```powershell
.\.venv\Scripts\python.exe -m pip install -r part-b\requirements.txt
.\.venv\Scripts\python.exe part-b\scripts\run_sql.py --project PROJECT_ID --file part-b\bigquery\01_schema.sql
.\.venv\Scripts\python.exe part-b\scripts\load_bigquery.py --project PROJECT_ID
.\.venv\Scripts\python.exe part-b\scripts\run_sql.py --project PROJECT_ID --file part-b\bigquery\02_features_and_analytics.sql
.\.venv\Scripts\python.exe part-b\scripts\run_sql.py --project PROJECT_ID --file part-b\bigquery\03_models_and_evaluation.sql
.\.venv\Scripts\python.exe part-b\scripts\run_sql.py --project PROJECT_ID --file part-b\bigquery\04_predictions.sql
.\.venv\Scripts\python.exe part-b\scripts\run_sql.py --project PROJECT_ID --file part-b\bigquery\05_precursors.sql
```

El cargador aplanará `location` y `metrics` al esquema de `fleet.telemetry`, y hará `MERGE` por clave natural para que repetir la carga no duplique registros. El puente de A conserva el mensaje JSON del contrato; al escribir a la tabla BigQuery debe mapear los campos anidados a las columnas aplanadas de 6.12.

El entrenamiento excluye máquinas de evaluación mediante `is_eval_machine`; las métricas se obtienen sobre máquinas separadas. La tabla `model_runs` registra la evaluación y deja `promoted=false`: el modelo no se considera promovido automáticamente por esta primera versión.
El SQL de predicciones materializa alertas de riesgo medio o mayor en `alerts_out`, con ID determinista por máquina/lectura y supresión de repeticiones no crecientes durante 24 horas. El pipeline analítico de A (SF-2) debe invocar `POST /v1/jobs/dispatch-alerts` después del cálculo; la ruta envía HMAC a A y marca cada alerta entregada solo tras recibir aceptación. Si el envío se reintenta, A debe mantener la idempotencia por `alert_id` del contrato.

## API local y pruebas

Instala dependencias y configura secretos solo en el entorno local, sin subir `.env`:

```powershell
.\.venv\Scripts\python.exe -m pip install -r part-b\requirements-dev.txt
$env:B_API_AUTH_SECRET = "local-test-secret"
$env:B_ALERT_HMAC_SECRET = "local-alert-secret"
$env:GOOGLE_CLOUD_PROJECT = "PROJECT_ID"
$env:BIGQUERY_DATASET = "fleet"
$env:GOOGLE_CLOUD_LOCATION = "us-central1"
$env:A_API_BASE = "https://AWS_API_BASE"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir part-b --host 127.0.0.1 --port 8080
```

Fuera de `/healthz`, cada petición requiere la firma `c-1` acordada en [contract/CONEXION_KIARA_NICO.md](../contract/CONEXION_KIARA_NICO.md); la clave debe coincidir con `B_AUTH_SECRET_ARN` de C. La firma de alertas hacia A es HMAC-SHA256 del cuerpo exacto, con `x-timestamp` y `x-signature`, y comparte el secreto `arquifusion/alert-hmac` en GCP Secret Manager y AWS Secrets Manager. El timestamp se limita a cinco minutos.

Rutas de integración de C:

| Ruta | Respuesta de datos |
|---|---|
| `GET /v1/analytics/fuel` | `machine_id, actual_lph, expected_lph, delta_pct` |
| `GET /v1/analytics/utilization` | `machine_id, sampled_operating_pct, cost_index` |
| `GET /v1/analytics/spare-parts?zone_id=` | demanda y stock mínimo sugerido |
| `GET /v1/analytics/common-cause` | `zone_id, machine_ids, hypothesis, confirmed` |
| `GET /v1/predictions/maintenance` | `machine_id, remaining_operating_hours, basis` |
| `GET /v1/predictions/risk?limit=100` | score de riesgo por máquina |
| `GET /v1/ai/explain?alert_id=&role=` | `role, text, model, grounded_on` |
| `POST /v1/ai/ask` | respuesta Gemini sustentada en historial real |
| `POST /v1/alerts/forward` | valida el formato 6.4 y reenvía alerta firmada a `POST /v1/alerts` de A |
| `POST /v1/jobs/dispatch-alerts?limit=100` | vacía alertas de riesgo pendientes de BigQuery a AWS; usar desde SF-2 |

`/v1/ai/*` consulta BigQuery y Vertex AI. No hay respuestas generativas de relleno: sin datos, configuración o Vertex AI disponible, la API falla explícitamente. El endpoint de explicación exige que `alert_id` exista en `fleet.alerts_out`.

Pruebas:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s part-b\tests -v
```

## Despliegue en GCP

Se requiere una cuenta/proyecto de Google Cloud con facturación habilitada; AWS no sustituye BigQuery, Pub/Sub ni Vertex AI. El despliegue Terraform crea dataset, Artifact Registry, cuenta de servicio, permisos y Cloud Run; el ejemplo de Cloud Run escala a cero. No crea valores de secretos ni publica claves. La primera aplicación debe ser por etapas porque Cloud Run requiere que ya existan versiones secretas:

1. Ejecutar `terraform init` y `terraform apply -var="project_id=..." -var="deploy_service=false"` para crear APIs, Artifact Registry, dataset, cuenta de servicio, IAM y recursos Secret Manager.
2. Crear versiones de `arquifusion-b-api-auth` y `arquifusion-alert-hmac` en Secret Manager con valores aleatorios compartidos de forma segura con C/A. No guardar los valores en Terraform ni terminales compartidas.
3. Crear tablas y vistas con los SQL anteriores. Construir y publicar la imagen Docker en Artifact Registry.
4. Aplicar otra vez con `-var="deploy_service=true" -var="container_image=..." -var="aws_api_base=..."`.
5. Pub/Sub: `terraform apply` ya crea el tópico `telemetry-raw`, la cuenta publicadora del puente de A y (con `-var create_telemetry_subscription=true`, **después** de correr `01_schema.sql`) la suscripción a `fleet.telemetry`. El puente de A publica JSON **aplanado** (`part-a/bridge/pubsub_bridge/flatten.py`). Entregar la clave de `af-bridge-publisher` solo a AWS Secrets Manager (`gcp-pubsub-key`), y entregar la URL de Cloud Run a C por el canal seguro del equipo.

No se ha aplicado Terraform ni desplegado en una cuenta cloud de equipo desde este entorno. La validez en Learner Lab, cuotas, facturación, permisos del puente y la firma de extremo a extremo deben probarse con las cuentas reales.
