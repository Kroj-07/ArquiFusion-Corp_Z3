import math
import random
from datetime import datetime,timedelta,timezone


def seed():
    rng=random.Random(17);stamp=datetime.now(timezone.utc)
    iso=lambda value:value.isoformat(timespec='milliseconds').replace('+00:00','Z')
    zones=['ZONA-NORTE-02','ZONA-CENTRO-01','ZONA-SUR-03'];types=['excavator','truck','loader']
    machines=[];telemetry=[]
    for n in range(1,25):
        zone=zones[(n-1)//8];lat=-12.068+((n-1)//8)*.025+(n%4)*.004;lon=-76.955+(n%8)*.005
        status='operating'
        if n in (2,9,17):status='idle'
        if n in (1,6):status='fault'
        if n==4:status='maintenance'
        machine={'machine_id':f'MCH-{n:06d}','name':f'{["Excavadora","Camión","Cargador"][(n-1)%3]} {n:02d}',
                 'model':['EX-320','TR-785','LD-950'][(n-1)%3],'type':types[(n-1)%3],'sector':'mining','zone_id':zone,
                 'status':status,'last_seen':iso(stamp),'location':{'lat':lat,'lon':lon},'operating_hours_total':3200+n*132,
                 'last_maintenance_at':iso(stamp-timedelta(days=10+n)), 'version':1,
                 'downtime_started_at':iso(stamp-timedelta(minutes=40+n)) if status in ('fault','maintenance') else None}
        series=[]
        for tick in range(24):
            temp=85+rng.uniform(-2,2)+(tick*.8 if n in (1,4,6) else 0)
            series.append({'timestamp':iso(stamp-timedelta(minutes=(23-tick)*10)),
              'metrics':{'engine_temp_c':round(temp,1),'vibration_mm_s':round(3+rng.uniform(-.3,.3)+(tick*.09 if n in(1,6) else 0),2),
                         'pressure_bar':round(6.1+rng.uniform(-.2,.2)-(tick*.045 if n==4 else 0),2),
                         'fuel_rate_lph':round(27+rng.uniform(-1,1)+(tick*.3 if n in(1,6) else 0),1),
                         'load_kg':rng.randint(8000,20000),'speed_kmh':rng.randint(3,20),'engine_rpm':rng.randint(1400,2100),
                         'operating_hours_total':machine['operating_hours_total']}})
        machine['metrics']=series[-1]['metrics'];machine['risk_score']=96 if n==1 else (83 if n==6 else (72 if n==4 else rng.randint(8,48)))
        machines.append(machine);telemetry.append({'key':machine['machine_id'],'machine_id':machine['machine_id'],'readings':series,'version':1})
    technicians=[]
    for n,(name,skills,zone) in enumerate([('Valeria Rojas',['engine','mechanical'],zones[0]),('Diego Salas',['hydraulics'],zones[0]),
         ('Lucía Torres',['engine'],zones[1]),('Mateo Flores',['electrical','mechanical'],zones[1]),('Ana Paredes',['hydraulics','engine'],zones[2]),
         ('Bruno Vega',['mechanical'],zones[2]),('Camila León',['engine','hydraulics'],zones[0]),('Andrés Díaz',['electrical'],zones[2])],1):
        machine=next(m for m in machines if m['zone_id']==zone)
        technicians.append({'technician_id':f'TEC-{n:04d}','name':name,'skills':skills,'zone_id':zone,
            'location':{'lat':machine['location']['lat']+.002*n,'lon':machine['location']['lon']-.003},
            'availability':'available','shift_end':iso(stamp+timedelta(hours=8)),'active_incident_id':None,'version':1})
    alerts=[];kinds=['predictive_failure','anomaly','fuel_drift','low_utilization','overuse','common_cause','maintenance_due']
    for n in range(1,21):
        machine=machines[(n-1)%24];level=['critical','high','medium','low','info'][(n-1)%5];score={'critical':96,'high':83,'medium':67,'low':38,'info':18}[level]
        alerts.append({'schema_version':'1.0','alert_id':f'ALT-{n:06d}','machine_id':machine['machine_id'],'zone_id':machine['zone_id'],
            'created_at':iso(stamp-timedelta(minutes=n*3)),'type':kinds[(n-1)%7],'severity':level,'score':score,'confidence':None,
            'summary':['Temperatura y vibración en aumento sostenido','Caída de presión respecto al historial','Consumo elevado para la carga transportada'][(n-1)%3],
            'suspected_component':['cooling_system','hydraulic_system','bearing'][(n-1)%3],
            'recommended_action':'stop_and_inspect_now' if level=='critical' else ('inspect_within_24h' if level=='high' else 'monitor'),
            'evidence':[{'metric':'engine_temp_c','observed':machine['metrics']['engine_temp_c'],'expected':85,'window':'4h','trend':'rising'},
                        {'metric':'vibration_mm_s','observed':machine['metrics']['vibration_mm_s'],'expected':3,'window':'4h','trend':'rising'}],
            'related_machine_ids':['MCH-000001','MCH-000004','MCH-000006'] if n==6 else [],'version':1})
    incidents=[]
    for n,machine_id in enumerate((1,4,6,10,17,21),1):
        machine=machines[machine_id-1];alert=alerts[(n-1)%len(alerts)];status='open' if n<=3 else ('assigned' if n<=5 else 'in_progress')
        tech=technicians[n-4] if n>=4 else None
        identifier=f'INC-{n:06d}';opened=iso(stamp-timedelta(minutes=50-n*3))
        incident={'incident_id':identifier,'machine_id':machine['machine_id'],'zone_id':machine['zone_id'],'opened_at':opened,'closed_at':None,
            'status':status,'severity':'critical' if n==1 else ('high' if n in(2,3) else 'medium'),'score':machine['risk_score'],
            'summary':alert['summary'],'suspected_component':['cooling_system','hydraulic_system','bearing','cooling_system','hydraulic_system','cooling_system'][n-1],
            'technician_id':tech['technician_id'] if tech else None,'actions':[],'parts_replaced':[],'downtime_minutes':None,
            'recurrence_of':None,'alert_ids':[alert['alert_id']],'version':1,
            'timeline':[{'at':opened,'type':'opened','text':'Alerta detectada: revisar variables combinadas','actor':'demo'}]}
        if tech:
            tech.update(availability='busy',active_incident_id=identifier)
            incident['timeline'].append({'at':iso(stamp-timedelta(minutes=20)),'type':'assigned','text':f'Asignado a {tech["name"]}','actor':'demo'})
        if status=='in_progress':
            incident['acknowledged_at']=iso(stamp-timedelta(minutes=18));incident['started_at']=iso(stamp-timedelta(minutes=15))
            incident['timeline'] += [{'at':incident['acknowledged_at'],'type':'acknowledged','text':'Técnico confirmó la recepción','actor':'demo'},{'at':incident['started_at'],'type':'started','text':'Intervención iniciada','actor':'demo'}]
        incidents.append(incident)
    inventory=[]
    for zone in zones:
        for n,(name,component,stock,minimum) in enumerate([('Kit de enfriamiento','cooling_system',4,3),('Filtro hidráulico','hydraulic_system',2,4),('Rodamiento industrial','bearing',6,3),('Sensor de presión','hydraulic_system',1,2),('Inyector','injectors',5,2),('Arnés eléctrico','electrical_system',3,2)],1):
            part_id=f'PRT-{n:04d}';inventory.append({'key':zone+'|'+part_id,'zone_id':zone,'part_id':part_id,'name':name,
                'component':component,'stock':stock,'min_stock':minimum,'updated_at':iso(stamp),'version':1})
    return {'machines':machines,'alerts':alerts,'incidents':incidents,'technicians':technicians,'inventory':inventory,'telemetry':telemetry}
