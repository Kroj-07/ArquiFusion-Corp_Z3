"""Desde el repo, en CloudShell de Kiara: python3 ~/af-login/Configurar_Acceso.py."""
import argparse
import getpass
import json
import io
import os
from pathlib import Path
import re
import shutil
import sys
import time
import urllib.error
import urllib.request
import zipfile
import boto3


def private_write(path, data):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'wb') as handle:
        handle.write(data)
    path.chmod(0o600)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--user', default='ta')
    args = parser.parse_args()
    username = args.user.strip().lower()
    if not re.fullmatch(r'[a-z0-9_.-]{2,64}', username):
        raise RuntimeError('Usuario: 2 a 64 letras, numeros, punto, guion o guion bajo.')
    session = boto3.Session(region_name='us-east-1')
    if session.client('sts').get_caller_identity()['Account'] != '057730774138':
        raise RuntimeError('Cuenta requerida: 057730774138. No se modifico nada.')
    repo = Path.cwd()
    if not (repo / 'scripts/pilot.py').is_file():
        raise RuntimeError('Primero entra en la raiz del repositorio.')
    package = Path(__file__).resolve().parent
    source_root = package / 'source'
    if not source_root.is_dir(): source_root = repo
    sys.path.insert(0, str(source_root / 'part-c/backend'))
    from afc.password_auth import password_record
    password = getpass.getpass('Elige contrasena de evaluacion (minimo 12 caracteres): ')
    confirmation = getpass.getpass('Repite la contrasena: ')
    if password != confirmation:
        raise RuntimeError('Las contrasenas no coinciden. No se modifico nada.')
    record = password_record(password, 'admin')
    cf = session.client('cloudformation')
    stack = cf.describe_stacks(StackName='af-z3-c')['Stacks'][0]
    if stack['StackStatus'] not in ('CREATE_COMPLETE', 'UPDATE_COMPLETE'):
        raise RuntimeError('El stack C aun no esta listo.')
    outputs = {r['OutputKey']: r['OutputValue'] for r in stack['Outputs']}
    resources = cf.list_stack_resources(StackName='af-z3-c')['StackResourceSummaries']
    function = next(r['PhysicalResourceId'] for r in resources if r['LogicalResourceId'] == 'ApiFunction')
    lamb = session.client('lambda')
    secrets = session.client('secretsmanager')
    previous = secrets.get_secret_value(SecretId=outputs['JwtSecretArn'])['SecretString']
    settings = json.loads(previous)
    if not settings.get('jwt_secret'):
        raise RuntimeError('Falta la clave de firma existente. No se modifico nada.')
    backup = Path.home() / '.arquifusion-recovery' / ('login-' + str(int(time.time())))
    backup.mkdir(parents=True, mode=0o700)
    metadata = lamb.get_function(FunctionName=function)
    with urllib.request.urlopen(metadata['Code']['Location'], timeout=60) as response:
        private_write(backup / 'api-anterior.zip', response.read())
    private_write(backup / 'secreto-anterior.json', previous.encode())
    settings.setdefault('demo_users', {})[username] = record
    secrets.put_secret_value(SecretId=outputs['JwtSecretArn'], SecretString=json.dumps(settings))
    if (package / 'backend.zip').is_file():
        code = (package / 'backend.zip').read_bytes()
    else:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
            for path in sorted((repo / 'part-c/backend/afc').glob('*.py')):
                archive.write(path, Path('afc') / path.name)
        code = buffer.getvalue()
    lamb.update_function_code(FunctionName=function, ZipFile=code)
    lamb.get_waiter('function_updated_v2').wait(FunctionName=function, WaiterConfig={'Delay': 2, 'MaxAttempts': 40})
    # Mantiene el repo consistente con la version desplegada y conserva cada archivo anterior.
    for source in ((package / 'source').rglob('*') if (package / 'source').is_dir() else []):
        if not source.is_file() or '__pycache__' in source.parts:
            continue
        relative = source.relative_to(package / 'source')
        destination = repo / relative
        if destination.exists():
            saved = backup / 'repo' / relative
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(destination, saved)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if str(relative) == 'README.md' and destination.exists():
            intro = source.read_text().split('\n\n', 1)[0] + '\n\n'
            text = destination.read_text()
            if not text.startswith(intro): destination.write_text(intro + text)
        elif str(relative) == '.gitignore' and destination.exists():
            text = destination.read_text()
            additions = [line for line in source.read_text().splitlines() if line and line not in text.splitlines()]
            destination.write_text(text.rstrip() + '\n' + '\n'.join(additions) + '\n')
        else:
            shutil.copy2(source, destination)

    def post(path, body):
        request = urllib.request.Request(outputs['ApiBase'] + path, method='POST', data=json.dumps(body).encode(), headers={'content-type': 'application/json'})
        with urllib.request.urlopen(request, timeout=35) as response:
            return response.status, json.load(response)['data']

    try:
        post('/v1/auth/login', {'username': username, 'password': 'invalid'})
        raise RuntimeError('La contrasena invalida fue aceptada. Revisar antes de compartir el acceso.')
    except urllib.error.HTTPError as exc:
        if exc.code != 401:
            raise
    status, result = post('/v1/auth/login', {'username': username, 'password': password})
    renewed_status, renewed = post('/v1/auth/refresh', {'refresh_token': result['refresh_token']})
    request = urllib.request.Request(outputs['ApiBase'] + '/v1/bootstrap', headers={'Authorization': 'Bearer ' + renewed['access_token']})
    with urllib.request.urlopen(request, timeout=35) as response:
        bootstrap_status = response.status
        machines = len(json.load(response)['data']['machines'])
    del password, confirmation, previous, settings, result, renewed
    print(json.dumps({'username': username, 'role': 'admin', 'invalid_password_http': 401,
                      'login_http': status, 'renewal_http': renewed_status, 'bootstrap_http': bootstrap_status,
                      'machines': machines, 'access_minutes': 60, 'renewal_days': 7,
                      'backup_path': str(backup),
                      'next': 'Publicar ArquiFusion_Web_Login.zip como nueva version del MISMO proyecto Pages. Entregar usuario y contrasena a los TAs por Canvas, no en GitHub.'}, indent=2))


if __name__ == '__main__':
    main()
