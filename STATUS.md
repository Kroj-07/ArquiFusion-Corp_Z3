# Estado del proyecto

Última actualización: 15 de noviembre de 2026.

## Qué está desplegado y funcionando

- **AWS** (cuenta Learner Lab de Kiara): ingesta por API → SQS → Lambda → DynamoDB, API `/v1` con JWT por rol, alertas firmadas con HMAC, y los workflows SF-1 (incidentes) y SF-3 (notificaciones por rol).
- **Google Cloud** (Nico): datos en BigQuery, modelos en BigQuery ML, API en Cloud Run y Gemini para las explicaciones.
- **Cloudflare** (Guillermo): la web en Pages y un Worker con Workers AI para explicaciones de incidentes. El login pasa por un Worker que reenvía a AWS.

La web se prueba siguiendo [PRUEBAS_TA.md](PRUEBAS_TA.md). Con eso se repite el ciclo completo: lectura de prueba, incidente, asignación, atención y cierre. La alerta enviada desde GCP a AWS quedó registrada como `ALT-B-TEST-002` (máquina `MCH-999001`, incidente `INC-6EC005997EF2`).

## Cambios al contrato que acordamos

- La firma de alertas es HMAC sobre `timestamp.cuerpo`, con el secreto `arquifusion/{env}/alert-hmac`.
- Usamos JWT HS256 en vez de Cognito. Al final el login es usuario y contraseña contra la API de AWS.
- Los nombres de tablas en SSM quedaron bajo `/data/` (el contrato decía `/ddb/`).
- El puente a Pub/Sub lee el stream de Telemetry (datos ya validados), no la cola cruda.
- La firma C→B es aparte de la de alertas B→A (ver [contract/CONEXION_KIARA_NICO.md](contract/CONEXION_KIARA_NICO.md)).

## Problemas que arreglamos al juntar las tres partes

- B firmaba solo el cuerpo y A esperaba `timestamp.cuerpo`, así que todas las alertas daban 401. Se corrigió en `part-b/app/security.py` y se agregó `tests/integration/test_ab_alert_signature.py`.
- B armaba la URL como `.../v1/v1/alerts`. Ahora tolera la base con o sin `/v1`.
- El puente mandaba JSON anidado y la tabla de BigQuery es plana; se agregó `part-a/bridge/pubsub_bridge/flatten.py`.
- Faltaban el tópico y la suscripción de Pub/Sub en el Terraform de B.
- SF-2 promovía modelos por MAE, pero B guarda precision y recall; ahora usa F1.
- Cubrimos el problema 12 (patrones previos a la falla) con `part-b/bigquery/05_precursors.sql`.

## Lo que no pudimos verificar

- Restauración de respaldos, alta disponibilidad entre regiones y la prueba de 5.000 máquinas.
- El pipeline de entrenamiento automático completo. Que el endpoint de predicción responda no demuestra precisión del modelo.
- Azure y Backblaze no participan en esta versión. Hay código de respaldo a Azure en `part-a/backup` y `part-c/frontend/DEPLOY_AZURE.md`, de un plan anterior.

## Pendiente (no alcanzamos a hacerlo)

- Endpoint de `failure_precursors` en la API de B, deriva de combustible con CUSUM y alertas desde ARIMA_PLUS.
- El paso "generar alertas por zona" en SF-2.
- Medir los costos con una corrida real (`load-tests/runner`) y confirmar API Gateway y X-Ray en las calculadoras.
- Copiar el secreto `alert-hmac` de AWS a Secret Manager de GCP cuando se despliegue en otra cuenta.
