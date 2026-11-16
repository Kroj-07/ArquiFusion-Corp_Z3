import importlib
import sys
import types
import unittest
from unittest.mock import patch


class DemoShiftTests(unittest.TestCase):
    def test_renews_only_available_matching_fixtures_without_active_incident(self):
        with patch.dict(sys.modules, {'boto3': types.ModuleType('boto3')}):
            pilot = importlib.import_module('afc.pilot')
        technicians = [
            {'technician_id': 'TEC-0001', 'name': 'Valeria Rojas', 'availability': 'available', 'active_incident_id': None, 'version': 2},
            {'technician_id': 'TEC-0002', 'name': 'Diego Salas', 'availability': 'busy', 'active_incident_id': 'INC-existing', 'version': 4},
            {'technician_id': 'TEC-0003', 'name': 'Otro nombre', 'availability': 'available', 'version': 1},
            {'technician_id': 'TEC-0004', 'name': 'Mateo Flores', 'availability': 'available', 'active_incident_id': 'INC-existing', 'version': 3},
        ]
        commits = []
        svc = types.SimpleNamespace(port=types.SimpleNamespace(snapshot=lambda: {'technicians': technicians}),
                                    ops=types.SimpleNamespace(_commit=lambda *args: commits.append(args)))
        with patch.object(pilot.cloud, 'service', return_value=svc):
            pilot.renew_simulated_shifts('test-command')
        self.assertEqual(len(commits), 1)
        entities = commits[0][2]
        self.assertEqual(len(entities), 1)
        self.assertEqual(entities[0][1]['technician_id'], 'TEC-0001')
        self.assertTrue(entities[0][2]['is_sample'])
        self.assertIn('shift_end', entities[0][2])
        self.assertEqual(technicians[1]['active_incident_id'], 'INC-existing')


if __name__ == '__main__':
    unittest.main()
