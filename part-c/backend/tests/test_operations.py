import copy
import itertools
import json
import random
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone,timedelta
from afc.assignment import hungarian,suggest
from afc.domain import Problem,claims_principal
from afc.local import create_service,principal
from afc.operations import Operations


class AssignmentTests(unittest.TestCase):
    def test_hungarian_matches_exhaustive_solution(self):
        rng=random.Random(17)
        for _ in range(20):
            matrix=[[rng.randrange(100) for _ in range(5)] for _ in range(3)]
            result=sum(matrix[i][j] for i,j in hungarian(matrix))
            optimum=min(sum(matrix[i][p[i]] for i in range(3)) for p in itertools.permutations(range(5),3))
            self.assertEqual(result,optimum)

    def test_no_wrong_skill_busy_or_short_shift(self):
        machines=[{'machine_id':'M1','location':{'lat':0,'lon':0}}]
        incidents=[{'incident_id':'I1','machine_id':'M1','severity':'critical','suspected_component':'cooling_system'}]
        common={'location':{'lat':0,'lon':0},'skills':['engine'],'availability':'available','technician_id':'T'}
        for tech in ({**common,'availability':'busy'},{**common,'skills':['hydraulics']},
                     {**common,'shift_end':datetime.now(timezone.utc).isoformat().replace('+00:00','Z')}):
            result=suggest(incidents,[tech],machines,engine='python')
            self.assertEqual(result['assignments'],[]);self.assertEqual(len(result['unassigned']),1)

    def test_global_assignment_preserves_rare_specialist(self):
        machines=[{'machine_id':'M1','location':{'lat':0,'lon':0}},{'machine_id':'M2','location':{'lat':0,'lon':0}}]
        incidents=[{'incident_id':'I1','machine_id':'M1','severity':'high','suspected_component':'engine'},
                   {'incident_id':'I2','machine_id':'M2','severity':'high','suspected_component':'hydraulics'}]
        tech=[{'technician_id':'BOTH','skills':['engine','hydraulics'],'availability':'available','location':{'lat':0,'lon':0}},
              {'technician_id':'ENGINE','skills':['engine'],'availability':'available','location':{'lat':.01,'lon':0}}]
        result=suggest(incidents,tech,machines,engine='python')
        self.assertEqual(len(result['assignments']),2)
        self.assertEqual(next(a['technician_id'] for a in result['assignments'] if a['incident_id']=='I2'),'BOTH')


class FlowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.service=create_service(self.temp.name+'/db.sqlite');self.actor=principal('maintenance')
    def tearDown(self):self.service.port.db.close();self.temp.cleanup()
    def request(self,path,body=None,key='test',actor=None):return self.service.route('POST',path,body or {},actor or self.actor,key)
    def assign(self,identifier='INC-000001'):
        proposed=self.request('/v1/assignments/suggest',{'incident_ids':[identifier]})
        self.request('/v1/assignments/confirm',{'assignments':proposed['assignments']},'confirm-'+identifier)
        return identifier
    def begin(self,identifier='INC-000001'):
        self.assign(identifier);self.request(f'/v1/incidents/{identifier}/ack',key='ack-'+identifier)
        self.request(f'/v1/incidents/{identifier}/start',key='start-'+identifier);return identifier

    def test_lifecycle_and_stock_close_are_atomic_and_idempotent(self):
        identifier=self.begin();before=next(i['stock'] for i in self.service.port.snapshot()['inventory'] if i['key']=='ZONA-NORTE-02|PRT-0001')
        body={'actions':['Revisión y reemplazo documentado'],'parts_replaced':[{'part_id':'PRT-0001','qty':1}],'restore_operation':True}
        result=self.request(f'/v1/incidents/{identifier}/close',body,'close-once')
        again=self.request(f'/v1/incidents/{identifier}/close',body,'close-once')
        snapshot=self.service.port.snapshot();item=self.service.ops.get_incident(identifier)
        self.assertTrue(result['accepted']);self.assertTrue(again['duplicate']);self.assertEqual(item['status'],'closed')
        self.assertEqual(next(i['stock'] for i in snapshot['inventory'] if i['key']=='ZONA-NORTE-02|PRT-0001'),before-1)
        self.assertEqual(next(t['availability'] for t in snapshot['technicians'] if t['technician_id']==item['technician_id']),'available')

    def test_insufficient_stock_does_not_partially_close(self):
        identifier=self.begin();before=self.service.port.snapshot()
        with self.assertRaises(Problem):self.request(f'/v1/incidents/{identifier}/close',{'actions':['Inspección completa'],'parts_replaced':[{'part_id':'PRT-0001','qty':1},{'part_id':'PRT-0002','qty':999}]},'insufficient')
        after=self.service.port.snapshot();self.assertEqual(before['inventory'],after['inventory']);self.assertEqual(self.service.ops.get_incident(identifier)['status'],'in_progress')

    def test_stale_suggestion_rejected_without_double_booking(self):
        proposed=self.request('/v1/assignments/suggest',{'incident_ids':['INC-000001']})
        payload={'assignments':proposed['assignments']};self.request('/v1/assignments/confirm',payload,'first')
        with self.assertRaises(Problem):self.request('/v1/assignments/confirm',payload,'different-command')
        repeated=self.request('/v1/assignments/confirm',payload,'first');self.assertEqual(len(repeated['assignments']),1)

    def test_concurrent_assignment_only_one_reserves_technician(self):
        # Two callers submit the same valid version concurrently.
        proposed=self.request('/v1/assignments/suggest',{'incident_ids':['INC-000001']});payload={'assignments':proposed['assignments']}
        gate=threading.Barrier(2)
        def attempt(i):
            gate.wait()
            try:self.service.ops.confirm(payload,'race-'+str(i),'test');return True
            except Problem:return False
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(attempt,[1,2]))
        self.assertEqual(results.count(True),1)

    def test_callback_tokens_never_leave_bootstrap(self):
        result=self.service.bootstrap(self.actor)
        self.assertNotIn('demo-ack',json.dumps(result));self.assertNotIn('task_token',json.dumps(result))

    def test_expired_callback_rejected(self):
        identifier=self.assign();key=f'TOKEN#{identifier}#ack';record=self.service.state.state_get(key);record['expires_at']=0;self.service.state.state_put(key,record)
        with self.assertRaises(Problem):self.request(f'/v1/incidents/{identifier}/ack',key='expired')
        self.assertNotIn('acknowledged_at',self.service.ops.get_incident(identifier))

    def test_operator_cannot_assign_or_close_another_machine(self):
        with self.assertRaises(Problem):self.request('/v1/assignments/suggest',{'incident_ids':['INC-000001']},actor=principal('operator'))
        data=self.service.bootstrap(principal('operator'));self.assertEqual([m['machine_id'] for m in data['machines']],['MCH-000001'])
        self.assertEqual(data['inventory'],[])
        with self.assertRaises(Problem):self.request('/v1/incidents/INC-000004/ack',actor=principal('operator'))

    def test_technician_only_sees_own_incidents(self):
        data=self.service.bootstrap(principal('technician'))
        self.assertTrue(data['incidents']);self.assertTrue(all(i['technician_id']=='TEC-0003' for i in data['incidents']))
        self.assertTrue(all(m['machine_id'] in {i['machine_id'] for i in data['incidents']} for m in data['machines']))

    def test_notify_replay_has_one_inbox_entry_per_role_scope(self):
        alert=self.service.port.snapshot()['alerts'][0]
        before=len(self.service.state.states('NOTICE#'));self.service.notify(alert);self.service.notify(alert)
        self.assertEqual(len(self.service.state.states('NOTICE#')),before)

    def test_live_missing_b_never_returns_demo_results(self):
        self.service.mode='live';result=self.service.analytics(self.actor)
        self.assertFalse(result['available']);self.assertEqual(result['provenance'],'unavailable')

    def test_claims_require_role_and_subject(self):
        with self.assertRaises(Problem):claims_principal({'sub':'x','role':'unknown'})
        with self.assertRaises(Problem):claims_principal({'role':'admin'})
        self.assertEqual(claims_principal({'sub':'x','cognito:groups':'["technician"]'})['role'],'technician')

if __name__=='__main__':unittest.main()
