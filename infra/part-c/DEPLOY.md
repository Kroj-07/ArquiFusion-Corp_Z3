# Desplegar C en AWS

1. Trabajar en la misma cuenta y región de Kiara, preferentemente us-east-1 según el acuerdo del equipo. No compartir credenciales personales por chat. Lambda usa su rol, no claves estáticas.
2. Kiara despliega el adaptador con `a-adapter-template.yaml` o integra ese contrato en su módulo A. Los nombres de tablas se pasan como parámetros. Obtener AdapterArn.
3. Verificar roles existentes del Lab. LambdaRoleArn: trust lambda.amazonaws.com. StatesRoleArn: trust states.amazonaws.com. Pueden coincidir solo si el rol permite ambos. El nombre LabRole no demuestra esos permisos. No se crean roles IAM nuevos en estas plantillas.
4. Tener bus `arquifusion-events`, Cognito configurado y origen HTTPS de Azure. El cliente Cognito no tiene client secret; callback y logout URLs incluyen exactamente el origen publicado, sin rutas adicionales.

Desde la raíz, con AWS SAM CLI y sesión Academy vigente:

```powershell
python infra/part-c/build_workflows.py
cd infra/part-c
sam validate --lint
sam build --template-file template.yaml
sam deploy --guided --stack-name af-z3-part-c --region us-east-1
```

Parámetros: LambdaRoleArn, StatesRoleArn, AAdapterArn, JwtIssuer, JwtAudience, FrontendOrigin; opcionales BApiBase y BAuthSecretArn. Usar los valores reales. No poner una URL ficticia en modo live y afirmar que está conectado.

## Permisos efectivos

- Lambda C: logs; InvokeFunction del adaptador A; Get/Put/Query de Coordination y su índice; GetSecretValue del secreto C→B; SendTaskSuccess de Step Functions; StartExecution SF1/SF3 para Receiver; Publish del tópico; SendMessage de Errors como destino de fallos asíncronos.
- Step Functions: InvokeFunction de WorkflowFunction; PutItem en Coordination; SendMessage en Errors; Publish en Topic; PutEvents en el bus; permisos de entrega de CloudWatch Logs.
- Adaptador A: Scan/Query/GetItem de tablas del piloto y TransactWriteItems/PutItem sobre máquinas, incidentes, técnicos, inventario y su tabla de comandos. Antes de escala, cambiar su lector acotado por consultas indexadas.

Los permisos amplios de LabRole, si se utiliza, son una restricción del entorno. No presentarlo como una política de mínimo privilegio diseñada por el equipo.

## Verificar

- Sin JWT válido, C debe rechazar la solicitud. `x-demo-role` no concede permisos en cloud.
- Publicar una alerta de prueba desde A y observar Receiver, una ejecución Standard y el fan-out Express.
- Confirmar técnico desde la app. Mostrar la espera de recepción y el callback de cierre.
- Avisos de aplicación se guardan por alert_id/rol/alcance; SNS puede entregar duplicados. Suscribirse y confirmar el correo antes de afirmar entrega por email. Los avisos de agrupación hourly se conservan en el inbox; el envío de digest por reloj no está implementado en C.
- En el cierre, una transacción actualiza incidente, inventario, técnico y máquina. El Map posterior **solo envía avisos de stock bajo**. No debe volver a descontar piezas.
- Si un workflow falla, revisar Errors y su ejecución; redrive es manual. Timeouts globales, mensajes pendientes o fallos de QueueFailure también requieren revisión de logs. Añadir alarmas de DLQ/ejecuciones fallidas antes de grabar la entrega final.

SF-1 espera hasta 5 min por recepción; reintenta con otro técnico hasta tres veces y luego pide asignación manual. Espera de asignación: 1 h; de cierre: 24 h; límite global: 48 h. Caducidad no equivale a incidente resuelto. Los tokens no se entregan al frontend ni se incluyen en logs de ejecución.

Las plantillas fueron validadas estáticamente; el despliegue, acceso a servicios, cuotas y trust del Lab se prueban en la cuenta real. No se ha ejecutado ese despliegue desde este paquete.
