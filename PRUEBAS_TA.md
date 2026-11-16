# Probar ArquiFusion

La URL de Pages, el usuario y la contraseña se entregan en Canvas. Las credenciales no están en este repositorio.

La flota de demostración contiene catálogos e históricos sintéticos. AWS, Google Cloud y Cloudflare ejecutan servicios reales. El caso de alerta enviada desde GCP a AWS quedó identificado como `ALT-B-TEST-002`, máquina `MCH-999001`, incidente `INC-6EC005997EF2`.

## Repetir el ciclo desde la web

1. Iniciar sesión con la cuenta de evaluación. El servidor verifica la contraseña; el rol no se elige desde el navegador.
2. En el centro de control, pulsar **Lectura de prueba**. Elegir una máquina sin incidente activo.
3. Elegir **temperatura y vibración altas** y enviar. Se publica una medición nueva en la cola de AWS. Esta ruta usa un detector por reglas, identificado como tal; no es una predicción de GCP.
4. Esperar unos segundos y actualizar **Incidentes**. Si hay especialista disponible dentro de su turno, puede quedar asignado automáticamente. Si queda abierto, ir a **Asignación de técnicos**, calcular y confirmar reservas.
5. Abrir el incidente. Revisar la evidencia y la explicación con su modelo y fuentes. La explicación puede tardar unos segundos.
6. Pulsar **Confirmar recepción**, esperar a que el workflow habilite la acción y pulsar **Iniciar atención**.
7. En **Intervención y cierre**, registrar una intervención de prueba. Puede cerrarse sin repuestos. Si se usa un repuesto, debe existir stock en la zona del incidente.
8. Pulsar **Cerrar intervención**, actualizar y comprobar el estado **Resuelto**, el historial y la disponibilidad del técnico.

La lectura de prueba renueva ocho horas el turno de los técnicos del catálogo sintético que estén disponibles. No libera técnicos ocupados ni borra incidentes. Al elegir **lectura normal**, no debe abrirse un incidente nuevo.

## Analítica de Google Cloud

Abrir **Analítica operativa**. Los módulos consultan Cloud Run; los fallos parciales se muestran como no disponibles y no se sustituyen por resultados simulados. La prueba del endpoint de predicciones de riesgo y de Gemini devolvió HTTP 200; esto no demuestra precisión ni entrenamiento automático completo.

## Verificación en AWS por el equipo

Kiara puede consultar la ejecución de SF1 correspondiente a una alerta y su historial. Una ejecución en espera de confirmación o cierre debe estar RUNNING; después del cierre completo debe finalizar SUCCEEDED. Si está esperando asignación, no se interpreta como fallo del despliegue.

La prueba manual de GCP a AWS se repite con una alerta firmada usando un identificador y fecha nuevos. Se conserva el mismo secreto alert-hmac. Reenviar una alerta ya publicada puede devolver duplicado y no crear otra ejecución.

## Reproducir la publicación

Instalar las dependencias de `part-c/frontend` con `npm ci`. Desde la raíz ejecutar `python scripts/build_public_web.py`. Subir el ZIP generado en `delivery/` como versión de producción del mismo proyecto Pages.

`scripts/Configurar_Acceso.py` configura la cuenta de evaluación y actualiza la Lambda de API en la cuenta de Kiara; no recrea tablas ni workflows. Requiere el paquete de instalación y una sesión AWS autorizada. No se incluyen contraseñas, tokens ni archivos de sesión en Git.

## Alcance de esta entrega

La web se aloja en Cloudflare Pages; Workers AI aporta las explicaciones. AWS opera el estado y los workflows. GCP aporta consultas y resultados de predicción. Azure no participa en esta versión. Backblaze, restauración de respaldos, alta disponibilidad entre regiones, pruebas de 5.000 máquinas y el pipeline automático completo de entrenamiento no tienen una verificación final en esta entrega.
