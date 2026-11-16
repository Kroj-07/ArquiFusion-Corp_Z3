# Piloto Z3: AWS + Cloudflare + Backblaze

Para la entrega se conserva C y se sustituye su integración Cognito/Google por una ruta de piloto independiente. La plantilla original de C se mantiene. No usar las credenciales de otra persona: desplegar los stacks en una cuenta Academy propia o pedir a la persona responsable que ejecute el mismo paquete en su cuenta.

## 1. Desplegar en AWS

Desde la raíz del repo, con Python 3.12, SAM, AWS CLI y sesión Academy vigente:

    powershell -ExecutionPolicy Bypass -File .\Desplegar_Piloto.ps1

Si ya conoces la URL del Worker:

    powershell -ExecutionPolicy Bypass -File .\Desplegar_Piloto.ps1 -CloudflareUrl "https://arquifusion-ai-z3.TU-SUBDOMINIO.workers.dev"

El script crea o actualiza af-test-data y af-z3-pilot, sin recursos IAM nuevos ni replicación regional. Usa LabRole, cuyo trust debe incluir Lambda, Step Functions y EventBridge. No ejecutar simultáneamente dos despliegues sobre esos stacks en la misma cuenta. Si falla, revisar Events de CloudFormation antes de reintentar. En ROLLBACK_COMPLETE, la causa debe corregirse antes de eliminar solamente el stack fallido y recrearlo.

## 2. Cloudflare

En Workers & Pages crear arquifusion-ai-z3. Reemplazar el código por infra/cloudflare/worker.mjs. Agregar binding Workers AI con nombre AI. La variable opcional MODEL permite cambiar el modelo; el predeterminado usa @cf/meta/llama-3.2-3b-instruct. Verificar disponibilidad y cuota en el panel.

Generar la copia segura de la clave compartida:

    .\.venv-cloud\Scripts\python.exe scripts/pilot.py cloudflare-key --copy

Pegar el contenido del portapapeles como Secret SHARED_KEY en Settings > Variables and Secrets del Worker. No pegar en el código ni en chats. Deploy. La URL /healthz debe mostrar ai_binding=true y authentication_configured=true. Esto comprueba configuración, no una inferencia real: esa se comprueba desde el incidente.

Actualizar la URL en AWS ejecutando otra vez Desplegar_Piloto.ps1 con -CloudflareUrl. El script actualiza recursos, no borra tablas.

## 3. Datos y web

    .\.venv-cloud\Scripts\python.exe scripts/pilot.py seed
    .\.venv-cloud\Scripts\python.exe scripts/pilot.py smoke
    .\.venv-cloud\Scripts\python.exe scripts/pilot.py frontend
    npm --prefix part-c/frontend ci
    npm --prefix part-c/frontend run build
    .\.venv-cloud\Scripts\python.exe scripts/pilot.py token --role admin --copy
    npm --prefix part-c/frontend run preview -- --port 5173

Abrir http://localhost:5173. Iniciar sesión y pegar el token. El secreto firmante nunca sale de Secrets Manager; el token de acceso sí se entrega al usuario autorizado y vence en 4 h. Es un mecanismo de acceso provisionado para la demostración, no un sistema de registro y login de usuarios para producción.

El seed inserta 24 máquinas, 8 técnicos, 18 filas de inventario y 576 lecturas históricas SIMULADAS. No crea alertas ni incidentes. No sobrescribe catálogos existentes; repetir seed vuelve a cargar el histórico de muestra con marcas de tiempo nuevas. Es para el entorno piloto, no producción.

## 4. Activar el flujo real

En otra terminal:

    .\.venv-cloud\Scripts\python.exe scripts/pilot.py simulate

Una lectura simulada llega por HTTP a AWS, entra a SQS, se valida y se guarda en DynamoDB y S3. Una regla de temperatura + vibración abre una alerta; EventBridge inicia SF1 y SF3 reales. La detección es por reglas: no se presenta como predicción ML.

Actualizar la web tras unos segundos. El incidente se asigna automáticamente a un técnico disponible. En la ficha: confirmar recepción, esperar la actualización del workflow, iniciar, pedir explicación de IA, describir intervención y cerrar con un repuesto. El cierre cambia incidente, inventario, técnico y máquina dentro de una transacción DynamoDB.

Si SF1 queda esperando recepción por más de 5 min, escala y puede reasignar. Para crear una escena nueva usar --machine MCH-000002. Evitar lanzar varias escenas al mismo tiempo durante la grabación. Para un incidente activo de la misma máquina se suprime el inicio de otro flujo.

Si una lectura se reenvía, su clave natural evita duplicar el registro; el indicador de publicación y el nombre de ejecución reducen duplicados. AWS mantiene entrega al menos una vez: no prometer exactly-once de todas las notificaciones.

## 5. Publicar en Cloudflare Pages

Publicar la carpeta part-c/frontend/dist mediante Direct Upload. Copiar el origen HTTPS público y actualizar CORS:

    powershell -ExecutionPolicy Bypass -File .\Desplegar_Piloto.ps1 -CloudflareUrl "https://TU-WORKER.workers.dev" -FrontendOrigin "https://TU-SITIO.pages.dev"

Entrar a la web pública y pegar un token vigente con el botón de acceso. No incluir tokens en la URL ni en la grabación. La clave compartida de IA y las credenciales AWS/B2 no se entregan a la web. Después de cambiar el origen, el acceso desde localhost puede dejar de estar permitido.

## 6. Tercera nube: Backblaze

Crear un bucket B2 privado y una Application Key restringida a ese bucket, con lectura y escritura. Obtener el endpoint S3 de la región. Configurar desde el equipo con acceso al entorno AWS:

    .\.venv-cloud\Scripts\python.exe scripts/pilot.py configure-b2
    .\.venv-cloud\Scripts\python.exe scripts/pilot.py backup
    .\.venv-cloud\Scripts\python.exe scripts/pilot.py backup-status

Los valores sensibles se piden sin eco y se guardan en Secrets Manager. No se escriben al repo. La máquina de estados ExportAndCopy -> RestoreAndCompare copia un export JSON de catálogos e incidentes de S3 a B2 y descarga la copia para verificar su SHA-256. Solo afirmar restauración después de ver SUCCEEDED y restored_verified=true. Se limita a 5 MiB por export del piloto. No se afirma inmutabilidad de B2 ni copia completa de telemetría/Parquet: esas ampliaciones no están en esta versión.

## Límites y limpieza

- Sin BigQuery, Vertex, Gemini ni entrenamiento predictivo en este piloto.
- La analítica utiliza lecturas simuladas persistidas: consumo medio, utilización de muestras y reglas de mantenimiento. No estima costo monetario ni confirma causas comunes.
- Lecturas de catálogo acotadas a 1.000 filas. Usar el dataset pequeño; no presentar el piloto como una prueba de miles de máquinas.
- Los avisos se guardan en la aplicación y se publican en SNS; email/SMS no están configurados por defecto.
- Las pruebas locales no certifican permisos, cuotas ni llamadas reales entre proveedores.
- Mantener planes gratuitos y limitar inferencias. Cerrar la terminal no elimina los recursos. Después de grabar y entregar, exportar evidencia y eliminar conscientemente af-z3-pilot y af-test-data. Algunas tablas de C se retienen; los buckets versionados con objetos requieren vaciado explícito antes de su eliminación. No usar borrado automático si contiene evidencia necesaria.

## Verificación local realizada

Pruebas backend, frontend y Worker; compilación Vite y validación estática cfn-lint. Verificar adicionalmente en las cuentas: API sin token rechazada; token de operador no puede asignar/cerrar; callback de recepción y cierre reanudan SF1; stock descontado una vez; IA de Cloudflare devuelve modelo/fuentes; respaldo B2 restaurado con hash idéntico.
