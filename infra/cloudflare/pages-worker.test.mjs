import { test } from 'node:test';
import assert from 'node:assert/strict';
import worker, { proxyApi, authRequest } from './pages-worker.mjs';

test('public API request without token never reaches AWS', async () => {
  const result = await proxyApi(new Request('https://example.pages.dev/v1/bootstrap'), () => { throw new Error('must not call'); });
  assert.equal(result.status, 401);
});
test('proxy keeps path, token, body and command; does not forward cookies', async () => {
  const request = new Request('https://example.pages.dev/v1/incidents/INC-test/ack?q=1', {
    method: 'POST', headers: { authorization: 'Bearer fixture', 'content-type': 'application/json', 'idempotency-key': 'command-fixture', cookie: 'private=not-forwarded' }, body: '{}',
  });
  const result = await proxyApi(request, async (url, options) => {
    assert.equal(url, 'https://vec07o9pei.execute-api.us-east-1.amazonaws.com/v1/incidents/INC-test/ack?q=1');
    assert.equal(options.headers.get('authorization'), 'Bearer fixture');
    assert.equal(options.headers.get('idempotency-key'), 'command-fixture');
    assert.equal(options.headers.has('cookie'), false);
    assert.equal(new TextDecoder().decode(options.body), '{}');
    assert.equal(options.redirect, 'manual');
    return new Response('{"data":{"accepted":true}}', { status: 200 });
  });
  assert.equal(result.status, 200);
  assert.equal(result.headers.get('cache-control'), 'no-store');
});
test('AWS permission rejection is preserved', async () => {
  const response = await proxyApi(new Request('https://example.pages.dev/v1/bootstrap', { headers: { authorization: 'Bearer fixture' } }), async () => new Response('{"error":{"code":"FORBIDDEN"}}', { status: 403 }));
  assert.equal(response.status, 403);
});
test('AWS outage returns an error without fake records', async () => {
  const response = await proxyApi(new Request('https://example.pages.dev/v1/bootstrap', { headers: { authorization: 'Bearer fixture' } }), async () => { throw new Error('offline'); });
  assert.equal(response.status, 502);
  assert.equal((await response.json()).error.code, 'UPSTREAM_UNAVAILABLE');
});
test('static assets use Pages ASSETS', async () => {
  const response = await worker.fetch(new Request('https://example.pages.dev/'), { ASSETS: { fetch: async () => new Response('app fixture') } });
  assert.equal(await response.text(), 'app fixture');
});
test('login hides refresh token from browser JSON and sets protected cookie', async () => {
  const request = new Request('https://example.pages.dev/v1/auth/login', { method: 'POST', headers: { origin: 'https://example.pages.dev' }, body: '{"username":"ta","password":"fixture"}' });
  const response = await authRequest(request, async () => Response.json({ data: { access_token: 'access-fixture', refresh_token: 'refresh-fixture', refresh_expires_in: 604800 } }));
  const body = await response.json();
  assert.equal(body.data.access_token, 'access-fixture');
  assert.equal(body.data.refresh_token, undefined);
  assert.match(response.headers.get('set-cookie'), /HttpOnly; Secure; SameSite=Strict/);
});
test('refresh forwards only the session cookie token in server body', async () => {
  const request = new Request('https://example.pages.dev/v1/auth/refresh', { method: 'POST', headers: { cookie: 'other=private; __Host-af_refresh=refresh-fixture' } });
  const response = await authRequest(request, async (url, options) => {
    assert.equal(url.endsWith('/v1/auth/refresh'), true);
    assert.deepEqual(JSON.parse(options.body), { refresh_token: 'refresh-fixture' });
    assert.equal(options.headers.cookie, undefined);
    return Response.json({ data: { access_token: 'new-access' } });
  });
  assert.equal((await response.json()).data.access_token, 'new-access');
});
test('cross-origin login is rejected before calling AWS', async () => {
  const request = new Request('https://example.pages.dev/v1/auth/login', { method: 'POST', headers: { origin: 'https://other.example' }, body: '{}' });
  const response = await authRequest(request, () => { throw new Error('must not call'); });
  assert.equal(response.status, 403);
});
test('logout clears the protected session cookie', async () => {
  const response = await authRequest(new Request('https://example.pages.dev/v1/auth/logout', { method: 'POST' }));
  assert.match(response.headers.get('set-cookie'), /Max-Age=0/);
});
