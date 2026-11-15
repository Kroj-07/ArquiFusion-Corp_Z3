import copy
from datetime import datetime, timezone, timedelta
from .domain import now, check, Problem, require_role
from .assignment import suggest


class Operations:
    def __init__(self,port):self.port=port

    def _commit(self,command,request,entities,result):
        expected=[];changes=[]
        for kind,old,new in entities:
            field={'incidents':'incident_id','technicians':'technician_id','inventory':'key','machines':'machine_id','alerts':'alert_id'}[kind]
            new=copy.deepcopy(new);new['version']=(old.get('version',1) if old else 0)+1
            identifier=new[field]
            expected.append({'kind':kind,'id':identifier,'version':old.get('version',1) if old else None})
            changes.append({'kind':kind,'id':identifier,'value':new})
        return self.port.commit(command,expected,changes,result,request)

    def suggestions(self,ids,engine='auto',excluded=None):
        snapshot=self.port.snapshot(); selected=[i for i in snapshot['incidents'] if i['incident_id'] in ids and i['status']=='open']
        check(len(ids)==len(set(ids)) and len(ids)<=20,'Selecciona hasta 20 incidentes distintos','VALIDATION_ERROR',400)
        check(len(selected)==len(ids),'Solo se pueden sugerir incidentes abiertos sin asignar')
        result=suggest(selected,snapshot['technicians'],snapshot['machines'],excluded,engine)
        result['generated_at']=now();return result

    def confirm(self,payload,command,actor):
        prior=self.port.lookup(command,{'action':'confirm',**payload})
        if prior is not None:return prior
        assignments=payload.get('assignments',[])
        check(isinstance(assignments,list) and 0<len(assignments)<=20,'Se requieren de 1 a 20 asignaciones','VALIDATION_ERROR',400)
        ids=[a['incident_id'] for a in assignments];tech_ids=[a['technician_id'] for a in assignments]
        check(len(set(ids))==len(ids) and len(set(tech_ids))==len(tech_ids),'No se puede reservar dos veces al mismo técnico o incidente')
        snapshot=self.port.snapshot();incidents={i['incident_id']:i for i in snapshot['incidents']};technicians={t['technician_id']:t for t in snapshot['technicians']}
        entities=[];result=[]
        for assignment in assignments:
            incident=incidents.get(assignment['incident_id']);technician=technicians.get(assignment['technician_id'])
            check(incident is not None and technician is not None,'Incidente o técnico no encontrado','NOT_FOUND',404)
            check(incident['status']=='open' and technician['availability']=='available','La disponibilidad cambió. Genera otra sugerencia.')
            check(assignment.get('incident_version')==incident.get('version',1) and assignment.get('technician_version')==technician.get('version',1),'Sugerencia desactualizada')
            eligible=suggest([incident],[technician],snapshot['machines'])['assignments']
            check(bool(eligible),'La especialidad o el turno del técnico no son compatibles')
            stamp=now();new_incident=copy.deepcopy(incident);new_technician=copy.deepcopy(technician)
            new_incident.update(status='assigned',technician_id=technician['technician_id'],assigned_at=stamp,assignment=eligible[0])
            new_incident.setdefault('timeline',[]).append({'at':stamp,'type':'assigned','text':f"Asignado a {technician['name']}",'actor':actor})
            new_technician.update(availability='busy',active_incident_id=incident['incident_id'])
            entities += [('incidents',incident,new_incident),('technicians',technician,new_technician)]
            result.append({'incident_id':incident['incident_id'],'technician_id':technician['technician_id']})
        return self._commit(command,{'action':'confirm',**payload},entities,{'assignments':result,'confirmed_at':now()})

    def create_incident(self,alert,command):
        prior=self.port.lookup(command,{'action':'create','alert':alert})
        if prior is not None:return prior
        import hashlib
        snapshot=self.port.snapshot()
        existing=next((i for i in snapshot['incidents'] if i['machine_id']==alert['machine_id'] and i['status']!='closed'),None)
        if existing:return {'incident_id':existing['incident_id']}
        identifier='INC-'+hashlib.sha256(alert['alert_id'].encode()).hexdigest()[:12].upper()
        stamp=now();incident={'incident_id':identifier,'machine_id':alert['machine_id'],'zone_id':alert['zone_id'],
            'opened_at':stamp,'closed_at':None,'status':'open','severity':alert['severity'],'score':alert['score'],
            'suspected_component':alert['suspected_component'],'summary':alert['summary'],'alert_ids':[alert['alert_id']],
            'technician_id':None,'actions':[],'parts_replaced':[],'downtime_minutes':None,'recurrence_of':None,
            'timeline':[{'at':stamp,'type':'opened','text':'Incidente registrado por alerta','actor':'workflow'}]}
        machine=next(m for m in snapshot['machines'] if m['machine_id']==alert['machine_id'])
        return self._commit(command,{'action':'create','alert':alert},[('incidents',None,incident),('machines',machine,{**machine,'active_incident_id':identifier})],{'incident_id':identifier})

    def ack(self,identifier,actor,command):
        request={'action':'ack','incident_id':identifier}
        prior=self.port.lookup(command,request)
        if prior is not None:return prior
        incident=self.get_incident(identifier)
        check(incident['status']=='assigned','El incidente no está asignado')
        value=copy.deepcopy(incident);stamp=now();value['acknowledged_at']=stamp
        value.setdefault('timeline',[]).append({'at':stamp,'type':'acknowledged','text':'Técnico confirmó la recepción','actor':actor})
        return self._commit(command,request,[('incidents',incident,value)],{'incident_id':identifier,'acknowledged_at':stamp})

    def start(self,identifier,actor,command):
        request={'action':'start','incident_id':identifier}
        prior=self.port.lookup(command,request)
        if prior is not None:return prior
        incident=self.get_incident(identifier)
        check(incident['status']=='assigned' and incident.get('acknowledged_at'),'Confirma la recepción antes de iniciar')
        value=copy.deepcopy(incident);stamp=now();value.update(status='in_progress',started_at=stamp)
        value.setdefault('timeline',[]).append({'at':stamp,'type':'started','text':'Intervención iniciada','actor':actor})
        return self._commit(command,request,[('incidents',incident,value)],{'incident_id':identifier,'status':'in_progress'})

    def validate_close(self,identifier,payload):
        snapshot=self.port.snapshot();incident=next((i for i in snapshot['incidents'] if i['incident_id']==identifier),None)
        check(incident is not None,'Incidente no encontrado','NOT_FOUND',404)
        check(incident['status']=='in_progress','Inicia la intervención antes de cerrar')
        actions=payload.get('actions',[])
        check(isinstance(actions,list) and bool(actions) and all(isinstance(a,str) and 3<=len(a.strip())<=1000 for a in actions),'Describe al menos una intervención (3 a 1000 caracteres)','VALIDATION_ERROR',400)
        parts=payload.get('parts_replaced',[])
        check(isinstance(parts,list) and len(parts)<=20,'Hasta 20 repuestos por cierre','VALIDATION_ERROR',400)
        used={};stock={i['key']:i for i in snapshot['inventory']}
        for part in parts:
            qty=part.get('qty');check(type(qty)is int and qty>0,'Las cantidades deben ser enteros positivos','VALIDATION_ERROR',400)
            key=incident['zone_id']+'|'+part['part_id'];used[key]=used.get(key,0)+qty
        for key,qty in used.items():
            check(key in stock and stock[key]['stock']>=qty,'Stock insuficiente. El cierre no descontará parcialmente los repuestos.')
        return snapshot,incident,used

    def close(self,identifier,payload,actor,command):
        request={'action':'close','incident_id':identifier,**payload}
        prior=self.port.lookup(command,request)
        if prior is not None:return prior
        snapshot,incident,used=self.validate_close(identifier,payload);stamp=now();value=copy.deepcopy(incident)
        previous=[i for i in snapshot['incidents'] if i['machine_id']==incident['machine_id'] and i['incident_id']!=identifier and i['status']=='closed' and i.get('suspected_component')==incident.get('suspected_component') and i.get('closed_at') and datetime.fromisoformat(i['closed_at'].replace('Z','+00:00'))>datetime.now(timezone.utc)-timedelta(days=30)]
        value.update(status='closed',closed_at=stamp,actions=payload['actions'],parts_replaced=[{'part_id':k.split('|')[1],'qty':q} for k,q in used.items()],recurrence_of=max(previous,key=lambda i:i['closed_at'])['incident_id'] if previous else None)
        value['resolution_minutes']=round((datetime.fromisoformat(stamp.replace('Z','+00:00'))-datetime.fromisoformat(incident['opened_at'].replace('Z','+00:00'))).total_seconds()/60,2)
        value.setdefault('timeline',[]).append({'at':stamp,'type':'closed','text':'; '.join(payload['actions']),'actor':actor})
        entities=[('incidents',incident,value)];low=[]
        for inventory in snapshot['inventory']:
            if inventory['key'] in used:
                updated={**inventory,'stock':inventory['stock']-used[inventory['key']],'updated_at':stamp}
                entities.append(('inventory',inventory,updated))
                if updated['stock']<updated['min_stock']:low.append(updated)
        for technician in snapshot['technicians']:
            if technician['technician_id']==incident.get('technician_id') and technician.get('active_incident_id')==identifier:
                entities.append(('technicians',technician,{**technician,'availability':'available','active_incident_id':None}))
        machine=next(m for m in snapshot['machines'] if m['machine_id']==incident['machine_id'])
        machine_update={**machine,'active_incident_id':None}
        if payload.get('restore_operation') is True:
            if machine.get('downtime_started_at'):
                value['downtime_minutes']=round((datetime.fromisoformat(stamp.replace('Z','+00:00'))-datetime.fromisoformat(machine['downtime_started_at'].replace('Z','+00:00'))).total_seconds()/60,2)
            machine_update.update(status='operating',downtime_started_at=None)
        entities.append(('machines',machine,machine_update))
        result={'incident_id':identifier,'status':'closed','stock_alerts':low,'recurrence_of':value['recurrence_of']}
        return self._commit(command,request,entities,result)

    def release_for_escalation(self,identifier,command):
        request={'action':'release','incident_id':identifier}
        prior=self.port.lookup(command,request)
        if prior is not None:return prior
        snapshot=self.port.snapshot();incident=next(i for i in snapshot['incidents'] if i['incident_id']==identifier)
        check(incident['status']=='assigned' and not incident.get('acknowledged_at'),'El técnico ya respondió; no reasignar')
        new=copy.deepcopy(incident);new.update(status='open',technician_id=None)
        entities=[('incidents',incident,new)]
        for tech in snapshot['technicians']:
            if tech.get('active_incident_id')==identifier:entities.append(('technicians',tech,{**tech,'availability':'available','active_incident_id':None}))
        return self._commit(command,request,entities,{'incident_id':identifier,'excluded_technician':incident.get('technician_id')})

    def get_incident(self,identifier):
        item=next((i for i in self.port.snapshot()['incidents'] if i['incident_id']==identifier),None)
        check(item is not None,'Incidente no encontrado','NOT_FOUND',404);return item
