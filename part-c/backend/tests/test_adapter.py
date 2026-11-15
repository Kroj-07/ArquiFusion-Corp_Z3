import json
import os
import unittest
from unittest.mock import patch
try:
    import boto3
    from moto import mock_aws
except ImportError:raise unittest.SkipTest('Pruebas DynamoDB: instalar requirements-dev.txt')
from afc import a_adapter
from afc.seed import seed
from afc.operations import Operations
from afc.domain import Problem

class AdapterPort:
    def call(self,event):
        result=a_adapter.handler(event,None)
        if 'error'in result:raise Problem(result['error']['message'],result['error']['code'],result['error']['status'])
        return result['data']
    def snapshot(self):return self.call({'op':'snapshot'})
    def lookup(self,key,request):return self.call({'op':'lookup','command_id':key,'request':request})
    def commit(self,key,expected,changes,result,request=None):return self.call({'op':'commit','command_id':key,'expected':expected,'changes':changes,'result':result,'request':request})

class DynamoAdapterTests(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,{'AWS_DEFAULT_REGION':'us-east-1','AWS_ACCESS_KEY_ID':'testing','AWS_SECRET_ACCESS_KEY':'testing','AWS_SESSION_TOKEN':'testing'})
        self.env.start();self.mock=mock_aws();self.mock.start();client=boto3.client('dynamodb');sample=seed()
        for kind,keys in a_adapter.KEYS.items():
            name='af-test-'+kind;os.environ[a_adapter.ENV[kind]]=name
            client.create_table(TableName=name,KeySchema=[{'AttributeName':k,'KeyType':'HASH' if n==0 else 'RANGE'} for n,k in enumerate(keys)],AttributeDefinitions=[{'AttributeName':k,'AttributeType':'S'} for k in keys],BillingMode='PAY_PER_REQUEST')
            for item in sample[kind]:client.put_item(TableName=name,Item=a_adapter.serial(item))
        os.environ['C_COMMANDS_TABLE']='af-commands'
        client.create_table(TableName='af-commands',KeySchema=[{'AttributeName':'pk','KeyType':'HASH'},{'AttributeName':'sk','KeyType':'RANGE'}],AttributeDefinitions=[{'AttributeName':'pk','AttributeType':'S'},{'AttributeName':'sk','AttributeType':'S'}],BillingMode='PAY_PER_REQUEST')
        self.port=AdapterPort();self.ops=Operations(self.port)
    def tearDown(self):self.mock.stop();self.env.stop()

    def test_reservation_and_marker_are_same_transaction(self):
        proposed=self.ops.suggestions(['INC-000001']);payload={'assignments':proposed['assignments']}
        first=self.ops.confirm(payload,'reserve-17','user');again=self.ops.confirm(payload,'reserve-17','user')
        self.assertEqual(first,again);snapshot=self.port.snapshot();identifier=first['assignments'][0]['technician_id']
        self.assertEqual(next(t['availability'] for t in snapshot['technicians'] if t['technician_id']==identifier),'busy')
        with self.assertRaises(Problem):self.ops.confirm(payload,'reserve-different','user')

    def test_real_dynamo_adapter_closes_and_decrements_once(self):
        proposed=self.ops.suggestions(['INC-000001']);self.ops.confirm({'assignments':proposed['assignments']},'reserve','user')
        self.ops.ack('INC-000001','user','ack');self.ops.start('INC-000001','user','start')
        payload={'actions':['Revisión completa documentada'],'parts_replaced':[{'part_id':'PRT-0001','qty':1}],'restore_operation':True}
        self.ops.close('INC-000001',payload,'user','close');self.ops.close('INC-000001',payload,'user','close')
        stock=next(i for i in self.port.snapshot()['inventory'] if i['key']=='ZONA-NORTE-02|PRT-0001')
        self.assertEqual(stock['stock'],3);self.assertEqual(self.ops.get_incident('INC-000001')['status'],'closed')

    def test_failed_condition_does_not_write_marker_or_partial_item(self):
        old=self.port.snapshot()['inventory'][0];changed={**old,'stock':0,'version':old['version']+1}
        request={'action':'test-conflict'}
        with self.assertRaises(Problem):self.port.commit('bad-version',[{'kind':'inventory','id':old['key'],'version':999}],
            [{'kind':'inventory','id':old['key'],'value':changed}],{'ok':True},request)
        self.assertIsNone(self.port.lookup('bad-version',request));after=next(i for i in self.port.snapshot()['inventory'] if i['key']==old['key']);self.assertEqual(after['stock'],old['stock'])

    def test_unauthenticated_gateway_does_not_trust_demo_header(self):
        from afc.cloud import api_handler
        result=api_handler({'headers':{'x-demo-role':'admin'},'rawPath':'/v1/bootstrap','requestContext':{'http':{'method':'GET'}}},None)
        self.assertEqual(result['statusCode'],401)

if __name__=='__main__':unittest.main()
