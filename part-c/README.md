# ArquiFusion · Parte C (app, asignación, SF-1 y SF-3)

Esta carpeta es la Parte C (Guillermo): app web, asignación de técnicos, callbacks, SF-1 y SF-3. La Parte A (AWS) es de Kiara y la Parte B (Google Cloud) es de Nico. La web final se publica en Cloudflare Pages (ver `infra/pilot/GUIA.md`); el despliegue en Azure que aparece en `frontend/DEPLOY_AZURE.md` es de un plan anterior y ya no lo usamos.

## Abrir en Windows

Desde la raíz del repositorio (los comandos de abajo asumen esa carpeta). Requisitos: Python 3.12 y Node.js 20.19 o superior.

En PowerShell, desde esta carpeta:

```powershell
powershell -ExecutionPolicy Bypass -File .\Iniciar_Demo.ps1
```

Abre `http://127.0.0.1:5173`. La otra ventana ejecuta el backend local. Ctrl+C detiene la app. El script no requiere credenciales cloud y no despliega recursos. Si los puertos 8000/5173 están ocupados, detener la ejecución anterior.

Alternativa, dos terminales:

```powershell
# Terminal 1: desde la raíz del repo
py -3.12 -m venv .venv
cd part-c\backend
..\..\.venv\Scripts\python.exe -m afc.local
```

```powershell
# Terminal 2: desde la raíz del repo
cd part-c\frontend
npm.cmd ci
npm.cmd run dev
```

SQLite conserva cambios en `part-c/backend/.local/demo.sqlite`. Para reiniciar la demo, cerrar el backend y usar otra ruta `--database` o eliminar únicamente ese archivo y sus archivos `-wal`/`-shm`.

## Recorrido de prueba

1. Control: mapa, estados e incidentes prioritarios.
2. Asignación: calcular propuesta y confirmar reservas.
3. Incidentes: abrir INC-000001 → confirmar recepción → iniciar atención.
4. Intervención y cierre: describir el trabajo, registrar repuestos y confirmar si volvió a operar.
5. Revisar inventario y la línea de tiempo. No se duplica el descuento al repetir el mismo comando.
6. Cambiar el rol de demostración: operador ve su máquina; técnico sus intervenciones; gerencia consulta sin editar.

La demo usa datos simulados. Sus vistas analíticas y explicaciones no son resultados de BigQuery ML/Gemini. En modo conectado no se usa información ficticia cuando falla una API.

## Qué está listo

- Seis vistas adaptables a escritorio y móvil; mapa Leaflet, detalle de máquina, gráficos, filtros, historial y avisos por rol.
- Asignación global con SciPy si está disponible; algoritmo Hungarian incluido como alternativa exacta sin dependencias. Comparación con heurística voraz.
- Reservas con versiones y transacción; cierre con inventario, liberación del técnico y recurrencia. Tiempo de resolución separado del downtime observado.
- SF-1 Standard con callbacks privados de asignación, recepción y cierre, reintentos, escalamiento y cola de errores. SF-3 Express con seis ramas por rol.
- API JWT para producción; acceso Cognito mediante PKCE. El selector de rol solo existe en demo.
- Plantillas SAM y conector para las tablas de A; scripts de carga y recuperación.

## Integrar y desplegar

1. Leer [CONEXION_KIARA_NICO.md](../contract/CONEXION_KIARA_NICO.md): ahí quedaron los acuerdos entre las tres partes.
2. Kiara despliega el conector de A y pasa su ARN. Ninguna clave de AWS va al navegador.
3. Nico da la base HTTPS de B; con él acordamos los ejemplos de respuesta y la firma C→B.
4. Desplegar [C en AWS](../infra/part-c/DEPLOY.md), configurar modo live y publicar el frontend en Cloudflare Pages siguiendo [infra/pilot/GUIA.md](../infra/pilot/GUIA.md).
5. Probar el recorrido real con la guía de [PRUEBAS_TA.md](../PRUEBAS_TA.md).

El adaptador de referencia lee catálogos con Scan acotado a 1000 filas por tabla. Es para integrar el piloto; **no demuestra escala a miles**. Se puede cambiar el lector por consultas indexadas sin tocar las transacciones ni el contrato. Los scripts de carga y caos no se ejecutaron a escala completa (ver `load-tests/README.md`).

## Comprobaciones

```powershell
cd part-c\backend
..\..\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
..\..\.venv\Scripts\python.exe -m unittest discover -v
```

```powershell
cd part-c\frontend
npm.cmd test
npm.cmd run build
```

Validar una plantilla no prueba los permisos reales del Learner Lab: eso solo se ve al desplegar.

## Entrega

`delivery/guion_4m30.md` y arquitectura editable son material de trabajo interno. El video final necesita las demostraciones reales de A/B/C. Actualizar la arquitectura con los recursos efectivamente desplegados. Canvas: video menor de cinco minutos, repositorio y PNG. No adjuntar un informe ni el PDF de planificación.
