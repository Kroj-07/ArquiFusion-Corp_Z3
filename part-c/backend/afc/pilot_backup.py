"""Respaldo privado AWS -> Backblaze B2 con verificación de restauración por SHA-256."""
import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone

import boto3
from botocore.config import Config
from .a_adapter import catalog
from .domain import check
from .pilot import secret


def b2_client():
    settings = json.loads(boto3.client('secretsmanager').get_secret_value(SecretId=os.environ['B2_SECRET_ARN'])['SecretString'])
    check(all(settings.get(k) for k in ('endpoint','bucket','key_id','application_key')), 'Configura primero el secreto de Backblaze B2')
    check(bool(re.fullmatch(r'https://s3\.[a-z0-9-]+\.backblazeb2\.com', settings['endpoint'])), 'Endpoint B2 inválido')
    client = boto3.client('s3', endpoint_url=settings['endpoint'], region_name=settings['endpoint'].split('.')[1],
        aws_access_key_id=settings['key_id'], aws_secret_access_key=settings['application_key'],
        config=Config(signature_version='s3v4', connect_timeout=5, read_timeout=15, retries={'max_attempts':2}))
    return client, settings['bucket']


def handler(event, context):
    client, bucket = b2_client()
    if event.get('action') == 'restore':
        response = client.get_object(Bucket=bucket, Key=event['key'])
        body = response['Body'].read(5*1024*1024+1)
        actual = hashlib.sha256(body).hexdigest()
        check(actual==event['sha256'], 'La copia restaurada no coincide con el origen')
        return {**event, 'restored_verified':True, 'bytes':len(body), 'provider':'backblaze-b2'}
    snapshot = {kind:catalog(kind) for kind in ('machines','incidents','technicians','inventory','alerts')}
    # Nunca se exportan JWT, claves, comandos ni tokens privados de Step Functions.
    body = json.dumps({'schema_version':'pilot-1', 'exported_at':datetime.now(timezone.utc).isoformat(), 'data':snapshot}, ensure_ascii=False).encode()
    check(len(body)<=5*1024*1024, 'Respaldo piloto limitado a 5 MiB')
    digest = hashlib.sha256(body).hexdigest()
    key = 'arquifusion/'+datetime.now(timezone.utc).strftime('%Y-%m-%d')+'/'+uuid.uuid4().hex+'.json'
    boto3.client('s3').put_object(Bucket=os.environ['DATA_BUCKET'], Key='exports/'+key, Body=body, ContentType='application/json', Metadata={'sha256':digest})
    client.put_object(Bucket=bucket, Key=key, Body=body, ContentType='application/json', Metadata={'sha256':digest})
    return {'action':'restore', 'bucket':bucket, 'key':key, 'sha256':digest, 'bytes':len(body)}
