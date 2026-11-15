import copy
import hashlib
import json
import time
import uuid
from .domain import (now, check, Problem, require_role, visible_machine, visible_incident,
                     notification_targets, notification_text, ROLES)
from .operations import Operations


class Service:
    def __init__(self,port,state,mode='live',b_client=None):
        self.port,self.state,self.mode,self.b_client=port,state,mode,b_client
        self.ops=Operations(port)

    def allowed_incident(self,identifier,principal):
        snapshot=self.port.snapshot();item=next((i for i in snapshot['incidents'] if i['incident_id']==identifier),None)
        check(item is not None and visible_incident(principal,item,snapshot['machines']),'Incidente no encontrado','NOT_FOUND',404)
        return item

    def register_callback(self,identifier,phase,token,execution='local',ttl=600):
        self.state.state_put(f'TOKEN#{identifier}#{phase}',{'incident_id':identifier,'phase':phase,'token':token,
            'execution':execution,'status':'waiting','expires_at':int(time.time())+ttl})
        return {'incident_id':identifier,'phase':phase}

    def actions_for(self,item,principal):
        if principal['role'] not in ('technician','maintenance','admin'):return []
        actions=[]
        for phase in ('ack','close'):
            token=self.state.state_get(f'TOKEN#{item["incident_id"]}#{phase}')
            if token and token['status']=='waiting' and token['expires_at']>time.time():actions.append(phase)
        if item.get('acknowledged_at') and item['status']=='assigned':actions.append('start')
        return actions

    def notices(self,principal):
        def belongs(item):
            if item['role']!=principal['role']:return False
            scope=item['scope']
            return scope=='all' or scope in principal.get('zone_ids',[]) or scope in principal.get('machine_ids',[]) or scope==principal.get('technician_id')
        return sorted([n for n in self.state.states('NOTICE#') if belongs(n)],key=lambda n:n['created_at'],reverse=True)[:100]

    def notify(self,alert,role=None,sns_client=None,topic=None):
        snapshot=self.port.snapshot();incident=next((i for i in snapshot['incidents'] if i['machine_id']==alert['machine_id'] and i['status']!='closed'),None)
        saved=[]
        for target,scope,delivery in notification_targets(alert,incident):
            if role and role!=target:continue
            identifier=hashlib.sha256(f'{alert["alert_id"]}|{target}|{scope}'.encode()).hexdigest()
            key='NOTICE#'+identifier;previous=self.state.state_get(key)
            item=previous or {'notification_id':identifier,'role':target,'scope':scope,'delivery':delivery,
                'machine_id':alert['machine_id'],'severity':alert['severity'],'created_at':now(),
                'text':notification_text(alert,target),'sns_sent':False}
            self.state.state_put(key,item,only_new=True)
            if sns_client and topic and delivery=='immediate' and not item['sns_sent']:
                sns_client.publish(TopicArn=topic,Message=json.dumps(item,ensure_ascii=False),
                    MessageAttributes={'role':{'DataType':'String','StringValue':target}})
                item['sns_sent']=True;self.state.state_put(key,item)
            saved.append({'notification_id':identifier,'role':target,'scope':scope,'delivery':delivery})
        return saved

    def bootstrap(self,principal):
        snapshot=self.port.snapshot();machines=[m for m in snapshot['machines'] if visible_machine(principal,m)]
        if principal['role']=='technician':
            ids={i['machine_id'] for i in snapshot['incidents'] if i.get('technician_id')==principal.get('technician_id')}
            machines=[m for m in snapshot['machines'] if m['machine_id'] in ids]
        machine_ids={m['machine_id'] for m in machines}
        incidents=[copy.deepcopy(i) for i in snapshot['incidents'] if visible_incident(principal,i,snapshot['machines'])]
        for incident in incidents:incident['available_actions']=self.actions_for(incident,principal)
        inventory=[i for i in snapshot['inventory'] if principal['role'] in ('admin','manager') or i['zone_id'] in principal.get('zone_ids',[])]
        if principal['role']=='operator':inventory=[]
        if principal['role']=='technician':
            zones={i['zone_id'] for i in incidents}
            components={i['suspected_component'] for i in incidents}
            inventory=[i for i in snapshot['inventory'] if i['zone_id'] in zones and i['component'] in components]
        techs=[t for t in snapshot['technicians'] if principal['role'] in ('admin','manager','maintenance','supervisor') and (principal['role'] in ('admin','manager') or t['zone_id'] in principal.get('zone_ids',[]))]
        if principal['role']=='technician':techs=[t for t in snapshot['technicians'] if t['technician_id']==principal.get('technician_id')]
        result={'mode':self.mode,'as_of':now(),'principal':principal,'machines':machines,'incidents':incidents,
                'alerts':[a for a in snapshot['alerts'] if a['machine_id'] in machine_ids],
                'technicians':techs,'inventory':inventory,'notifications':self.notices(principal)}
        return result

    def analytics(self,principal):
        data=self.bootstrap(principal)
        if self.mode=='demo':
            machines=data['machines']
            return {'available':True,'provenance':'simulated','fuel':[{'machine_id':m['machine_id'],'actual_lph':m['metrics']['fuel_rate_lph'],'expected_lph':27,'delta_pct':round((m['metrics']['fuel_rate_lph']/27-1)*100,1)} for m in machines],
              'utilization':[{'machine_id':m['machine_id'],'sampled_operating_pct':86 if m['status']=='operating' else 28,'cost_index':round(m['metrics']['fuel_rate_lph']/27,2)} for m in machines],
              'maintenance':[{'machine_id':m['machine_id'],'remaining_operating_hours':max(0,250-(m['operating_hours_total']%250)),'basis':'Ejemplo de intervalo fijo, no pronóstico'} for m in machines],
              'common_cause':[{'zone_id':'ZONA-NORTE-02','machine_ids':['MCH-000001','MCH-000004','MCH-000006'],'hypothesis':'Patrón coincidente; investigar combustible y condiciones de operación','confirmed':False}] if any(m['zone_id']=='ZONA-NORTE-02' for m in machines) else []}
        if not self.b_client:return {'available':False,'message':'Servicio de Nico sin configurar','provenance':'unavailable'}
        endpoints={'fuel':'/v1/analytics/fuel','utilization':'/v1/analytics/utilization','maintenance':'/v1/predictions/maintenance','common_cause':'/v1/analytics/common-cause'}
        result={'available':True,'provenance':'live','errors':{}}
        ids={m['machine_id'] for m in data['machines']}
        for kind,path in endpoints.items():
            try:
                rows=self.b_client.get(path).get('data',[])
                result[kind]=[r for r in rows if r.get('machine_id') in ids or (r.get('machine_ids') and all(i in ids for i in r['machine_ids']))]
            except Exception:
                result[kind]=[];result['errors'][kind]='No disponible; no se sustituyó por datos de demostración'
        return result

    def callback(self,identifier,phase,payload,principal,command):
        require_role(principal,'technician','maintenance','admin')
        incident=self.allowed_incident(identifier,principal)
        if phase=='start':return self.ops.start(identifier,principal['sub'],command)
        key=f'TOKEN#{identifier}#{phase}';record=self.state.state_get(key)
        check(record is not None,'El workflow aún no habilitó esta acción. Actualiza en unos segundos.')
        request_hash=hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()
        if record.get('command_id')==command and record.get('status')=='consumed':
            check(record['request_hash']==request_hash,'Idempotency-Key reutilizada con otro cuerpo')
            return {'incident_id':identifier,'accepted':True,'duplicate':True}
        if phase=='ack':check(incident['status']=='assigned','El incidente debe estar asignado')
        if phase=='close':self.ops.validate_close(identifier,payload)
        check(record['status']=='waiting' and record['expires_at']>time.time(),'La espera caducó o ya fue atendida. Actualiza el incidente.')
        output={'incident_id':identifier,'actor':principal['sub'],'command_id':command,'payload':payload}
        if self.mode=='demo':
            if phase=='ack':
                self.ops.ack(identifier,principal['sub'],command)
                self.register_callback(identifier,'close','demo-close',ttl=86400)
            elif phase=='close':self.ops.close(identifier,payload,principal['sub'],command)
        else:
            import boto3
            from botocore.exceptions import ClientError
            try:boto3.client('stepfunctions').send_task_success(taskToken=record['token'],output=json.dumps(output))
            except ClientError as exc:
                if exc.response['Error']['Code'] in ('TaskDoesNotExist','TaskTimedOut','InvalidToken'):
                    raise Problem('La espera cambió; actualiza para conocer el estado vigente','CONFLICT',409)
                raise
        record.update(status='consumed',command_id=command,request_hash=request_hash)
        self.state.state_put(key,record)
        return {'incident_id':identifier,'accepted':True,'message':'Callback aceptado; el workflow actualizará el estado'}

    def route(self,method,path,payload,principal,command=None):
        command=command or str(uuid.uuid4())
        if method=='GET' and path=='/v1/bootstrap':return self.bootstrap(principal)
        if method=='GET' and path=='/v1/analytics':return self.analytics(principal)
        if method=='GET' and path.startswith('/v1/incidents/') and path.endswith('/explanation'):
            identifier=path.split('/')[3];incident=self.allowed_incident(identifier,principal)
            alert_id=(incident.get('alert_ids') or [None])[0]
            if self.mode=='demo':return {'available':True,'source':'demo','model':None,'text':f"{incident['summary']}. Revisar {incident['suspected_component'].replace('_',' ')} y contrastar sensores antes de decidir una reparación.",'grounded_on':[alert_id] if alert_id else []}
            if not self.b_client:return {'available':False,'source':'unavailable'}
            import urllib.parse
            try:
                value=self.b_client.get('/v1/ai/explain?'+urllib.parse.urlencode({'alert_id':alert_id,'role':principal['role']}))
                value=value.get('data',value);return {'available':True,'source':'service-b',**value}
            except Exception:return {'available':False,'source':'unavailable'}
        if method=='GET' and path.startswith('/v1/machines/') and path.endswith('/telemetry'):
            identifier=path.split('/')[3]
            check(identifier in {m['machine_id'] for m in self.bootstrap(principal)['machines']},'Máquina no encontrada','NOT_FOUND',404)
            return {'data':self.port.telemetry(identifier)[-1000:],'next_token':None}
        if method=='POST' and path=='/v1/assignments/suggest':
            require_role(principal,'maintenance','admin');visible={i['incident_id'] for i in self.bootstrap(principal)['incidents']}
            check(all(i in visible for i in payload.get('incident_ids',[])),'Incidente no autorizado','FORBIDDEN',403)
            result=self.ops.suggestions(payload.get('incident_ids',[]));result['baseline']=self.ops.suggestions(payload.get('incident_ids',[]),'greedy');return result
        if method=='POST' and path=='/v1/assignments/confirm':
            require_role(principal,'maintenance','admin');visible={i['incident_id'] for i in self.bootstrap(principal)['incidents']}
            check(all(a['incident_id'] in visible for a in payload.get('assignments',[])),'Incidente no autorizado','FORBIDDEN',403)
            result=self.ops.confirm(payload,command,principal['sub'])
            for assignment in result['assignments']:
                token=self.state.state_get(f'TOKEN#{assignment["incident_id"]}#assignment')
                if token and token['status']=='waiting':
                    if self.mode!='demo':
                        import boto3
                        boto3.client('stepfunctions').send_task_success(taskToken=token['token'],output=json.dumps(assignment))
                    token['status']='consumed';self.state.state_put(f'TOKEN#{assignment["incident_id"]}#assignment',token)
                if self.mode=='demo':self.register_callback(assignment['incident_id'],'ack','demo-ack',ttl=86400)
            return result
        if method=='POST' and path.startswith('/v1/incidents/'):
            parts=path.strip('/').split('/')
            check(len(parts)==4 and parts[3] in ('ack','start','close'),'Ruta no encontrada','NOT_FOUND',404)
            return self.callback(parts[2],parts[3],payload,principal,command)
        if method=='POST' and path=='/v1/demo/scenario' and self.mode=='demo':
            require_role(principal,'maintenance','admin')
            snapshot=self.port.snapshot();machine=next((m for m in snapshot['machines'] if m['machine_id'] not in {i['machine_id'] for i in snapshot['incidents'] if i['status']!='closed'} and m['zone_id'] in principal.get('zone_ids',[])),None)
            check(machine is not None,'No quedan máquinas libres para otra escena')
            alert={'schema_version':'1.0','alert_id':'ALT-DEMO-'+uuid.uuid4().hex[:8].upper(),'machine_id':machine['machine_id'],
                'zone_id':machine['zone_id'],'created_at':now(),'severity':'critical','score':94,'type':'anomaly','summary':'Deriva multivariable inyectada para demostrar el flujo',
                'suspected_component':'cooling_system','recommended_action':'stop_and_inspect_now','evidence':[],'related_machine_ids':[]}
            self.port.commit(command,[{'kind':'alerts','id':alert['alert_id'],'version':None}],[{'kind':'alerts','id':alert['alert_id'],'value':{**alert,'version':1}}],{'alert_id':alert['alert_id']},payload)
            result=self.ops.create_incident(alert,command+'-inc');identifier=result['incident_id']
            proposed=self.ops.suggestions([identifier])
            if proposed['assignments']:
                self.ops.confirm({'assignments':proposed['assignments']},command+'-asg','local-workflow')
                self.register_callback(identifier,'ack','demo-ack',ttl=86400)
            else:self.register_callback(identifier,'assignment','demo-assignment',ttl=86400)
            self.notify(alert);return {'incident_id':identifier,'mode':'demo'}
        raise Problem('Ruta no encontrada','NOT_FOUND',404)
