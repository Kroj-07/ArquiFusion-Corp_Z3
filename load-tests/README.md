# Pruebas con Kiara

Estos scripts no se han ejecutado contra el Lab. La prueba grande consume créditos: empezar con 20 máquinas y usar una sola corrida de hasta 5000 cerca del hito H4, como indica el plan v3.

Instalar boto3 en el entorno de pruebas. Nunca pasar el token o secreto como texto en el comando: usar entrada oculta o `--secret-id` para leer desde Secrets Manager con la sesión local autorizada.

```powershell
python load-tests/replay.py --api https://API_A_REAL --machines 20 --steps 3 --workers 2
```

Por defecto usa Bearer; confirmar con Kiara cómo autentica su ingesta. Si implementó HMAC, usar `--auth hmac-body` (firma del body, como el plan) o `--auth hmac-bound` (timestamp+método+ruta+body), exactamente según su verificador. No elegir a ciegas. Estas opciones no cambian el contrato de Nico.

Las máquinas tienen prefijo `MCH-LOAD-`; Kiara/Nico deben permitir o precargar ese catálogo. Si su ingesta exige máquinas registradas, cargarlo antes. El script no pretende medir ML ni mantenimiento cuando la entrada aún no se acepta.

`replay.json` conserva claves de lecturas aceptadas y latencia HTTP p95. Solo crea un manifest completo si A identifica de manera consistente las lecturas aceptadas/rechazadas. HTTP 202 no prueba que todo el procesamiento terminó.

Para interrumpir únicamente el consumidor:

```powershell
python load-tests/chaos.py --mapping UUID_REAL --queue-url URL_REAL --pause-seconds 20
```

Enviar la corrida pequeña desde otra terminal mientras está deshabilitado. El script restaura el mapping en finally. No borra colas, tablas ni funciones. Si no se puede restaurar por permisos o pérdida de sesión, volver a habilitarlo desde la consola.

Para conciliar IDs después de restaurar, añadir `--manifest evidence/replay.json --telemetry-table NOMBRE_REAL`. La tabla debe tener las claves exactas del v3: machine_id y timestamp. Si A normaliza timestamps, adaptar la comparación antes de interpretar el resultado. El conteo aproximado de SQS por sí solo no prueba pérdida cero.

Esta prueba demuestra recuperación del consumidor; no demuestra tolerancia a una caída regional ni pérdida de cuenta. El respaldo Azure y su restauración los verifica Kiara por separado.
