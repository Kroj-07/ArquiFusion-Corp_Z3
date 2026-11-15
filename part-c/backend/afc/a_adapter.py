"""Adaptador de integración para A. Ejecutar en la cuenta/región de las tablas de Kiara.

El lector de catálogos usa Scan acotado para el piloto. A debe sustituir snapshot
por sus consultas indexadas antes de pruebas de escala. Las escrituras ya son
condicionales y transaccionales, con un marcador durable de idempotencia.
"""
import hashlib
import json
import os
from decimal import Decimal
import boto3
from boto3.dynamodb.types import TypeSerializer
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError
from .domain import Problem,check

ENV={'machines':'MACHINES_TABLE','incidents':'INCIDENTS_TABLE','technicians':'TECHNICIANS_TABLE','inventory':'INVENTORY_TABLE','alerts':'ALERTS_TABLE'}
KEYS={'machines':('machine_id',),'incidents':('machine_id','opened_at'),'technicians':('technician_id',),'inventory':('zone_id','part_id'),'alerts':('machine_id','created_at')}

def native(value):return json.loads(json.dumps(value,default=lambda v:int(v) if v%1==0 else float(v)))
def serial(value):
    normalized=json.loads(json.dumps(value),parse_float=Decimal);serializer=TypeSerializer()
    return {k:serializer.serialize(v) for k,v in normalized.items()}

def commands():return boto3.resource('dynamodb').Table(os.environ['C_COMMANDS_TABLE'])
def digest(request):return hashlib.sha256(json.dumps(request,sort_keys=True).encode()).hexdigest()

def lookup(command,request):
    marker=commands().get_item(Key={'pk':'COMMAND#'+command,'sk':'STATE'},ConsistentRead=True).get('Item')
    if not marker:return None
    check(marker['digest']==digest(request),'Idempotency-Key reutilizada con otro contenido')
    return json.loads(marker['result'])

def catalog(kind):
    table=boto3.resource('dynamodb').Table(os.environ[ENV[kind]]);items=[];cursor=None
    while True:
        kwargs={'Limit':200,'ConsistentRead':True}
        if cursor:kwargs['ExclusiveStartKey']=cursor
        page=table.scan(**kwargs);items+=page['Items'];cursor=page.get('LastEvaluatedKey')
        check(len(items)<=1000,'Adaptador piloto limitado a 1000 filas por catálogo. Reemplazar Scan con las APIs paginadas de A.','CAPACITY_LIMIT',503)
        if not cursor:break
    result=native(items)
    for item in result:
        item.setdefault('version',1)
        if kind=='inventory':item['key']=item['zone_id']+'|'+item['part_id']
        if kind=='machines' and 'zone_id' not in item and item.get('location'):item['zone_id']=item['location'].get('zone_id')
    return result

def commit(event):
    command=event['command_id'];request=event.get('request') or event['changes']
    prior=lookup(command,request)
    if prior is not None:return prior
    changes=event['changes'];expected={(c['kind'],c['id']):c['version'] for c in event['expected']}
    check(0<len(changes)<=90,'Transacción demasiado grande')
    items=[];seen=set()
    for change in changes:
        kind=change['kind'];check(kind in ('machines','incidents','technicians','inventory'),'Entidad de escritura no autorizada','FORBIDDEN',403)
        value=change['value'];keys={k:value[k] for k in KEYS[kind]};version=expected[kind,change['id']]
        identity=(kind,tuple(keys.values()));check(identity not in seen,'Dos acciones sobre el mismo ítem');seen.add(identity)
        condition='attribute_not_exists(#pk)' if version is None else 'attribute_exists(#pk) AND (#version = :old'+(' OR attribute_not_exists(#version)' if version==1 else '')+')'
        put={'TableName':os.environ[ENV[kind]],'Item':serial(value),'ConditionExpression':condition,'ExpressionAttributeNames':{'#pk':KEYS[kind][0]}}
        if version is not None:
            put['ExpressionAttributeNames']['#version']='version';put['ExpressionAttributeValues']=serial({':old':version})
        items.append({'Put':put})
    marker={'pk':'COMMAND#'+command,'sk':'STATE','digest':digest(request),'result':json.dumps(event['result'])}
    items.append({'Put':{'TableName':os.environ['C_COMMANDS_TABLE'],'Item':serial(marker),'ConditionExpression':'attribute_not_exists(pk)'}})
    try:boto3.client('dynamodb').transact_write_items(TransactItems=items)
    except ClientError as exc:
        if exc.response['Error']['Code']=='TransactionCanceledException':
            prior=lookup(command,request)
            if prior is not None:return prior
            raise Problem('Datos cambiaron. No se aplicó ninguna parte de la transacción.','CONFLICT',409)
        raise
    return event['result']

def handler(event,context):
    try:
        op=event['op']
        if op=='snapshot':result={**{kind:catalog(kind) for kind in ENV},'telemetry':[]}
        elif op=='lookup':result=lookup(event['command_id'],event['request'])
        elif op=='commit':result=commit(event)
        elif op=='telemetry':
            table=boto3.resource('dynamodb').Table(os.environ['TELEMETRY_TABLE'])
            page=table.query(KeyConditionExpression=Key('machine_id').eq(event['machine_id']),ScanIndexForward=False,Limit=1000)
            result=sorted([native(r.get('reading',r)) for r in page['Items']],key=lambda r:r['timestamp'])
        else:raise Problem('Operación de adaptador no soportada')
        return {'data':result}
    except Problem as exc:return {'error':{'code':exc.code,'message':str(exc),'status':exc.status}}
