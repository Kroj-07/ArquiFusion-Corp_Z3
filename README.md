# ArquiFusion Fleet Intelligence

Sistema multi-nube para gestionar una flota de maquinaria: recibe telemetría, detecta fallas, abre incidentes, asigna técnicos y cierra el ciclo de mantenimiento. Lo hicimos para el hackathon del curso de Cloud Computing.

## Datos del equipo

| | |
|---|---|
| **Grupo** | Z3 / Grupo 17 |
| **Sección** | 2 |
| **Integrantes** | Kiara Luz Rojas Meza, Pedro Nicolás Solís Córdova, Guillermo Valentino Ceceu Gamboa Sanchez |

Cómo nos repartimos el trabajo:

| Parte | Responsable | Qué hace |
|---|---|---|
| **A** | Kiara | Núcleo en AWS: ingesta, datos, API, seguridad, alertas, workflows |
| **B** | Pedro Nicolás (Nico) | Google Cloud: generador de datos, BigQuery + ML, Cloud Run, Gemini |
| **C** | Guillermo | App web, asignación de técnicos, workflows de incidentes, Cloudflare |

---

## Credenciales para los TAs

La web está desplegada en **Cloudflare (Pages)**. Esta cuenta es solo para evaluar la interfaz:

```text
Usuario:    ta
Contraseña: ArquiFusion2026!
```

**URL de la web:** `<pegar aquí la URL de Cloudflare Pages>`

Notas rápidas:
- El rol no se elige desde el navegador: el servidor (AWS) verifica la contraseña y decide el rol.
- Es una cuenta de evaluación, no un sistema de registro de usuarios.
- Los pasos para repetir el ciclo completo están en [PRUEBAS_TA.md](PRUEBAS_TA.md) (resumidos abajo).

---

## Arquitectura (resumen corto)

Usamos **3 nubes**, cada una con un trabajo distinto:

| Nube | Para qué la usamos | Servicios |
|---|---|---|
| **AWS** | El núcleo: recibe los datos, guarda el estado y orquesta los incidentes | API Gateway, SQS (+ DLQ), Lambdas, DynamoDB, S3, Step Functions, Secrets Manager |
| **Google Cloud** | Analítica e IA | BigQuery y BigQuery ML (predicción, anomalías), Cloud Run (API de analítica), Gemini (explicaciones y asistente) |
| **Cloudflare** | Lo que ve el usuario | Pages (frontend), Workers (proxy de login hacia AWS y explicaciones con Workers AI) |

Flujo general:

```text
Máquina / simulador
      │  telemetría
      ▼
[AWS] API → SQS → Lambda de ingesta → DynamoDB
      │                                   │
      │                                   └─► puente → Pub/Sub → [GCP] BigQuery
      │                                                         (ML: riesgo, anomalías)
      │            alerta firmada (HMAC)                              │
      ◄───────────────────────────────────────────────────────────────┘
      ▼
[AWS] Step Functions (SF-1): abrir incidente → asignar técnico → avisar → atender → reponer → cerrar
      │
      ▼
[Cloudflare] Pages + Workers  ←  lo que ven los usuarios (mapa, incidentes, analítica)
```

Cosas de seguridad que sí implementamos:
- Las alertas de GCP hacia AWS van firmadas con HMAC-SHA256 (timestamp + cuerpo, ventana de 5 minutos) y son idempotentes por `alert_id`.
- La API de AWS usa JWT con roles. El navegador nunca recibe la clave compartida.
- Ningún secreto está en el repo: viven en Secrets Manager / SSM (AWS) y Secret Manager (GCP).

El contrato técnico entre las tres partes (formatos de mensajes, endpoints, firma) está en [contract/README.md](contract/README.md).

---

## Cómo está organizado el repo

```text
.
├── part-a/            Parte A (AWS): ingesta, API /v1, autorizador, alertas, puente a Pub/Sub,
│   ├── ingest/          respaldo, SF-2 (pipeline analítico), observabilidad y costos
│   ├── api/
│   ├── bridge/
│   ├── sf2/
│   ├── observability/
│   ├── security/
│   └── shared/        utilidades compartidas (HMAC)
├── part-b/            Parte B (Google Cloud)
│   ├── generator/       generador de telemetría/fallas sintéticas
│   ├── bigquery/        SQL en orden: 01 esquema → 05 precursores (incluye modelos ML)
│   ├── app/             API en Cloud Run (FastAPI) + asistente Gemini
│   ├── deploy/terraform/
│   └── data/sample/     datos de ejemplo
├── part-c/            Parte C (app)
│   ├── frontend/        React + Vite (mapa, incidentes, asignación, analítica)
│   └── backend/afc/     lógica de dominio, asignación de técnicos, demo local
├── infra/             Infraestructura como código
│   ├── part-a/          plantillas SAM/CloudFormation de A
│   ├── part-c/          SF-1 (incidentes), SF-3 (notificaciones por rol), plantillas de C
│   ├── pilot/           stack de despliegue del piloto (AWS + Cloudflare)
│   └── cloudflare/      Workers y Pages (login proxy, Workers AI)
├── contract/          Contrato técnico entre A, B y C + ejemplos JSON
├── load-tests/        Pruebas de carga (100 / 1.000 / 5.000 máquinas) y caos (SQS)
├── tests/integration/ Pruebas de integración A ↔ B (firma de alertas)
├── scripts/           Despliegue, pruebas, smoke test, validación de plantillas
├── PRUEBAS_TA.md      Guía paso a paso para probar la web
└── STATUS.md          Estado de la integración y pendientes
```

Si solo tienen poco tiempo, miren en este orden: **la web** → `PRUEBAS_TA.md` → `infra/part-c/sf1-incident.asl.json` → `part-b/bigquery/` → `part-a/api/`.

---

## Cómo probar la web (resumen)

Detalle completo en [PRUEBAS_TA.md](PRUEBAS_TA.md).

1. Entrar con el usuario `ta`.
2. En el centro de control, pulsar **Lectura de prueba**, elegir una máquina sin incidente activo y enviar **temperatura y vibración altas**. Esto publica una medición nueva en la cola de AWS (usa un detector por reglas, está identificado como tal).
3. Esperar unos segundos y revisar **Incidentes**. Si no se asignó técnico solo, ir a **Asignación de técnicos**, calcular y confirmar.
4. Abrir el incidente: evidencia + explicación generada por IA.
5. **Confirmar recepción** → **Iniciar atención**.
6. En **Intervención y cierre**, registrar una intervención y **Cerrar intervención**. El incidente pasa a *Resuelto* y el técnico queda libre.
7. En **Analítica operativa** se ven los módulos que consultan Cloud Run (BigQuery/Gemini). Si algo falla se muestra como "no disponible"; no inventamos resultados.

Si eligen **lectura normal**, no debería abrirse ningún incidente.

---

## Cobertura de los 14 problemas del reto

| # | Problema | Dónde está |
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

---

## Correr el proyecto en local (sin nube)

Requisitos: Python 3.12 y Node.js 20.19 o superior.

**Pruebas de todo el repo** (no necesitan credenciales cloud):

```bash
pip install pyyaml boto3 pyarrow
pip install -r part-b/requirements-dev.txt
scripts/run_tests.sh
```

**Demo local de la app** (Windows, PowerShell, desde la raíz):

```powershell
powershell -ExecutionPolicy Bypass -File .\Iniciar_Demo.ps1
```

Abre `http://127.0.0.1:5173` con un backend local y datos simulados. Detalles en [part-c/README.md](part-c/README.md).

**Generar datos sintéticos de la Parte B:**

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe part-b\generator\generate.py --seed 17 --machines 50 --days 30 --start 2026-10-15T00:00:00Z
```

---

## Desplegar

```bash
scripts/deploy.sh test us-east-1           # AWS: seguridad, datos, ingesta, eventos, API, puente, SF-2
scripts/set_secrets.sh test us-east-1 ...  # carga de secretos (HMAC, claves)
scripts/smoke_test.sh test us-east-1       # ingesta -> DynamoDB -> API, alerta firmada
scripts/destroy.sh test us-east-1          # limpiar
```

- **AWS (piloto + Cloudflare):** [infra/pilot/GUIA.md](infra/pilot/GUIA.md)
- **Google Cloud:** [part-b/README.md](part-b/README.md) (Terraform + SQL; el secreto HMAC de AWS se copia a Secret Manager de GCP)
- **Cloudflare:** Workers en `infra/cloudflare/`. La web se publica con `python scripts/build_public_web.py` y se sube el ZIP de `delivery/` a Pages.

---

## Qué quedó verificado y qué no

Preferimos ser claros con esto:

**Sí funciona y lo probamos:**
- Ciclo completo desde la web: lectura → cola de AWS → incidente → asignación → atención → cierre.
- Alerta firmada de GCP a AWS (caso de prueba `ALT-B-TEST-002`, máquina `MCH-999001`, incidente `INC-6EC005997EF2`).
- Endpoints de predicción de riesgo y Gemini en Cloud Run respondiendo HTTP 200.
- Pruebas unitarias e de integración locales (`scripts/run_tests.sh`).

**Límites que conocemos:**
- La flota, los catálogos y los históricos son **sintéticos**. No hay máquinas reales.
- La ruta de "Lectura de prueba" usa un detector por reglas, no un modelo de GCP.
- Que el endpoint de GCP responda no demuestra precisión del modelo ni un pipeline de entrenamiento automático completo.
- **Azure no participa en esta versión.** Hay código de respaldo y despliegue para Azure en el repo (`part-a/backup`, `part-c/frontend/DEPLOY_AZURE.md`) de un plan anterior, pero no está en uso.
- No hay verificación final de: restauración de respaldos, alta disponibilidad entre regiones, pruebas de 5.000 máquinas ni el pipeline completo de entrenamiento.
- El adaptador de AWS lee catálogos con `Scan` acotado a 1000 filas. Sirve para el piloto, no demuestra escala a miles.

Más detalle en [STATUS.md](STATUS.md).

---

## Documentación por carpeta

- [contract/README.md](contract/README.md): contrato técnico entre A, B y C
- [part-a/api/README.md](part-a/api/README.md): API y autorizador
- [part-a/observability/costs.md](part-a/observability/costs.md): modelo de costos
- [part-b/README.md](part-b/README.md): BigQuery, ML, Cloud Run, Terraform
- [part-c/README.md](part-c/README.md): app, asignación, SF-1 y SF-3
- [load-tests/README.md](load-tests/README.md): carga y caos
- [PRUEBAS_TA.md](PRUEBAS_TA.md): guía de evaluación
