# STATUS — ArquiFusion Fleet Intelligence (Parte A)

Última actualización: 2026-11-15 (integración A+B+C)

| Frente | Hecho | En curso | Bloqueado por |
|---|---|---|---|
| Fundación (raíz, seguridad, scripts, CI) | Raíz anida los 8 stacks; secretos y SSM; `deploy.sh`, `destroy.sh`, `set_secrets.sh`, `smoke_test.sh`, `check_templates.py`, CI | — | Despliegue real en el Lab |
| Ingesta | Código con pruebas; plantilla API HTTP → SQS+DLQ → Lambda | — | Confirmar integración directa API Gateway → SQS con LabRole |
| Datos | 6 tablas, S3, Global Tables, stream de Telemetry, índice `incident_id-index` | — | — |
| API | Endpoints, autorizador (REST y HTTP), alertas HMAC, callbacks; 77 pruebas | — | Aceptación de B (HMAC) y C (JWT) |
| Puente y respaldo | Código y plantilla; fuente = stream de Telemetry | — | Clave GCP, SAS de Azure, proyecto de B |
| SF-2 | Máquina de estados con mocks | Versión real de `sync_bigquery` | Tablas BigQuery de B |

## Decisiones y cambios de contrato
- Contrato v1.3: HMAC sobre `timestamp.cuerpo`, secreto `arquifusion/{env}/alert-hmac`; JWT HS256 en vez de Cognito.
- SSM de tablas bajo `/data/` (no `/ddb/`); entornos `test` y `shared`; ingesta con su propio API HTTP (JWT `admin`).
- El puente lee el stream de Telemetry (datos ya validados), no la cola cruda.

## Pendientes de confirmar
- Que la cuenta sea Learner Lab (SES, Step Functions, Global Tables, EventBridge Scheduler, `events.amazonaws.com` en LabRole).
- Que B acepte el cambio del secreto HMAC; que C acepte el autorizador JWT.
- `sam validate --lint` y un despliegue real: nada se ha probado contra AWS.

## Integración A+B+C (2026-11-15) — conflictos hallados y resueltos
| # | Conflicto | Resolución |
|---|---|---|
| 1 | B firmaba alertas con `HMAC(cuerpo)`; A exige `HMAC("timestamp.cuerpo")` → 401 en todo `POST /v1/alerts` | `part-b/app/security.py` + pruebas de B y `tests/integration/test_ab_alert_signature.py` |
| 2 | B construía `.../v1/v1/alerts` (el SSM `api/base-url` ya termina en `/v1`) | `part-b/app/main.py` tolera con o sin `/v1` |
| 3 | El puente publicaba JSON anidado; `fleet.telemetry` es plana → Pub/Sub→BigQuery rechazaba todo | `part-a/bridge/pubsub_bridge/flatten.py` |
| 4 | Terraform de B no creaba tópico ni suscripción | `part-b/deploy/terraform/main.tf` (suscripción tras crear tablas: `create_telemetry_subscription`) |
| 5 | SF-2 promovía por MAE; B guarda precision/recall en `model_runs` | `part-a/sf2/functions/pipeline.py` (F1 + tope de caída de recall) |
| 6 | Tras mover infra a `infra/part-a/`: rutas rotas (`CodeUri`, `check_templates.py`, `deploy.sh`), `events-template.yaml` viejo, `Role` en Globals | rutas corregidas; `cfn-lint` 0 errores |
| 7 | README de A guardado como `README (2).md`; README raíz era el de C | README raíz mínimo; el de C en `part-c/README.md` |
| 8 | Problema 12 (patrones previos a la falla) sin cobertura | `part-b/bigquery/05_precursors.sql` |

## Sigue pendiente
- Copiar el secreto `arquifusion/{env}/alert-hmac` (lo genera AWS) a Secret Manager de GCP (`arquifusion-alert-hmac`); B lo lee como `B_ALERT_HMAC_SECRET`.
- Sin implementar (B): endpoint de `failure_precursors`, deriva de combustible con CUSUM, alertas desde ARIMA_PLUS; en SF-2 falta el paso "generar alertas por zona" del plan v3.
- Costos: medir con la corrida real (`load-tests/runner`) y confirmar API Gateway/X-Ray en las calculadoras.
- Nada de esto se probó contra AWS/GCP reales (no hay `sam`, `terraform` ni credenciales en este entorno).
