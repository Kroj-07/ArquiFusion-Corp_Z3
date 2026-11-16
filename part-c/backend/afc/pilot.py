"""Adaptación de despliegue del piloto: JWT temporal, telemetría e IA entre nubes."""
import base64
import hashlib
import hmac
import json
import math
import os
import time
import urllib.request
import uuid
from decimal import Decimal
from functools import lru_cache

import boto3
from . import cloud
from .domain import Problem, check, claims_principal, now, require_role


@lru_cache
def secret(arn):
    return json.loads(boto3.client('secretsmanager').get_secret_value(SecretId=arn)['SecretString'])


def verify_token(token, key, current=None):
    current = time.time() if current is None else current
    try:
        header, payload, signature = token.split('.')
        decode = lambda s: base64.urlsafe_b64decode(s + '=' * (-len(s) % 4))
        metadata = json.loads(decode(header))
        claims = json.loads(decode(payload))
        expected = hmac.new(key.encode(), (header+'.'+payload).encode(), hashlib.sha256).digest()
        valid = metadata.get('alg') == 'HS256' and hmac.compare_digest(expected, decode(signature))
        valid = valid and claims.get('iss') == 'arquifusion-pilot' and claims.get('aud') == 'arquifusion-web'
        exp = claims.get('exp')
        valid = valid and type(exp) in (int, float) and current < exp <= current + 18000
        if not valid:
            raise ValueError('invalid token')
        return claims_principal(claims)
    except (ValueError, TypeError, KeyError, UnicodeError):
        raise Problem('Sesión inválida o vencida. Solicita un token nuevo.', 'UNAUTHORIZED', 401)


def validate_reading(reading):
    check(isinstance(reading, dict), 'Se requiere una lectura JSON', 'VALIDATION_ERROR', 400)
    from datetime import datetime
    import re
    check(bool(re.fullmatch(r'MCH-[0-9]{6}', str(reading.get('machine_id', '')))), 'machine_id inválido', 'VALIDATION_ERROR', 400)
    try:
        stamp = datetime.fromisoformat(reading['timestamp'].replace('Z', '+00:00'))
        if stamp.tzinfo is None: raise ValueError()
    except (KeyError, TypeError, ValueError, AttributeError):
        raise Problem('timestamp debe incluir zona horaria', 'VALIDATION_ERROR', 400)
    metrics = reading.get('metrics', {})
    for name, low, high in [('engine_temp_c', -50, 250), ('vibration_mm_s', 0, 200), ('pressure_bar', 0, 1000), ('fuel_rate_lph', 0, 1000)]:
        value = metrics.get(name)
        check(type(value) in (int, float) and math.isfinite(value) and low <= value <= high, 'Sensor inválido: '+name, 'VALIDATION_ERROR', 400)
    return reading


def explain_alert(alert, role):
    svc = cloud.service()
    cache_key = 'AI#'+alert['alert_id']+'#'+role
    cached = svc.state.state_get(cache_key)
    if cached and cached.get('expires_at', 0) > time.time(): return cached['response']
    base = os.environ.get('B_API_BASE', '').rstrip('/')
    if not base: raise Problem('Cloudflare aún no está conectado', 'SERVICE_NOT_CONFIGURED', 503)
    path = '/v1/ai/explain'
    body = json.dumps({'alert': alert, 'role': role}, separators=(',', ':'), ensure_ascii=False).encode()
    stamp = str(int(time.time()))
    key = secret(os.environ['B_AUTH_SECRET_ARN'])['shared_key']
    canonical = (stamp+'\nPOST\n'+path+'\n').encode()+body
    headers = {'content-type':'application/json', 'x-timestamp':stamp, 'x-signature-version':'c-1',
               'x-signature':hmac.new(key.encode(), canonical, hashlib.sha256).hexdigest()}
    request = urllib.request.Request(base+path, data=body, headers=headers, method='POST')
    with urllib.request.urlopen(request, timeout=20) as response:
        result = json.load(response)['data']
    check(bool(result.get('text')) and result.get('model'), 'La IA no devolvió una explicación', 'UPSTREAM_ERROR', 502)
    output = {'available':True, 'source':'cloudflare-workers-ai', **result}
    svc.state.state_put(cache_key, {'response':output, 'expires_at':int(time.time())+3600})
    return output


def analytics(principal):
    svc = cloud.service(); snapshot = svc.bootstrap(principal)
    gcp_base=os.environ.get('GCP_API_BASE','').strip()
    if gcp_base:
        client=cloud.BClient(gcp_base,os.environ['GCP_AUTH_SECRET_ARN'])
        ids={m['machine_id'] for m in snapshot['machines']}
        result={'available':True,'provenance':'gcp-cloud-run','errors':{}}
        endpoints={'fuel':'/v1/analytics/fuel','utilization':'/v1/analytics/utilization','maintenance':'/v1/predictions/maintenance','common_cause':'/v1/analytics/common-cause'}
        for kind,path in endpoints.items():
            try:
                rows=client.get(path).get('data',[])
                result[kind]=[row for row in rows if row.get('machine_id') in ids or (row.get('machine_ids') and all(i in ids for i in row['machine_ids']))]
            except Exception:
                result[kind]=[];result['errors'][kind]='El servicio GCP no respondió; no se usaron resultados simulados de reemplazo.'
        result['available']=len(result['errors'])<len(endpoints)
        return result
    rows = []; utilization = []; maintenance = []; groups = {}
    for machine in snapshot['machines']:
        history = svc.port.telemetry(machine['machine_id'])[-100:]
        fuel = [r['metrics']['fuel_rate_lph'] for r in history if r.get('metrics', {}).get('fuel_rate_lph') is not None]
        if fuel: rows.append({'machine_id':machine['machine_id'], 'actual_lph':round(sum(fuel)/len(fuel), 2), 'expected_lph':None, 'delta_pct':None})
        utilization.append({'machine_id':machine['machine_id'], 'sampled_operating_pct':round(100*sum(r.get('status')=='operating' for r in history)/len(history), 1) if history else None, 'cost_index':None})
        hours = machine.get('operating_hours_total', 0)
        maintenance.append({'machine_id':machine['machine_id'], 'remaining_operating_hours':500-hours%500, 'basis':'Regla ilustrativa cada 500 h; no es un pronóstico de IA'})
        if machine.get('risk_score', 0) >= 70: groups.setdefault(machine['zone_id'], []).append(machine['machine_id'])
    common = [{'zone_id':zone, 'machine_ids':ids, 'hypothesis':'Alertas de reglas coincidentes en una zona; investigar condiciones compartidas.', 'confirmed':False} for zone, ids in groups.items() if len(ids)>1]
    return {'available':True, 'provenance':'aws-simulated-telemetry', 'fuel':rows, 'utilization':utilization, 'maintenance':maintenance, 'common_cause':common}


def api_handler(event, context):
    try:
        method = event['requestContext']['http']['method']; path = event['rawPath']
        if method == 'POST' and path in ('/v1/auth/login', '/v1/auth/refresh'):
            from . import password_auth
            raw = event.get('body') or ''
            if event.get('isBase64Encoded'): raw = base64.b64decode(raw).decode()
            check(len(raw.encode()) <= 16384, 'Solicitud demasiado grande', 'VALIDATION_ERROR', 413)
            handler = password_auth.login if path.endswith('/login') else password_auth.refresh
            return cloud.response(200, {'data': handler(json.loads(raw), secret(os.environ['PILOT_JWT_SECRET']))})
        headers = {k.lower():v for k, v in event.get('headers', {}).items()}
        auth = headers.get('authorization', '')
        check(auth.startswith('Bearer '), 'Se requiere una sesión', 'UNAUTHORIZED', 401)
        principal = verify_token(auth[7:], secret(os.environ['PILOT_JWT_SECRET'])['jwt_secret'])
        method = event['requestContext']['http']['method']; path = event['rawPath']
        raw = event.get('body') or ''
        if event.get('isBase64Encoded'): raw = base64.b64decode(raw).decode()
        check(len(raw.encode()) <= 262144, 'Solicitud demasiado grande', 'VALIDATION_ERROR', 413)
        body = json.loads(raw) if raw else {}
        command = headers.get('idempotency-key')
        if method == 'POST': check(command and len(command)<=120, 'Idempotency-Key requerido', 'VALIDATION_ERROR', 400)
        if method == 'POST' and path == '/v1/pilot/telemetry':
            require_role(principal, 'admin', 'maintenance')
            validate_reading(body)
            if body.get('renew_simulated_shifts') is True:
                renew_simulated_shifts(command)
            boto3.client('sqs').send_message(QueueUrl=os.environ['INGEST_QUEUE'], MessageBody=json.dumps(body, allow_nan=False))
            return cloud.response(202, {'data':{'accepted':True, 'machine_id':body['machine_id']}})
        if method == 'GET' and path == '/v1/bootstrap':
            result=cloud.service().bootstrap(principal)
            latest={}
            for alert in sorted(result['alerts'],key=lambda a:a.get('created_at','')):latest[alert['machine_id']]=alert
            for machine in result['machines']:
                if machine['machine_id'] in latest:machine['risk_score']=latest[machine['machine_id']]['score']
        elif method == 'GET' and path == '/v1/analytics': result = analytics(principal)
        elif method == 'GET' and path.startswith('/v1/incidents/') and path.endswith('/explanation'):
            svc = cloud.service(); incident = svc.allowed_incident(path.split('/')[3], principal)
            identifier = (incident.get('alert_ids') or [None])[0]
            alert = next((a for a in svc.port.snapshot()['alerts'] if a['alert_id']==identifier), None)
            check(alert is not None, 'No se encontró la alerta', 'NOT_FOUND', 404)
            result = explain_alert(alert, principal['role'])
        else: result = cloud.service().route(method, path, body, principal, command)
        return cloud.response(200, {'data':result})
    except Problem as exc: return cloud.response(exc.status, {'error':{'code':exc.code, 'message':str(exc)}})
    except (ValueError, KeyError, TypeError): return cloud.response(400, {'error':{'code':'VALIDATION_ERROR', 'message':'Solicitud inválida'}})
    except Exception:
        import logging; logging.exception('pilot_api_failed')
        return cloud.response(502, {'error':{'code':'UPSTREAM_ERROR', 'message':'Falló un servicio. Revisa CloudWatch; no se generaron resultados ficticios.'}})


def workflow_handler(event, context):
    if event.get('action') == 'explain':
        try: return explain_alert(event['alert'], 'technician')
        except Exception:
            return {'available':False, 'source':'unavailable', 'text':'IA pendiente; el incidente continúa con su evidencia original.'}
    return cloud.workflow_handler(event, context)


def rule_alert(reading, machine):
    metrics = reading['metrics']
    temp, vib, pressure = (metrics[k] for k in ('engine_temp_c', 'vibration_mm_s', 'pressure_bar'))
    if temp >= 105 and vib >= 5:
        component, score, severity = 'cooling_system', 96, 'critical'
    elif pressure < 4:
        component, score, severity = 'hydraulic_system', 83, 'high'
    else: return None
    identifier = hashlib.sha256((reading['machine_id']+'|'+reading['timestamp']).encode()).hexdigest()[:20]
    return {'schema_version':'1.0', 'alert_id':'ALT-PILOT-'+identifier, 'machine_id':reading['machine_id'],
            'zone_id':machine['zone_id'], 'created_at':reading['timestamp'], 'type':'anomaly', 'severity':severity,
            'score':score, 'confidence':None, 'summary':'Regla multivariable activada en telemetría simulada. Requiere inspección.',
            'suspected_component':component, 'recommended_action':'stop_and_inspect_now' if severity=='critical' else 'inspect_within_24h',
            'evidence':[{'metric':k,'observed':metrics[k],'expected':e,'window':'lectura actual','trend':'not_evaluated'} for k,e in [('engine_temp_c',85),('vibration_mm_s',3),('pressure_bar',6)]],
            'related_machine_ids':[], 'detection_method':'deterministic_rule', 'version':1, 'event_published':False}


def renew_simulated_shifts(command):
    """Solo fixtures conocidos y disponibles; conserva las reservas de tecnicos ocupados."""
    from datetime import datetime, timedelta, timezone
    from .seed import seed
    svc = cloud.service()
    known = {t['technician_id']: t['name'] for t in seed()['technicians']}
    until = (datetime.now(timezone.utc) + timedelta(hours=8)).isoformat().replace('+00:00', 'Z')
    entities = []
    for technician in svc.port.snapshot()['technicians']:
        if (known.get(technician['technician_id']) == technician.get('name')
                and technician.get('availability') == 'available' and not technician.get('active_incident_id')):
            updated = {**technician, 'shift_end': until, 'is_sample': True}
            entities.append(('technicians', technician, updated))
    if entities:
        svc.ops._commit(command + '-demo-shifts', {'action': 'renew_simulated_shifts'}, entities,
                        {'renewed': len(entities)})


def ingest_handler(event, context):
    from botocore.exceptions import ClientError
    db = boto3.resource('dynamodb'); failures = []
    table = lambda key: db.Table(os.environ[key])
    native = lambda value: json.loads(json.dumps(value), parse_float=Decimal)
    for record in event.get('Records', []):
        try:
            reading = validate_reading(json.loads(record['body']))
            machine_table = table('MACHINES_TABLE')
            machine = machine_table.get_item(Key={'machine_id':reading['machine_id']}, ConsistentRead=True).get('Item')
            check(machine is not None, 'Máquina no registrada')
            alert = rule_alert(reading, machine)
            telemetry = {**reading, 'ttl':int(time.time())+2592000, 'simulated':True}
            try: table('TELEMETRY_TABLE').put_item(Item=native(telemetry), ConditionExpression='attribute_not_exists(machine_id)')
            except ClientError as exc:
                if exc.response['Error']['Code']!='ConditionalCheckFailedException': raise
            # El objeto es determinista y S3 mantiene sus versiones.
            object_key='telemetry-pilot/'+reading['machine_id']+'/'+hashlib.sha256(reading['timestamp'].encode()).hexdigest()+'.json'
            boto3.client('s3').put_object(Bucket=os.environ['DATA_BUCKET'], Key=object_key, Body=json.dumps(reading).encode(), ContentType='application/json')
            # Actualizar atributos, no reemplazar una fila que otra transacción está usando.
            try:
                machine_table.update_item(Key={'machine_id':reading['machine_id']},
                    UpdateExpression='SET #metrics=:metrics, last_seen=:stamp, risk_score=:risk, #v=if_not_exists(#v,:zero)+:one',
                    ConditionExpression='attribute_not_exists(last_seen) OR last_seen <= :stamp',
                    ExpressionAttributeNames={'#v':'version', '#metrics':'metrics'},
                    ExpressionAttributeValues=native({':metrics':reading['metrics'], ':stamp':reading['timestamp'], ':risk':alert['score'] if alert else 0, ':zero':0, ':one':1}))
            except ClientError as exc:
                if exc.response['Error']['Code']!='ConditionalCheckFailedException': raise
                # Una lectura atrasada se conserva en el historial y no reemplaza el estado actual.
                continue
            if alert:
                alerts = table('ALERTS_TABLE'); key = {'machine_id':alert['machine_id'], 'created_at':alert['created_at']}
                try: alerts.put_item(Item=native(alert), ConditionExpression='attribute_not_exists(machine_id)')
                except ClientError as exc:
                    if exc.response['Error']['Code']!='ConditionalCheckFailedException': raise
                saved = alerts.get_item(Key=key, ConsistentRead=True)['Item']
                if machine.get('active_incident_id'):
                    alerts.update_item(Key=key, UpdateExpression='SET event_published=:yes, suppressed_for_incident=:incident',
                        ExpressionAttributeValues={':yes':True, ':incident':machine['active_incident_id']})
                elif not saved.get('event_published'):
                    result = boto3.client('events').put_events(Entries=[{'EventBusName':os.environ['EVENT_BUS'], 'Source':'arquifusion.pilot', 'DetailType':'alert.created', 'Detail':json.dumps(alert)}])
                    check(result['FailedEntryCount']==0, 'No se pudo publicar la alerta')
                    alerts.update_item(Key=key, UpdateExpression='SET event_published=:yes', ExpressionAttributeValues={':yes':True})
        except Exception as exc:
            import logging; logging.exception('pilot_ingest_failed')
            failures.append({'itemIdentifier':record['messageId']})
    return {'batchItemFailures':failures}
