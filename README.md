# ArquiFusion Fleet Intelligence

Plataforma serverless en tres nubes para gestionar flotas de maquinaria: **AWS** opera (ingesta, datos, Step Functions, alertas),
**Google Cloud** analiza y razona (BigQuery ML, Gemini, Cloud Run) y **Azure** sirve la app y guarda un respaldo inmutable.
Cero servidores encendidos. Arquitectura: `ArquiFusion_Arquitectura.png` (se entrega por Canvas). Contrato: [contract/README.md](contract/README.md).

| Carpeta | Qué contiene | Dueña/o |
|---|---|---|
| `part-a/`, `infra/part-a/` | Ingesta, DynamoDB/S3, API `/v1`, seguridad, puente a Pub/Sub, respaldo a Azure, SF-2, observabilidad | A |
| `part-b/` | Generador de fallas, BigQuery (+ML), Cloud Run, Gemini, Terraform | B |
| `part-c/`, `infra/part-c/` | App web, asignación de técnicos, SF-1 y SF-3 | C |
| `load-tests/` | Carga (100 / 1.000 / 5.000 máquinas) y caos (apagar el consumidor 60 s) | A |

## Desplegar (A en AWS Learner Lab: `us-east-1` o `us-west-2`)
```bash
scripts/run_tests.sh                       # pruebas locales (sin nube)
scripts/deploy.sh test us-east-1           # seguridad, datos, ingesta, eventos, API, puente, SF-2, observabilidad
scripts/set_secrets.sh test us-east-1 --gcp-key-file clave.json --azure-sas-file sas.txt --show-hmac-for-gcp
scripts/smoke_test.sh test us-east-1       # ingesta -> DynamoDB -> API, alerta firmada
scripts/destroy.sh test us-east-1          # limpiar
```
- **B (Google Cloud):** [part-b/README.md](part-b/README.md) (Terraform + SQL; el secreto HMAC de AWS se copia a Secret Manager de GCP).
- **C (app local de demo):** [part-c/README.md](part-c/README.md) · despliegue en Azure: `part-c/frontend/DEPLOY_AZURE.md`.
- Ningún secreto vive en el repositorio: Secrets Manager (`arquifusion/{env}/…`) y SSM (`/arquifusion/{env}/…`).

## Cobertura de los 14 problemas del reto
| # | Problema | Dónde |
|---|---|---|
| 1 | Mantenimiento predictivo | `part-b/bigquery/03_models_and_evaluation.sql` (Boosted Tree), `04_predictions.sql` |
| 2 | Mantenimiento preventivo | `fleet.maintenance_predictions` · `GET /v1/predictions/maintenance` |
| 3 | Distribución de repuestos | `fleet.spare_parts_analytics` · `GET /v1/analytics/spare-parts` |
| 4 | Ubicación y estado | DynamoDB `machines` + `GET /v1/machines` · mapa en `part-c/frontend` |
| 5 | Asignación de técnicos | `part-c/backend/afc/assignment.py` (óptima vs. voraz) |
| 6 | Combustible | `fleet.fuel_analytics` · `GET /v1/analytics/fuel` |
| 7 | Productividad | `fleet.utilization_analytics` · `GET /v1/analytics/utilization` |
| 8 | Comportamientos inusuales | ARIMA_PLUS y K-Means en `03_models_and_evaluation.sql` |
| 9 | Comunicación por rol | SF-3 (`infra/part-c/sf3-notifications.asl.json`) + `part-a/events/notifier.py` |
| 10 | Historial de incidentes | DynamoDB `incidents` + `GET /v1/machines/{id}/incidents` |
| 11 | Incidentes simultáneos | `fleet.common_cause_analytics` (ST_CLUSTERDBSCAN) |
| 12 | Planificación con histórico | `fleet.failure_precursors` (`part-b/bigquery/05_precursors.sql`) |
| 13 | Escalar con costo razonable | `load-tests/runner`, `part-a/observability/costs.md` |
| 14 | Más allá del dashboard | alerta → SF-1 (`infra/part-c/sf1-incident.asl.json`) → asignar, avisar, reponer, cerrar |

Estado y pendientes: [STATUS.md](STATUS.md).
