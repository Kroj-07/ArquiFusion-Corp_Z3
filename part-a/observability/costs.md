# Costos estimados por maquina al mes — ArquiFusion Parte A

Generado con `python part-a/observability/cost_model.py` (cambia `--interval` o `--xray-rate` y se recalcula).
Precios de lista **us-east-1**, en USD, **sin capa gratuita** (estimación conservadora).

## Estado de los precios

- **Verificados** contra páginas o anuncios oficiales (15-nov-2026): Lambda, DynamoDB on-demand, SQS, Step Functions Standard, CloudWatch (logs, métricas, alarmas, dashboard), S3 Standard y PUT, Pub/Sub, suscripción BigQuery, almacenamiento BigQuery y Azure Blob Hot LRS (East US).
- **No verificados**: API Gateway HTTP ($1,00/M), X-Ray ($5/M), precio arm64 de Lambda (las funciones son arm64 pero el modelo usa el precio x86, algo más caro: conservador) y operaciones de escritura de Azure Blob (no modeladas). Confirmar en las calculadoras antes de dar la cifra final. Todos están en `cost_model.py`, diccionario `P`.
- Este modelo **no es una medición**: el plan pide usar también el consumo real de la corrida de carga (`load-tests/runner`); cuando se ejecute, sustituir los supuestos de abajo por lo medido.

## Supuestos

| Supuesto | Valor | Por qué importa |
|---|---|---|
| Frecuencia por máquina | 1 mensaje cada 30 s = 86.400 al mes | Es el factor que más mueve el costo: todo lo variable es lineal en esto |
| Tamaño de mensaje | 0,5 KB | Cabe en 1 WRU de DynamoDB |
| Entrada | API Gateway HTTP (`POST /v1/telemetry`, contrato §6) → Lambda ingesta → SQS | El endpoint lo fija el contrato; el uso de SQS lo asume este modelo (la edad de cola y la DLQ dependen de ello) |
| Consumidor | Lambda por lote de 10, 256 MB, 250 ms | |
| Escrituras DynamoDB | 2 por mensaje (histórico + último estado) | |
| Retención | TTL de 30 días (contrato §8) | Sin TTL el almacenamiento crece cada mes |
| S3 | Parquet de telemetría, ~4x más compacto, 1 objeto por ~1.000 mensajes | Contrato §8 prevé `telemetry/` en Parquet; el tamaño es un supuesto |
| Logs | 0,7 KB por invocación | Bajar el nivel a WARN reduce esta fila |
| X-Ray | 1 % de muestreo | Ver nota abajo |

Supuesto: 1 mensaje cada 30 s por maquina = 86,400 mensajes/maquina/mes

| Componente | USD/maquina/mes (variable) |
|---|---:|
| API Gateway HTTP (entrada) | 0.0864 |
| Lambda ingesta | 0.0265 |
| SQS (envio + recepcion + borrado) | 0.0415 |
| Lambda consumidora | 0.0109 |
| DynamoDB escrituras (2 por mensaje) | 0.1080 |
| DynamoDB lecturas (API/consultas, 0,1 por mensaje) | 0.0011 |
| DynamoDB almacenamiento (TTL 30 dias) | 0.0103 |
| Puente Pub/Sub (datos a Google, Parte A) | 0.0032 |
| Pub/Sub -> BigQuery (suscripcion, Parte B) | 0.0040 |
| BigQuery almacenamiento activo (30 dias, 0,15 KB/fila) | 0.0000 |
| Azure Blob respaldo Parquet (30 dias, sin operaciones) | 0.0002 |
| S3 Parquet de telemetria (almacenamiento + PUT) | 0.0007 |
| CloudWatch Logs (ingesta + consumidora) | 0.0317 |
| X-Ray (trazas muestreadas) | 0.0043 |
| **Subtotal variable** | **0.3288** |

| Componente fijo | USD/mes (total flota) |
|---|---:|
| SF-2 (1 ejecucion/dia, ~25 transiciones) | 0.02 |
| CloudWatch metricas personalizadas (EMF, ~8) | 2.40 |
| CloudWatch alarmas (8) | 0.80 |
| CloudWatch dashboard (1) | 3.00 |
| **Subtotal fijo** | **6.22** |

| Flota | Variable/maq | Fijo/maq | **Total USD/maquina/mes** | Total flota USD/mes |
|---:|---:|---:|---:|---:|
| 100 | 0.3288 | 0.0622 | **0.3910** | 39.10 |
| 1,000 | 0.3288 | 0.0062 | **0.3351** | 335.05 |
| 5,000 | 0.3288 | 0.0012 | **0.3301** | 1650.38 |

## Lectura rápida

- **Costo total aproximado: US$ 0,32 a 0,38 por máquina al mes**, según el tamaño de la flota. A 5.000 máquinas son unos US$ 1.600 al mes.
- Lo fijo (métricas, alarmas, dashboard) pesa solo con flotas pequeñas: a 100 máquinas añade ~US$ 0,06 por máquina; a 5.000 es despreciable.
- **DynamoDB escrituras es lo más caro** (~1/3 del total). Una escritura por mensaje en vez de dos bajaría ~US$ 0,05 por máquina.
- **API Gateway** es el segundo. Es un costo de entrada fijado por la arquitectura (API Gateway → SQS → Lambda).
- **X-Ray es sensible al muestreo**: al 5 % costaría unos US$ 0,02 por máquina, cinco veces más que al 1 %. Por eso `observability/template.yaml` lo deja en 1 %.
- **Lo que no incluye**: consultas y BigQuery ML (Parte B, se cobran por TiB procesado y dependen del uso), Vertex AI/Gemini, Cloud Run, operaciones de escritura en Azure Blob ni transferencia de datos saliente entre nubes.
- **Opcionales de `infra/part-a/data/template.yaml`, apagados por defecto y NO modelados**: replicación S3 entre regiones (`EnableReplication`: transferencia entre regiones + PUT de replicación) y Global Tables de Alerts/Incidents (`EnableGlobalTables`: escrituras replicadas, más caras). Activarlos sube el costo; avísame y los agrego al modelo.
- Las tablas Machines, Alerts, Incidents, Technicians e Inventory tienen PITR (respaldo continuo, se cobra por GB-mes); son tablas pequeñas, así que se ignoran. Telemetry no tiene PITR (el histórico vive en S3).
- El SF-2 corre una vez al día con unas 25 transiciones: centavos al mes.

## Reproducir

```
python part-a/observability/cost_model.py                 # 30 s entre mensajes
python part-a/observability/cost_model.py --interval 10   # 1 mensaje cada 10 s
python part-a/observability/cost_model.py --xray-rate 0.05
```
