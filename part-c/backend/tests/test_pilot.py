import base64
import hashlib
import hmac
import json
import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from afc.pilot import verify_token,validate_reading,rule_alert,ingest_handler,secret
from afc.domain import Problem


class PilotTests(unittest.TestCase):
    def jwt(self, **overrides):
        encode=lambda data:base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip('=')
        claims={'iss':'arquifusion-pilot','aud':'arquifusion-web','sub':'admin-1','role':'admin','exp':int(time.time())+3600,**overrides}
        text=encode({'alg':'HS256'})+'.'+encode(claims)
        return text+'.'+base64.urlsafe_b64encode(hmac.new(b'test-secret',text.encode(),hashlib.sha256).digest()).decode().rstrip('=')

    def reading(self):
        return {'machine_id':'MCH-000001','timestamp':'2026-11-15T23:00:00.000Z','status':'operating','metrics':{'engine_temp_c':112.0,'vibration_mm_s':6.8,'pressure_bar':6.0,'fuel_rate_lph':38.0}}

    def test_signed_token_does_not_accept_expired_or_other_audience(self):
        self.assertEqual(verify_token(self.jwt(),'test-secret')['role'],'admin')
        for value in (self.jwt(exp=1),self.jwt(aud='other'),self.jwt()+'x'):
            with self.assertRaises(Problem):verify_token(value,'test-secret')

    def test_bad_sensor_cannot_become_an_alert(self):
        reading=self.reading();reading['metrics']['engine_temp_c']=float('nan')
        with self.assertRaises(Problem):validate_reading(reading)

    def test_multivariable_rule_is_explicit_and_idempotent(self):
        reading=self.reading();machine={'zone_id':'ZONE'}
        alert=rule_alert(reading,machine)
        self.assertEqual(alert['alert_id'],rule_alert(reading,machine)['alert_id'])
        self.assertEqual(alert['detection_method'],'deterministic_rule')
        reading['metrics']['vibration_mm_s']=2
        self.assertIsNone(rule_alert(reading,machine))

    def test_replayed_sqs_message_has_one_alert_and_one_event(self):
        from moto import mock_aws
        import boto3
        with mock_aws(),patch.dict(os.environ,{'AWS_DEFAULT_REGION':'us-east-1','MACHINES_TABLE':'machines','TELEMETRY_TABLE':'telemetry','ALERTS_TABLE':'alerts','DATA_BUCKET':'pilot-test-data','EVENT_BUS':'pilot-test-events'}):
            db=boto3.resource('dynamodb')
            for name,keys in [('machines',['machine_id']),('telemetry',['machine_id','timestamp']),('alerts',['machine_id','created_at'])]:
                db.create_table(TableName=name,BillingMode='PAY_PER_REQUEST',AttributeDefinitions=[{'AttributeName':k,'AttributeType':'S'} for k in keys],KeySchema=[{'AttributeName':k,'KeyType':'HASH' if i==0 else 'RANGE'} for i,k in enumerate(keys)])
            db.Table('machines').put_item(Item={'machine_id':'MCH-000001','zone_id':'ZONE','version':1})
            boto3.client('s3').create_bucket(Bucket='pilot-test-data')
            events=boto3.client('events');events.create_event_bus(Name='pilot-test-events')
            message={'Records':[{'messageId':'msg-1','body':json.dumps(self.reading())}]}
            original_client=boto3.client
            with patch('afc.pilot.boto3.client',side_effect=lambda name,**kwargs:events if name=='events' else original_client(name,**kwargs)):
                with patch.object(events,'put_events',wraps=events.put_events) as put:
                    self.assertEqual(ingest_handler(message,None),{'batchItemFailures':[]})
                    self.assertEqual(ingest_handler(message,None),{'batchItemFailures':[]})
                    self.assertEqual(put.call_count,1)
            self.assertEqual(db.Table('alerts').scan()['Count'],1)
            self.assertEqual(db.Table('telemetry').scan()['Count'],1)
            self.assertTrue(db.Table('alerts').scan()['Items'][0]['event_published'])

    def test_backup_restores_the_same_bytes_and_detects_corruption(self):
        from moto import mock_aws
        import boto3
        from afc import pilot_backup
        with mock_aws(),patch.dict(os.environ,{'AWS_DEFAULT_REGION':'us-east-1','DATA_BUCKET':'pilot-source-test'}):
            client=boto3.client('s3')
            for bucket in ('pilot-source-test','pilot-b2-test'):client.create_bucket(Bucket=bucket)
            with patch.object(pilot_backup,'b2_client',return_value=(client,'pilot-b2-test')),patch.object(pilot_backup,'catalog',return_value=[]):
                copied=pilot_backup.handler({'action':'backup'},None)
                restored=pilot_backup.handler(copied,None)
                self.assertTrue(restored['restored_verified'])
                client.put_object(Bucket='pilot-b2-test',Key=copied['key'],Body=b'corrupted')
                with self.assertRaises(Problem):pilot_backup.handler(copied,None)


if __name__=='__main__':unittest.main()
