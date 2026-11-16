# Integración C · acuerdos entre las tres partes

Lo que la Parte C (Guillermo) necesita de la Parte A (Kiara) y de la Parte B (Nico), y lo que ofrece a cambio.

## Con Kiara (Parte A, AWS)

C no asume nombres de tablas ni usa una cuenta distinta. La Lambda de C invoca por IAM un adaptador en **la misma cuenta y región** que los datos y las máquinas de estados. El adaptador mantiene las escrituras de negocio dentro del módulo A. Kiara nos pasa el ARN del adaptador.

Implementación de referencia lista para adaptar: `part-c/backend/afc/a_adapter.py`; despliegue: `infra/part-c/a-adapter-template.yaml`. Recibe nombres reales de tablas de A. Crea solo una tabla privada de comandos, no reemplaza datos de A. Las claves son estas:

| Entidad | PK | SK |
|---|---|---|
| Machines | machine_id | — |
| Incidents | machine_id | opened_at |
| Technicians | technician_id | — |
| Inventory | zone_id | part_id |
| Alerts | machine_id | created_at |
| Telemetry | machine_id | timestamp |

El lector de referencia usa Scan acotado en catálogos pequeños. Hay que cambiar `catalog()` por consultas indexadas antes de la prueba grande. La lectura de telemetría usa Query por máquina, máximo 1000 puntos. No se escanea toda la telemetría.

### Operaciones del adaptador

- `snapshot` → `{data:{machines:[], incidents:[], technicians:[], inventory:[], alerts:[], telemetry:[]}}`.
- `telemetry`, `machine_id` → `{data:[{timestamp,metrics:{...}}]}` ordenado cronológicamente.
- `lookup`, `command_id`, `request` → `{data:null}` o resultado previamente confirmado.
- `commit`, `command_id`, `request`, `expected`, `changes`, `result` → transacción todo o nada, con versiones y marcador durable de idempotencia.

No autorizar este adaptador como endpoint público. El rol de la Lambda de C necesita InvokeFunction sobre su ARN; el rol del adaptador tiene los permisos de lectura y TransactWriteItems de A.

### Campos que C necesita además del catálogo básico

| Entidad | Campos necesarios |
|---|---|
| Machine | machine_id, name opcional, model, zone_id, status, location{lat,lon}, last_seen, operating_hours_total, last_maintenance_at, metrics última lectura opcional, risk_score opcional, version |
| Incident | incident_id, machine_id, zone_id, opened_at, status, severity, score, summary, suspected_component, technician_id, alert_ids[], actions[], parts_replaced[], timeline[], version |
| Technician | technician_id, name, skills[], location, zone_id, availability, shift_end UTC, active_incident_id cuando está reservado, version |
| Inventory | zone_id, part_id, name, component, stock, min_stock, version; el adaptador agrega key=zone_id\|part_id |

Las filas anteriores sin `version` se interpretan como versión 1 en el adaptador. **Todas las escrituras posteriores de A también deben respetar e incrementar version**. De lo contrario, la protección de concurrencia pierde validez. No descontar stock otra vez en otro consumidor de `incident.closed`: C ya lo descuenta dentro de la transacción de cierre.

`downtime_started_at` de Machine es opcional. Si no existe una marca real de parada y confirmación de reinicio, C conserva downtime_minutes=null. `resolution_minutes` mide otra cosa: apertura a cierre del incidente.

Cuando A acepte una alerta, publicar en `arquifusion-events` un evento `detail-type=alert.created` cuyo `detail` sea el JSON de alerta del contrato. C crea o reutiliza el incidente, reserva al técnico y espera los callbacks. Los callbacks públicos son de la API C, autenticados por JWT; A no necesita manejar tokens de Step Functions.

## Con Nico (Parte B, Google Cloud)

Nico nos da una base HTTPS, sin `/v1` al final. C consume:

| Ruta | Respuesta `{data:...}` |
|---|---|
| GET /v1/analytics/fuel | `[{machine_id,actual_lph,expected_lph,delta_pct}]` |
| GET /v1/analytics/utilization | `[{machine_id,sampled_operating_pct,cost_index}]` |
| GET /v1/predictions/maintenance | `[{machine_id,remaining_operating_hours,basis}]` |
| GET /v1/analytics/common-cause | `[{zone_id,machine_ids:[],hypothesis,confirmed:false}]` |
| GET /v1/ai/explain?alert_id=...&role=... | `{role,text,model,grounded_on:[]}` |

`sampled_operating_pct` es proporción de muestras, 0..100. Si la utilización se calcula por tiempo, hay que cambiar el campo y el rótulo de la vista para que represente esa definición. No inventar `confidence` ni confundir riesgo con probabilidad.

C filtra resultados por las máquinas autorizadas del usuario. B solo recibe llamadas de backend; el secreto no se incorpora al frontend.

Para autenticar C→B se propone `x-signature-version=c-1`, `x-timestamp` UNIX y HMAC-SHA256 del texto `timestamp + '\nGET\n' + ruta_con_query + '\n'`. El secreto se guarda en AWS Secrets Manager (C) y GCP Secret Manager (B). Referencia de validación en `b_signature.py`. **Este acuerdo es solo para C→B y no cambia la firma de alertas B→A.** Se confirma antes de activar el modo live; si usan otro mecanismo, cambiar solo BClient.

Si B no responde, la UI muestra datos no disponibles. En el workflow, la evidencia de la alerta queda como texto determinístico claramente identificado; no se llama a eso una respuesta de Gemini.

## Autenticación y alcance

> **Nota:** esta sección describe el diseño inicial con Cognito. En la versión que entregamos no usamos Cognito: el login es usuario y contraseña contra la API de AWS (`part-c/backend/afc/password_auth.py`), que devuelve un JWT, y pasa por el Worker de Cloudflare (`infra/cloudflare/pages-worker.mjs`). La lógica de roles y alcance por zona/máquina es la misma.

API C valida en API Gateway el issuer y audience del cliente Cognito público. Esta implementación usa **ID token**, `token_use=id`, porque contiene los atributos de alcance. Si el equipo decide usar access tokens, Kiara debe añadir esos claims con el trigger adecuado y cambiar esta comprobación de forma coordinada.

Grupos: operator, technician, maintenance, supervisor, admin, manager. Atributos de Cognito: `custom:zone_ids`, `custom:machine_ids`, `custom:technician_id`. Listas separadas por comas. Configurar ReadAttributes en el cliente y **no permitir que el usuario escriba sus propios atributos de alcance**. Los grupos y alcances se asignan desde administración. Sin alcance no se otorga acceso por defecto a todas las zonas.

Los tokens de callback viven en una tabla privada de C, separados de los incidentes que ve la UI. Ack/close devuelven aceptación; la actualización final ocurre en el workflow y se observa en la siguiente lectura. Aprobaciones repetidas pueden devolver conflicto si la espera ya cambió; refrescar antes de reintentar.
