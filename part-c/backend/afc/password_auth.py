"""Cuentas de evaluacion. Contrasenas derivadas en Secrets Manager; sesion firmada en AWS."""
import base64
import hashlib
import hmac
import json
import secrets
import time
from .domain import Problem, ROLES

ITERATIONS = 210000
ACCESS_TTL = 3600
REFRESH_TTL = 7 * 86400


def password_record(password, role='admin'):
    if not isinstance(password, str) or not 12 <= len(password) <= 256:
        raise ValueError('La contrasena debe tener de 12 a 256 caracteres.')
    if role not in ROLES:
        raise ValueError('Rol no valido.')
    salt = secrets.token_hex(24)
    return {'salt': salt, 'hash': hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), ITERATIONS).hex(),
            'iterations': ITERATIONS, 'role': role, 'active': True,
            'zone_ids': ['ZONA-NORTE-02', 'ZONA-CENTRO-01', 'ZONA-SUR-03', 'ZONA-SUR-01'],
            'machine_ids': ['MCH-999001', 'MCH-000001'], 'technician_id': ''}


def _b64(value):
    return base64.urlsafe_b64encode(value).decode().rstrip('=')


def _sign(claims, key):
    value = _b64(b'{"alg":"HS256","typ":"JWT"}') + '.' + _b64(json.dumps(claims, separators=(',', ':')).encode())
    return value + '.' + _b64(hmac.new(key.encode(), value.encode(), hashlib.sha256).digest())


def _identity(username, user, stamp):
    return {'iss': 'arquifusion-pilot', 'aud': 'arquifusion-web', 'sub': username, 'role': user['role'],
            'name': username, 'iat': stamp, 'exp': stamp + ACCESS_TTL,
            'custom:zone_ids': ','.join(user.get('zone_ids', [])),
            'custom:machine_ids': ','.join(user.get('machine_ids', [])),
            'custom:technician_id': user.get('technician_id', '')}


def _session(username, user, settings, stamp, include_refresh):
    result = {'access_token': _sign(_identity(username, user, stamp), settings['jwt_secret']),
              'expires_in': ACCESS_TTL, 'user': {'username': username, 'role': user['role']}}
    if include_refresh:
        claims = {'iss': 'arquifusion-pilot', 'aud': 'arquifusion-refresh', 'purpose': 'refresh', 'sub': username,
                  'iat': stamp, 'exp': stamp + REFRESH_TTL, 'credential_id': hashlib.sha256(user['hash'].encode()).hexdigest(), 'jti': secrets.token_hex(16)}
        result.update(refresh_token=_sign(claims, settings['jwt_secret']), refresh_expires_in=REFRESH_TTL)
    return result


def login(body, settings, current=None):
    stamp = int(time.time() if current is None else current)
    users = settings.get('demo_users', {})
    if not users:
        raise Problem('Las cuentas de acceso aun no estan configuradas.', 'SERVICE_NOT_CONFIGURED', 503)
    username = body.get('username', '') if isinstance(body, dict) else ''
    password = body.get('password', '') if isinstance(body, dict) else ''
    if not isinstance(username, str) or not isinstance(password, str) or len(username) > 64 or len(password) > 256:
        raise Problem('Usuario o contrasena incorrectos.', 'UNAUTHORIZED', 401)
    username = username.strip().lower()
    user = users.get(username) or {}
    derived = hashlib.pbkdf2_hmac('sha256', password.encode(), user.get('salt', 'unknown-user').encode(), ITERATIONS).hex()
    valid = hmac.compare_digest(derived, user.get('hash', '0' * 64))
    if not valid or not user.get('active') or user.get('role') not in ROLES:
        raise Problem('Usuario o contrasena incorrectos.', 'UNAUTHORIZED', 401)
    return _session(username, user, settings, stamp, True)


def refresh(body, settings, current=None):
    stamp = int(time.time() if current is None else current)
    try:
        encoded = body['refresh_token']
        if not isinstance(encoded, str) or len(encoded) > 8192:
            raise ValueError('token')
        head, payload, signature = encoded.split('.')
        decode = lambda value: base64.urlsafe_b64decode(value + '=' * (-len(value) % 4))
        expected = hmac.new(settings['jwt_secret'].encode(), (head + '.' + payload).encode(), hashlib.sha256).digest()
        if json.loads(decode(head)).get('alg') != 'HS256' or not hmac.compare_digest(expected, decode(signature)):
            raise ValueError('signature')
        claims = json.loads(decode(payload))
        if claims.get('iss') != 'arquifusion-pilot' or claims.get('aud') != 'arquifusion-refresh' or claims.get('purpose') != 'refresh':
            raise ValueError('purpose')
        if type(claims.get('exp')) is not int or not stamp < claims['exp'] <= stamp + REFRESH_TTL:
            raise ValueError('expired')
        username = claims['sub']
        user = settings.get('demo_users', {}).get(username, {})
        if not user.get('active') or user.get('role') not in ROLES or not hmac.compare_digest(hashlib.sha256(user.get('hash', '').encode()).hexdigest(), claims.get('credential_id', '')):
            raise ValueError('user')
    except (ValueError, KeyError, TypeError, AttributeError, UnicodeError):
        raise Problem('La sesion termino. Inicia sesion de nuevo.', 'UNAUTHORIZED', 401)
    return _session(username, user, settings, stamp, False)
