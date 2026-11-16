"""Herramientas del piloto. Credenciales AWS por perfil/sesión; nunca dentro del repo."""
import argparse
import base64
import getpass
import hashlib
import hmac
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import boto3

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'part-c/backend'))
from afc.seed import seed
from afc.domain import ROLES


def outputs(session, stack):
    data=session.client('cloudformation').describe_stacks(StackName=stack)['Stacks'][0]
    if data['StackStatus'] not in ('CREATE_COMPLETE','UPDATE_COMPLETE'):
        raise RuntimeError('Stack aún no listo: '+data['StackStatus'])
    return {i['OutputKey']:i['OutputValue'] for i in data['Outputs']}


def secret(session, arn):
    return json.loads(session.client('secretsmanager').get_secret_value(SecretId=arn)['SecretString'])


def token(session, settings, role, part_a=False):
    claims={'iss':'arquifusion-pilot','aud':'arquifusion-web','sub':'pilot-'+role,'role':role,'name':'Piloto Z3 · '+role,
            'iat':int(time.time()),'exp':int(time.time())+14400,
            'custom:zone_ids':'ZONA-NORTE-02,ZONA-CENTRO-01,ZONA-SUR-03','custom:machine_ids':'MCH-000001',
            'custom:technician_id':'TEC-0001' if role=='technician' else ''}
    encode=lambda value:base64.urlsafe_b64encode(value).decode().rstrip('=')
    header=encode(b'{"alg":"HS256","typ":"JWT"}')
    payload=encode(json.dumps(claims,separators=(',',':')).encode())
    body=header+'.'+payload
    if part_a:key=session.client('secretsmanager').get_secret_value(SecretId='arquifusion/test/jwt-signing')['SecretString']
    else:key=secret(session, settings['JwtSecretArn'])['jwt_secret']
    signature=hmac.new(key.encode(),body.encode(),hashlib.sha256).digest()
    return body+'.'+encode(signature)


def copy(text):
    if os.name!='nt': raise RuntimeError('La copia al portapapeles requiere Windows')
    subprocess.run(['clip.exe'],input=text.encode('utf-16le'),check=True)


def api(session, settings, path, body=None):
    headers={'Authorization':'Bearer '+token(session,settings,'admin'),'content-type':'application/json','Idempotency-Key':str(uuid.uuid4())}
    request=urllib.request.Request(settings['ApiBase']+path,headers=headers,data=json.dumps(body).encode() if body is not None else None)
    with urllib.request.urlopen(request,timeout=30) as response:return json.load(response)


def seed_tables(session, settings):
    snapshot=seed();db=session.resource('dynamodb');ssm=session.client('ssm')
    def table(kind):return db.Table(ssm.get_parameter(Name='/arquifusion/test/data/'+kind+'-table')['Parameter']['Value'])
    for machine in snapshot['machines']:
        machine.update(status='operating',risk_score=0,downtime_started_at=None)
    for technician in snapshot['technicians']:
        technician.update(availability='available',active_incident_id=None)
    # Solo catálogos e históricos. Los incidentes y alertas los debe crear el flujo real.
    for kind in ('machines','technicians','inventory'):
        target=table(kind)
        for item in snapshot[kind]:
            key={'machine_id':item['machine_id']} if kind=='machines' else {'technician_id':item['technician_id']} if kind=='technicians' else {'zone_id':item['zone_id'],'part_id':item['part_id']}
            if target.get_item(Key=key).get('Item'):continue
            target.put_item(Item=json.loads(json.dumps(item),parse_float=Decimal))
    target=table('telemetry')
    for machine in snapshot['telemetry']:
        with target.batch_writer() as batch:
            for reading in machine['readings']:
                item={'machine_id':machine['machine_id'],**reading,'status':'operating','simulated':True,'ttl':int(time.time())+2592000}
                batch.put_item(Item=json.loads(json.dumps(item),parse_float=Decimal))
    print('Catálogos y 576 lecturas simuladas guardados en DynamoDB. No se precargaron incidentes ni alertas.')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('command',choices=['status','seed','token','cloudflare-key','gcp-key','simulate','frontend','configure-b2','backup','backup-status','smoke'])
    parser.add_argument('--stack',default='af-z3-pilot');parser.add_argument('--region',default='us-east-1');parser.add_argument('--role',choices=ROLES,default='admin')
    parser.add_argument('--copy',action='store_true');parser.add_argument('--execution');parser.add_argument('--machine',default='MCH-000001')
    parser.add_argument('--via',choices=['pilot','part-a'],default='pilot')
    args=parser.parse_args();session=boto3.Session(region_name=args.region);settings=outputs(session,args.stack)
    if args.command=='status':print(json.dumps(settings,indent=2))
    elif args.command=='seed':seed_tables(session,settings)
    elif args.command=='token':
        value=token(session,settings,args.role)
        if args.copy:copy(value);print('Token temporal de '+args.role+' copiado. Vence en cuatro horas. Pégalo únicamente en la aplicación.')
        else:print('Usa --copy para copiar el token sin mostrarlo en la terminal.')
    elif args.command in ('cloudflare-key','gcp-key'):
        if not args.copy:raise RuntimeError('Usa --copy para evitar mostrar la clave en la terminal')
        name='CloudflareSecretArn' if args.command=='cloudflare-key' else 'GcpAuthSecretArn'
        copy(secret(session,settings[name])['shared_key'])
        print('Clave copiada. Destino: '+('Cloudflare Secret SHARED_KEY' if args.command=='cloudflare-key' else 'GCP B_API_AUTH_SECRET de Cloud Run')+'. No pegar en chats.')
    elif args.command=='simulate':
        body={'schema_version':'1.0','machine_id':args.machine,'timestamp':datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z'),
              'status':'operating','metrics':{'engine_temp_c':112.0,'vibration_mm_s':6.8,'pressure_bar':6.0,'fuel_rate_lph':38.0,'load_kg':12000,'speed_kmh':8,'engine_rpm':1800,'operating_hours_total':3400}}
        if args.via=='part-a':
            url=settings.get('PartAIngestUrl')
            if not url:raise RuntimeError('Este stack no esta conectado a la ingesta de A')
            ssm=session.client('ssm');table=ssm.get_parameter(Name='/arquifusion/test/data/machines-table')['Parameter']['Value']
            machine=session.resource('dynamodb').Table(table).get_item(Key={'machine_id':args.machine})['Item']
            body['location']={**machine['location'],'zone_id':machine.get('zone_id',machine['location'].get('zone_id'))}
            request=urllib.request.Request(url,data=json.dumps({'readings':[body]},default=float).encode(),headers={'Authorization':'Bearer '+token(session,settings,'admin',part_a=True),'content-type':'application/json'})
            with urllib.request.urlopen(request,timeout=30) as response:print(response.status,response.read().decode())
            print('Lectura enviada a A. GCP debe generar y reenviar la alerta antes de que C abra el incidente.')
        else:
            print(json.dumps(api(session,settings,'/v1/pilot/telemetry',body),indent=2));print('Lectura enviada al detector por REGLAS del piloto; no es una prediccion de GCP.')
    elif args.command=='smoke':
        result=api(session,settings,'/v1/bootstrap')['data']
        print(json.dumps({'mode':result['mode'],'machines':len(result['machines']),'incidents':len(result['incidents']),'alerts':len(result['alerts'])},indent=2))
    elif args.command=='frontend':
        path=ROOT/'part-c/frontend/.env.production.local'
        path.write_text('VITE_DATA_MODE=live\nVITE_API_BASE='+settings['ApiBase']+'\nVITE_AUTH_MODE=pilot-token\n')
        print('Configuración pública escrita en '+str(path)+'. Ejecuta npm ci y npm run build en part-c/frontend.')
    elif args.command=='configure-b2':
        endpoint=input('Endpoint S3 de B2 (https://s3.REGION.backblazeb2.com): ').strip().rstrip('/')
        import re
        if not re.fullmatch(r'https://s3\.[a-z0-9-]+\.backblazeb2\.com',endpoint):raise RuntimeError('Endpoint B2 inválido')
        bucket=input('Nombre del bucket privado B2: ').strip()
        key_id=getpass.getpass('Application Key ID: ');key=getpass.getpass('Application Key: ')
        if not all((bucket,key_id,key)):raise RuntimeError('Faltan valores B2')
        session.client('secretsmanager').put_secret_value(SecretId=settings['B2SecretArn'],SecretString=json.dumps({'endpoint':endpoint,'bucket':bucket,'key_id':key_id,'application_key':key}))
        print('Credenciales guardadas en AWS Secrets Manager. No se creó archivo local con ellas.')
    elif args.command=='backup':
        result=session.client('stepfunctions').start_execution(stateMachineArn=settings['BackupWorkflowArn'],input='{}')
        print(json.dumps(result,default=str,indent=2))
    elif args.command=='backup-status':
        client=session.client('stepfunctions')
        execution=args.execution or client.list_executions(stateMachineArn=settings['BackupWorkflowArn'],maxResults=1)['executions'][0]['executionArn']
        result=client.describe_execution(executionArn=execution)
        print(json.dumps({k:result.get(k) for k in ('status','output','error','cause')},indent=2))


if __name__=='__main__':main()
