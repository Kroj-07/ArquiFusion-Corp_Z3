# Recuperacion e integracion unica

## Cuenta principal

AWS receptor de B y propietario de los datos: **057730774138 (Kiara), us-east-1**.
Stack de A: af-test-root. Stack nuevo de C: af-z3-c. El script Desplegar_C_Sobre_A.ps1 verifica la cuenta antes de modificar recursos. Reutiliza las tablas y el bus que A publico en SSM; no crea otro af-test-data. El piloto de 532362123916 queda como respaldo, no es receptor de alertas GCP.

El camino principal es: ingesta A -> SQS/Lambda/DynamoDB de A -> puente/BigQuery de B -> alerta HMAC a API A -> bus A -> Receiver C -> SF1/SF3 -> explicacion Cloudflare -> asignacion/callback/cierre C. Los callbacks del navegador se envian a ApiBase del stack C, no a los endpoints de callback antiguos de A.

## Fallo corregido

Las ramas de SF1 se llaman Prepare_create, Prepare_context y Prepare_explain. Cada rama de SF3 usa NotifyRole_ROL. StartAt y States se generan juntos para que las referencias coincidan. Se conserva el orden de ramas, los payloads y la logica de incidentes.

El despliegue llama scripts/validate_workflows.py antes de crear/eliminar recursos. Primero comprueba nombres y referencias; despues llama ValidateStateMachineDefinition para STANDARD y EXPRESS en AWS con ARN ficticios validos. Esto valida sintaxis sin crear maquinas, pero no demuestra permisos efectivos ni ejecucion correcta. Si el resultado no es OK, se detiene.

## 1. Validar desde cualquier cuenta Academy propia

    .\.venv-cloud\Scripts\python.exe infra/part-c/build_workflows.py
    .\.venv-cloud\Scripts\python.exe scripts/validate_workflows.py

Compartir result y diagnostics; no son secretos. Si aparece AccessDenied del validador, no afirmar que paso: revisar permisos o validar desde la cuenta principal antes de desplegar.

## 2. Desplegar C en la cuenta de Kiara

Kiara aplica esta actualizacion en su copia del repo. Necesita Python 3.12 y SAM para empaquetar el backend. En PowerShell, desde la raiz:

    powershell -ExecutionPolicy Bypass -File .\Desplegar_C_Sobre_A.ps1

Con URL de Cloud Run ya disponible:

    powershell -ExecutionPolicy Bypass -File .\Desplegar_C_Sobre_A.ps1 -GcpApiBase "https://SERVICIO-NICO.run.app"

El script debe mostrar cuenta 057730774138. No intercambiar claves AWS por chat para hacerlo desde otra cuenta. Cada persona ejecuta los comandos con su propia sesion autorizada.

No configurar el parametro IncidentWorkflowArn del stack A con SF1: la regla nueva conecta el bus A con Receiver C, que arma el payload correcto. Conectar tambien A directamente a SF1 podria iniciar el incidente dos veces o con un payload distinto.

## 3. Tres secretos de integracion diferentes

1. B -> A: arquifusion/test/alert-hmac de AWS Kiara. B debe usar EXACTAMENTE su valor en B_ALERT_HMAC_SECRET de Cloud Run. El nombre de Secret Manager Google puede variar; verificar que la variable lea el secreto correcto. Firmar timestamp.cuerpo.
2. AWS C -> Cloudflare: CloudflareSecretArn del stack af-z3-c. Obtener con scripts/pilot.py cloudflare-key --stack af-z3-c --copy. Guardar valor como Secret SHARED_KEY en Cloudflare.
3. AWS C -> GCP consultas: GcpAuthSecretArn del stack af-z3-c. Obtener con scripts/pilot.py gcp-key --stack af-z3-c --copy. Nico lo configura como B_API_AUTH_SECRET de Cloud Run y despliega una revision que cargue esa version. Firma c-1; no confundir con alert-hmac.

El JWT de acceso de C es otro secreto independiente; se provisionan tokens temporales desde una sesion AWS autorizada. No incluir secretos ni tokens en capturas o videos.

## 4. Sembrar y probar en la cuenta principal

    .\.venv-cloud\Scripts\python.exe scripts/pilot.py seed --stack af-z3-c
    .\.venv-cloud\Scripts\python.exe scripts/pilot.py smoke --stack af-z3-c
    .\.venv-cloud\Scripts\python.exe scripts/pilot.py frontend --stack af-z3-c
    npm --prefix part-c/frontend ci
    npm --prefix part-c/frontend run build
    .\.venv-cloud\Scripts\python.exe scripts/pilot.py token --stack af-z3-c --role admin --copy
    npm --prefix part-c/frontend run preview -- --port 5173

Para probar la tuberia real de A y B:

    .\.venv-cloud\Scripts\python.exe scripts/pilot.py simulate --stack af-z3-c --via part-a --machine MCH-000001

Esto solo envia la lectura. El incidente requiere que B calcule y envie su alerta; no se afirma prediccion completada por recibir HTTP 200 de ingesta. Nico debe demostrar un POST de alerta aceptado por A y su fila de BigQuery. Usar una maquina que exista en AWS (MCH-000001 queda sembrada).

Para probar C separadamente mientras B termina:

    .\.venv-cloud\Scripts\python.exe scripts/pilot.py simulate --stack af-z3-c --via pilot --machine MCH-000002

Esta ruta dispara reglas multivariables, no ML. Se usa otra maquina para no abrir flujos simultaneos del mismo incidente. La explicacion puede provenir realmente de Workers AI en ambas rutas.

## 5. Recuperar nuestro stack fallido sin perder la tabla retenida

En la cuenta 532362123916:

    .\.venv-cloud\Scripts\python.exe scripts/inspect_failed_pilot.py

Esto consulta y guarda un inventario en el directorio personal .arquifusion-recovery, fuera del repo. No elimina nada. Coordination DELETE_SKIPPED permanece fuera de la gestion activa del stack y puede seguir generando costo. No tiene API operativa ni tokens nuevos que se deban reutilizar.

Solo si se necesita volver a levantar el respaldo independiente:

    powershell -ExecutionPolicy Bypass -File .\Desplegar_Piloto.ps1 -ExpectedAccount 532362123916 -RecoverFailedStack -CloudflareUrl "https://arquifusion-ai-z3.guillermo-gamboa.workers.dev"

Tras validar AWS, recover_pilot.py permite eliminar exclusivamente af-z3-pilot o af-z3-c en ROLLBACK_COMPLETE, con cuenta esperada y reporte guardado. No elimina af-test-data ni llama DeleteTable. Al crear otra vez, Coordination tiene un nombre fisico nuevo; la tabla retenida antigua se conserva. No importar esa tabla sin necesidad ni borrar toda la cuenta para resolver el rollback.

Mantener este respaldo sin conexion GCP durante la demo principal. No copiar el HMAC de nuestro AWS a Google si el receptor sigue siendo Kiara.

## 6. Backblaze despues del recorrido principal

    .\.venv-cloud\Scripts\python.exe scripts/pilot.py configure-b2 --stack af-z3-c
    .\.venv-cloud\Scripts\python.exe scripts/pilot.py backup --stack af-z3-c
    .\.venv-cloud\Scripts\python.exe scripts/pilot.py backup-status --stack af-z3-c

## Comprobaciones pendientes

- Validacion AWS con result OK en ambos flujos.
- Stack C CREATE_COMPLETE y bootstrap autorizado operativo.
- B alerta hacia API de A y mismo evento capturado por C.
- Cloudflare devuelve texto/modelo/fuentes reales; healthz no basta.
- Confirmacion, inicio y cierre actualizan estado y stock una sola vez.
- Todas las escrituras concurrentes de A y C deben respetar el versionado antes de afirmar aislamiento completo. Para la demo, pausar el generador mientras se confirma/cierra una intervencion.
- Respaldo restaurado con SHA-256 identico antes de afirmar recuperacion B2.
