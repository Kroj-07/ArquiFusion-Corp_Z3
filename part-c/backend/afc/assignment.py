"""Asignación global con restricciones duras; SciPy opcional y Hungarian puro como respaldo."""
from datetime import datetime, timezone
from .domain import distance, SEVERITY

SKILLS = {'cooling_system': 'engine', 'injectors': 'engine', 'engine': 'engine',
          'hydraulic_system': 'hydraulics', 'hydraulics': 'hydraulics',
          'bearing': 'mechanical', 'electrical_system': 'electrical'}


def hungarian(cost):
    if not cost:
        return []
    n, m = len(cost), len(cost[0])
    assert n <= m
    u, v, p, way = [0.]*(n+1), [0.]*(m+1), [0]*(m+1), [0]*(m+1)
    for i in range(1, n+1):
        p[0], j0 = i, 0
        mins, used = [float('inf')]*(m+1), [False]*(m+1)
        while True:
            used[j0] = True
            i0, delta, j1 = p[j0], float('inf'), 0
            for j in range(1,m+1):
                if not used[j]:
                    cur = cost[i0-1][j-1]-u[i0]-v[j]
                    if cur < mins[j]:
                        mins[j], way[j] = cur, j0
                    if mins[j] < delta:
                        delta,j1=mins[j],j
            for j in range(m+1):
                if used[j]:
                    u[p[j]]+=delta; v[j]-=delta
                else:
                    mins[j]-=delta
            j0=j1
            if p[j0]==0:
                break
        while j0:
            j1=way[j0];p[j0]=p[j1];j0=j1
    return sorted([(p[j]-1,j-1) for j in range(1,m+1) if p[j]], key=lambda x:x[0])


def suggest(incidents, technicians, machines, excluded=None, engine='auto', current_time=None):
    current_time = current_time or datetime.now(timezone.utc)
    excluded = set(excluded or [])
    machine_map = {m['machine_id']:m for m in machines}
    available = [t for t in technicians if t['availability']=='available' and t['technician_id'] not in excluded]
    matrix, details = [], {}
    for i, incident in enumerate(incidents):
        machine=machine_map.get(incident['machine_id'])
        row=[]
        for j, technician in enumerate(available):
            skill=SKILLS.get(incident.get('suspected_component'), incident.get('suspected_component'))
            km=distance(machine['location'],technician['location']) if machine else float('inf')
            eta=math_ceil(km/25*60+10) if machine else 100000
            shift=technician.get('shift_end')
            remaining=(datetime.fromisoformat(shift.replace('Z','+00:00'))-current_time).total_seconds()/60 if shift else 100000
            eligible=machine and skill in technician['skills'] and eta+60<=remaining
            level=SEVERITY.get(incident['severity'],2)
            row.append(eta*(1+level) if eligible else 1e12)
            details[i,j]={'eta_minutes':eta,'distance_km':round(km,2) if machine else None,'skill':skill}
        row += [1e6+SEVERITY.get(incident['severity'],2)*1e5]*len(incidents)
        matrix.append(row)
    if not matrix:
        return {'assignments':[],'unassigned':[],'engine':'hungarian','total_cost':0}
    used_engine='hungarian-python'
    if engine=='greedy':
        pairs=[]; used=set()
        for i in sorted(range(len(incidents)),key=lambda i:-SEVERITY.get(incidents[i]['severity'],0)):
            options=[j for j in range(len(matrix[i])) if j not in used]
            j=min(options,key=lambda j:matrix[i][j]);used.add(j);pairs.append((i,j))
        used_engine='greedy'
    else:
        try:
            if engine=='python':raise ImportError
            from scipy.optimize import linear_sum_assignment
            ri,cj=linear_sum_assignment(matrix);pairs=list(zip(ri,cj));used_engine='scipy-linear_sum_assignment'
        except ImportError:
            pairs=hungarian(matrix)
    assignments=[];unassigned=[]
    for i,j in pairs:
        incident=incidents[i]
        if j>=len(available) or matrix[i][j]>=1e12:
            unassigned.append({'incident_id':incident['incident_id'],'reason':'Sin especialista disponible que pueda completar la atención dentro de su turno'})
        else:
            technician=available[j];detail=details[i,j]
            assignments.append({'incident_id':incident['incident_id'],'technician_id':technician['technician_id'],
                **detail,'score':round(1/(1+detail['eta_minutes']/60),3),
                'incident_version':incident.get('version',1),'technician_version':technician.get('version',1),
                'reason':f"Especialidad {detail['skill']}, a {detail['distance_km']} km, disponible. ETA estimada a 25 km/h + 10 min de preparación."})
    return {'assignments':assignments,'unassigned':unassigned,'engine':used_engine,
            'total_cost':sum(matrix[i][j] for i,j in pairs),'score_note':'Score operativo de cercanía; no probabilidad ni confianza del modelo.'}


def math_ceil(value):
    import math
    return math.ceil(value)
