"""Compila la web publica con acceso por cuenta y proxy Pages, sin incluir secretos."""
import json
import os
from pathlib import Path
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
frontend = ROOT / 'part-c/frontend'
environment = {**os.environ, 'VITE_DATA_MODE': 'live', 'VITE_API_BASE': '', 'VITE_AUTH_MODE': 'password'}
subprocess.run(['npm.cmd' if os.name == 'nt' else 'npm', 'run', 'build'], cwd=frontend, env=environment, check=True)
dist = frontend / 'dist'
worker = (ROOT / 'infra/cloudflare/pages-worker.mjs').read_text()
worker = worker.replace('export async function proxyApi', 'async function proxyApi').replace('export async function authRequest', 'async function authRequest')
(dist / '_worker.js').write_text(worker)
(dist / '_routes.json').write_text(json.dumps({'version': 1, 'include': ['/v1/*'], 'exclude': []}))
(dist / 'staticwebapp.config.json').unlink(missing_ok=True)
output = ROOT / 'delivery/ArquiFusion_Web_Login.zip'
output.parent.mkdir(exist_ok=True)
with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
    for path in sorted(dist.rglob('*')):
        if path.is_file():
            archive.write(path, path.relative_to(dist))
print('Subir como nueva version de produccion en Pages: ' + str(output))
