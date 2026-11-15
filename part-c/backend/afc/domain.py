import math
from datetime import datetime, timezone

ROLES = ('operator', 'technician', 'maintenance', 'supervisor', 'admin', 'manager')
SEVERITY = {'info': 0, 'low': 1, 'medium': 2, 'high': 3, 'critical': 4}


class Problem(Exception):
    def __init__(self, message, code='VALIDATION_ERROR', status=400):
        super().__init__(message)
        self.code, self.status = code, status


def now():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def distance(a, b):
    lat1, lat2 = math.radians(a['lat']), math.radians(b['lat'])
    h = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(math.radians(b['lon']-a['lon'])/2)**2
    return 6371*2*math.asin(min(1, math.sqrt(h)))


def check(condition, message, code='CONFLICT', status=409):
    if not condition:
        raise Problem(message, code, status)


def visible_machine(principal, machine):
    role = principal['role']
    if role in ('manager', 'admin'):
        return True
    if role == 'operator':
        return machine['machine_id'] in principal.get('machine_ids', [])
    return machine.get('zone_id') in principal.get('zone_ids', [])


def visible_incident(principal, incident, machines):
    if principal['role'] == 'technician':
        return incident.get('technician_id') == principal.get('technician_id')
    machine = next((m for m in machines if m['machine_id'] == incident['machine_id']), None)
    return machine is not None and visible_machine(principal, machine)


def require_role(principal, *roles):
    check(principal['role'] in roles, 'Tu rol no permite esta acción', 'FORBIDDEN', 403)


def claims_principal(claims):
    raw = claims.get('cognito:groups', claims.get('role', ''))
    if isinstance(raw, str):
        import json
        try:
            raw = json.loads(raw) if raw.startswith('[') else raw.replace('[', '').replace(']', '').split(',')
        except ValueError:
            raw = []
    groups = [r.strip().strip('"') for r in raw]
    role = next((r for r in ('admin','maintenance','supervisor','technician','operator','manager') if r in groups), None)
    check(role is not None and claims.get('sub'), 'Sesión sin rol autorizado', 'FORBIDDEN', 403)
    return {'sub': claims['sub'], 'role': role, 'name': claims.get('name', claims.get('username', role)),
            'zone_ids': [v.strip() for v in claims.get('custom:zone_ids', '').split(',') if v.strip()],
            'machine_ids': [v.strip() for v in claims.get('custom:machine_ids', '').split(',') if v.strip()],
            'technician_id': claims.get('custom:technician_id')}


def notification_targets(alert, incident=None):
    level = SEVERITY.get(alert['severity'], 0)
    targets = []
    zone, machine = alert['zone_id'], alert['machine_id']
    if level >= 2:
        targets += [('operator', machine, 'immediate'), ('maintenance', zone, 'immediate' if level >= 3 else 'hourly')]
    if level>=2 and incident and incident.get('technician_id'):
        targets += [('technician', incident['technician_id'], 'immediate')]
    if level >= 3:
        targets += [('supervisor', zone, 'immediate')]
    if level >= 4:
        targets += [('admin', 'all', 'immediate')]
        if len(alert.get('related_machine_ids', [])) >= 2:
            targets += [('manager', 'all', 'immediate')]
    return targets


def notification_text(alert, role):
    if role in ('manager','admin'):
        return f"{alert['machine_id']}: incidente {alert['severity']}. Revisar impacto en disponibilidad de la operación."
    if role == 'operator':
        return f"{alert['machine_id']}: {alert['summary']} Acción: {alert['recommended_action']}."
    return f"{alert['machine_id']} · {alert['suspected_component']}. {alert['summary']}"
