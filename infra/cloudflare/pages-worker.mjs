const AWS_API = 'https://vec07o9pei.execute-api.us-east-1.amazonaws.com';
const json = (data, status) => new Response(JSON.stringify(data), {
  status,
  headers: { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' },
});
const refreshCookie = (token, maxAge) => `__Host-af_refresh=${token}; HttpOnly; Secure; SameSite=Strict; Path=/; Max-Age=${maxAge}`;

export async function authRequest(request, upstreamFetch = fetch) {
  const url = new URL(request.url);
  if (request.method !== 'POST') return json({ error: { message: 'Metodo no disponible.' } }, 405);
  const origin = request.headers.get('origin');
  if (origin && origin !== url.origin) return json({ error: { message: 'Origen no autorizado.' } }, 403);
  if (url.pathname === '/v1/auth/logout') {
    const response = json({ data: { logged_out: true } }, 200);
    response.headers.set('set-cookie', refreshCookie('', 0));
    return response;
  }
  let body;
  if (url.pathname === '/v1/auth/refresh') {
    const token = (request.headers.get('cookie') || '').split(';').map(v => v.trim()).find(v => v.startsWith('__Host-af_refresh='))?.slice('__Host-af_refresh='.length);
    if (!token || token.length > 8192) return json({ error: { message: 'Inicia sesion.' } }, 401);
    body = JSON.stringify({ refresh_token: token });
  } else if (url.pathname === '/v1/auth/login') {
    const raw = await request.arrayBuffer();
    if (raw.byteLength > 16384) return json({ error: { message: 'Solicitud demasiado grande.' } }, 413);
    body = raw;
  } else return json({ error: { message: 'Ruta no disponible.' } }, 404);
  try {
    const upstream = await upstreamFetch(AWS_API + url.pathname, { method: 'POST', headers: { 'content-type': 'application/json' }, body, redirect: 'manual', signal: AbortSignal.timeout(30000) });
    const payload = await upstream.json();
    const refresh = payload.data?.refresh_token;
    const ttl = payload.data?.refresh_expires_in;
    if (payload.data) { delete payload.data.refresh_token; delete payload.data.refresh_expires_in; }
    const response = json(payload, upstream.status);
    if (upstream.ok && refresh) response.headers.set('set-cookie', refreshCookie(refresh, Math.min(ttl || 604800, 604800)));
    if (upstream.status === 401 && url.pathname.endsWith('/refresh')) response.headers.set('set-cookie', refreshCookie('', 0));
    return response;
  } catch {
    return json({ error: { message: 'No se pudo contactar al servicio de acceso en AWS.' } }, 502);
  }
}

export async function proxyApi(request, upstreamFetch = fetch) {
  const url = new URL(request.url);
  if (!['GET', 'POST'].includes(request.method)) {
    return json({ error: { code: 'METHOD_NOT_ALLOWED', message: 'Metodo no disponible.' } }, 405);
  }
  const authorization = request.headers.get('authorization') || '';
  if (!authorization.startsWith('Bearer ')) {
    return json({ error: { code: 'UNAUTHORIZED', message: 'Inicia sesion con tu token temporal.' } }, 401);
  }
  const headers = new Headers();
  for (const name of ['authorization', 'content-type', 'idempotency-key', 'accept']) {
    if (request.headers.has(name)) headers.set(name, request.headers.get(name));
  }
  if (Number(request.headers.get('content-length') || 0) > 262144) {
    return json({ error: { code: 'PAYLOAD_TOO_LARGE', message: 'Solicitud demasiado grande.' } }, 413);
  }
  const body = request.method === 'POST' ? await request.arrayBuffer() : undefined;
  if (body && body.byteLength > 262144) {
    return json({ error: { code: 'PAYLOAD_TOO_LARGE', message: 'Solicitud demasiado grande.' } }, 413);
  }
  try {
    // Destino fijo. La identidad y las operaciones se validan en AWS.
    const response = await upstreamFetch(AWS_API + url.pathname + url.search, {
      method: request.method, headers, body, redirect: 'manual', signal: AbortSignal.timeout(35000),
    });
    const outgoing = new Headers(response.headers);
    outgoing.set('cache-control', 'no-store');
    outgoing.set('x-arquifusion-proxy', 'cloudflare-pages');
    return new Response(response.body, { status: response.status, headers: outgoing });
  } catch {
    return json({ error: { code: 'UPSTREAM_UNAVAILABLE', message: 'AWS no respondio. No se usaron datos de demostracion.' } }, 502);
  }
}

export default {
  async fetch(request, env) {
    if (new URL(request.url).pathname.startsWith('/v1/auth/')) return authRequest(request);
    if (new URL(request.url).pathname.startsWith('/v1/')) return proxyApi(request);
    return env.ASSETS.fetch(request);
  },
};
