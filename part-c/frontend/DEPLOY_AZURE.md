# Azure Static Web Apps

La app es estática; los datos y callbacks van a la API C en AWS. Azure no recibe claves Academy, HMAC ni SAS en el navegador.

1. Crear Static Web App en el portal Azure, plan Free si está disponible en su suscripción. Elegir repositorio y rama del equipo. No crear App Service con servidor dedicado.
2. App location: `part-c/frontend`; API location: vacía; output location: `dist`. Si el repo tiene otra carpeta raíz, ajustar App location.
3. Antes del build, añadir al entorno de compilación de GitHub Actions las variables públicas:

```text
VITE_DATA_MODE=live
VITE_API_BASE=https://API_C_REAL.execute-api.us-east-1.amazonaws.com
VITE_COGNITO_DOMAIN=https://DOMINIO_REAL.auth.us-east-1.amazoncognito.com
VITE_COGNITO_CLIENT_ID=CLIENT_ID_PUBLICO
```

Son valores públicos; los secretos nunca usan prefijo VITE_. Con Vite las variables se resuelven **durante build**. Cambiar una setting del hosting sin reconstruir no cambia el bundle. Incluirlas en el paso `Azure/static-web-apps-deploy` como `env`, desde variables públicas del repositorio o valores de configuración del workflow.

4. Registrar en Cognito el origen HTTPS final de Azure como callback y logout URL. Configurar autorización code grant, PKCE S256 y scopes openid/profile/email. El cliente no tiene client secret. C usa el ID token y API Gateway valida issuer/audience; revisar `contract/CONEXION_KIARA_NICO.md` para grupos y alcance.
5. En la plantilla AWS, FrontendOrigin debe coincidir con el origen de Azure, sin `/` final. Esto configura CORS para Authorization, Content-Type e Idempotency-Key.
6. Compilar `npm ci && npm run build`. `staticwebapp.config.json` ya se copia a dist y permite rutas SPA. Publicar con el workflow generado por Azure o usar la CLI SWA con el token de despliegue introducido de forma segura. No guardar ese token en el repo.

Verificar login, lectura, una reserva y ambos callbacks desde la URL publicada. Si falta la API, la app no debe mostrar datos de demo. `VITE_DATA_MODE=demo` en un hosting estático no incluye un backend local: no sirve como sustituto del despliegue live.

El mapa usa tiles públicos de OpenStreetMap con atribución. Si no hay acceso a tiles, siguen los marcadores georreferenciados y el fondo de respaldo. Para tráfico real, elegir un proveedor de tiles compatible con su volumen y condiciones de uso; esta demo no afirma capacidad ilimitada del servicio público.
