import hashlib
import hmac
import json
import os
import time
import urllib.request
import urllib.parse
from functools import lru_cache
from .domain import Problem,claims_principal,now
from .store import LambdaPort,DynamoState
from .service import Service


class BClient:
    def __init__(self,base,secret_arn=''):
        if not base.startswith('https://'):raise ValueError('B_API_BASE requiere HTTPS')
        self.base=base.rstrip('/');self.secret_arn=secret_arn

    @lru_cache
    def secret(self):
        import boto3
        value=boto3.client('secretsmanager').get_secret_value(SecretId=self.secret_arn)['SecretString']
        return json.loads(value).get('shared_key',value) if value.startswith('{') else value

    def get(self,path):
        headers={'accept':'application/json'}
        if self.secret_arn:
            stamp=str(int(time.time()));canonical=f'{stamp}\nGET\n{path}\n'.encode()
            headers.update({'x-timestamp':stamp,'x-signature':hmac.new(self.secret().encode(),canonical,hashlib.sha256).hexdigest(),'x-signature-version':'c-1'})
        request=urllib.request.Request(self.base+path,headers=headers)
        with urllib.request.urlopen(request,timeout=5) as response:return json.load(response)


@lru_cache
def service():
    base=os.environ.get('B_API_BASE','')
    return Service(LambdaPort(os.environ['A_ADAPTER_ARN']),DynamoState(os.environ['C_STATE_TABLE']),
                   b_client=BClient(base,os.environ.get('B_AUTH_SECRET_ARN','')) if base else None)


def response(status,data):
    return {'statusCode':status,'headers':{'content-type':'application/json','cache-control':'no-store'},'body':json.dumps(data,ensure_ascii=False,allow_nan=False)}


def api_handler(event,context):
    try:
        claims=event.get('requestContext',{}).get('authorizer',{}).get('jwt',{}).get('claims',{})
        if claims.get('token_use')!='id':raise Problem('Se requiere un ID token del cliente Cognito autorizado','UNAUTHORIZED',401)
        # Solo claims ya validados por API Gateway; nunca se confía en x-role o JWT decodificado por el navegador.
        principal=claims_principal(claims)
        method=event['requestContext']['http']['method'];path=event['rawPath']
        raw=event.get('body') or ''
        if event.get('isBase64Encoded'):
            import base64;raw=base64.b64decode(raw).decode()
        if len(raw)>262144:raise Problem('Payload demasiado grande','VALIDATION_ERROR',413)
        body=json.loads(raw) if raw else {}
        headers={k.lower():v for k,v in event.get('headers',{}).items()}
        command=headers.get('idempotency-key')
        if method=='POST' and (not command or len(command)>120):raise Problem('Idempotency-Key requerido (máximo 120 caracteres)')
        output=service().route(method,path,body,principal,command)
        return response(200,{'data':output})
    except Problem as exc:return response(exc.status,{'error':{'code':exc.code,'message':str(exc)}})
    except (KeyError,ValueError,TypeError) as exc:return response(400,{'error':{'code':'VALIDATION_ERROR','message':str(exc)}})
    except Exception:
        import logging;logging.exception('c_api_failed');return response(502,{'error':{'code':'UPSTREAM_ERROR','message':'No fue posible completar la operación. No se usaron datos de demo.'}})


def workflow_handler(event,context):
    svc=service();action=event['action'];alert=event.get('alert');identifier=event.get('incident_id')
    command=event.get('command_id') or f"workflow:{action}:{identifier or (alert or {}).get('alert_id')}"
    if action=='create':return svc.ops.create_incident(alert,command)
    if action=='context':
        snapshot=svc.port.snapshot();machine=next((m for m in snapshot['machines'] if m['machine_id']==alert['machine_id']),None)
        return {'machine':machine,'available_technicians':sum(t['availability']=='available' for t in snapshot['technicians'])}
    if action=='explain':
        if svc.b_client:
            try:return svc.b_client.get('/v1/ai/explain?'+urllib.parse.urlencode({'alert_id':alert['alert_id'],'role':'technician'}))
            except Exception:pass
        return {'text':alert['summary'],'grounded_on':[alert['alert_id']],'model':None,'source':'deterministic_fallback','ai_available':False}
    if action=='assign':
        incident=svc.ops.get_incident(identifier)
        if incident.get('technician_id') and incident['status'] in ('assigned','in_progress'):
            return {'incident_id':identifier,'assigned':True,'technician_id':incident['technician_id']}
        proposed=svc.ops.suggestions([identifier],excluded=event.get('excluded',[]))
        if proposed['assignments']:
            assigned=svc.ops.confirm({'assignments':proposed['assignments']},command,'workflow')
            return {'incident_id':identifier,'assigned':True,'technician_id':assigned['assignments'][0]['technician_id']}
        return {'incident_id':identifier,'assigned':False,'reason':'No hay especialistas disponibles'}
    if action=='wait':return svc.register_callback(identifier,event['phase'],event['task_token'],event.get('execution',''),event.get('ttl',600))
    if action=='ack':
        callback=event['callback'];return svc.ops.ack(identifier,callback['actor'],callback['command_id'])
    if action=='finalize':
        callback=event['callback'];return svc.ops.close(identifier,callback['payload'],callback['actor'],callback['command_id'])
    if action=='escalate':
        import boto3
        item=svc.ops.get_incident(identifier)
        if item.get('acknowledged_at'):return {'incident_id':identifier,'already_acknowledged':True,'excluded':event.get('excluded',[])}
        previous=item.get('technician_id');svc.ops.release_for_escalation(identifier,command)
        boto3.client('sns').publish(TopicArn=os.environ['SNS_TOPIC_ARN'],Message=json.dumps({'incident_id':identifier,'type':'escalation','message':'Técnico sin confirmar; se busca otro candidato'}))
        return {'incident_id':identifier,'already_acknowledged':False,'excluded':list(set(event.get('excluded',[])+([previous] if previous else [])))}
    if action=='notify':
        import boto3
        notices=svc.notify(alert,role=event.get('role'),sns_client=boto3.client('sns'),topic=os.environ['SNS_TOPIC_ARN'])
        return {'notifications':notices}
    if action=='stock_low':
        import boto3
        part=event['part'];boto3.client('sns').publish(TopicArn=os.environ['SNS_TOPIC_ARN'],Message=json.dumps({'type':'spare.stock_low','part':part}));return {'part_id':part['part_id']}
    raise Problem('Acción de workflow desconocida')


def event_handler(event,context):
    import boto3
    alert=event.get('detail',event.get('alert'))
    if not isinstance(alert,dict) or not all(k in alert for k in ('alert_id','machine_id','severity','score','zone_id','summary','suspected_component')):raise Problem('Evento alert.created inválido')
    payload=json.dumps({'alert':alert,'excluded':[]},separators=(',',':'));name=hashlib.sha256(alert['alert_id'].encode()).hexdigest()
    client=boto3.client('stepfunctions')
    for env in ('SF1_ARN','SF3_ARN'):
        try:client.start_execution(stateMachineArn=os.environ[env],name=name,input=payload)
        except client.exceptions.ExecutionAlreadyExists:pass
    return {'accepted':True,'alert_id':alert['alert_id']}
