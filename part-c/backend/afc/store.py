import copy
import hashlib
import json
import sqlite3
import threading
from pathlib import Path
from .domain import Problem, check

COLLECTIONS=('machines','alerts','incidents','technicians','inventory','telemetry')
IDS={'machines':'machine_id','alerts':'alert_id','incidents':'incident_id','technicians':'technician_id','inventory':'key','telemetry':'key'}


class SQLitePort:
    """Sustituto local de los datos de A, con transacciones reales de SQLite."""
    def __init__(self,path):
        Path(path).parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(path,check_same_thread=False,isolation_level=None)
        self.lock=threading.RLock()
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('CREATE TABLE IF NOT EXISTS entities(kind TEXT,id TEXT,payload TEXT,PRIMARY KEY(kind,id)); CREATE TABLE IF NOT EXISTS commands(id TEXT PRIMARY KEY,digest TEXT,result TEXT); CREATE TABLE IF NOT EXISTS coordination(id TEXT PRIMARY KEY,payload TEXT);')

    def snapshot(self):
        with self.lock:
            result={kind:[] for kind in COLLECTIONS}
            for kind,payload in self.db.execute('SELECT kind,payload FROM entities'):
                if kind in result:result[kind].append(json.loads(payload))
            return result

    def telemetry(self,identifier):
        return next((t['readings'] for t in self.snapshot()['telemetry'] if t['machine_id']==identifier),[])

    def command_result(self,command_id,digest):
        row=self.db.execute('SELECT digest,result FROM commands WHERE id=?',(command_id,)).fetchone()
        if row:
            check(row[0]==digest,'Idempotency-Key reutilizada con otro contenido')
            return json.loads(row[1])

    def lookup(self,command_id,request):
        digest=hashlib.sha256(json.dumps(request,sort_keys=True).encode()).hexdigest()
        with self.lock:return self.command_result(command_id,digest)

    def commit(self,command_id,expected,changes,result,request=None):
        digest=hashlib.sha256(json.dumps(request if request is not None else changes,sort_keys=True).encode()).hexdigest()
        with self.lock:
            prior=self.command_result(command_id,digest)
            if prior is not None:return prior
            self.db.execute('BEGIN IMMEDIATE')
            try:
                for condition in expected:
                    row=self.db.execute('SELECT payload FROM entities WHERE kind=? AND id=?',(condition['kind'],condition['id'])).fetchone()
                    version=json.loads(row[0]).get('version',1) if row else None
                    check(version==condition['version'],'El estado cambió. Actualiza los datos y vuelve a sugerir.')
                for change in changes:
                    value=copy.deepcopy(change['value'])
                    self.db.execute('INSERT OR REPLACE INTO entities VALUES (?,?,?)',(change['kind'],change['id'],json.dumps(value)))
                self.db.execute('INSERT INTO commands VALUES (?,?,?)',(command_id,digest,json.dumps(result)))
                self.db.execute('COMMIT')
            except Exception:
                self.db.execute('ROLLBACK');raise
        return result

    def seed(self, snapshot):
        with self.lock:
            if self.db.execute('SELECT count(*) FROM entities').fetchone()[0]:return
            for kind,items in snapshot.items():
                for item in items:
                    self.db.execute('INSERT INTO entities VALUES (?,?,?)',(kind,item[IDS[kind]],json.dumps(item)))

    def state_get(self,key):
        with self.lock:
            row=self.db.execute('SELECT payload FROM coordination WHERE id=?',(key,)).fetchone()
            return json.loads(row[0]) if row else None

    def state_put(self,key,value,only_new=False):
        with self.lock:
            if only_new and self.state_get(key):return False
            self.db.execute('INSERT OR REPLACE INTO coordination VALUES (?,?)',(key,json.dumps(value)))
            return True

    def states(self,prefix):
        with self.lock:
            return [json.loads(r[0]) for r in self.db.execute('SELECT payload FROM coordination WHERE id LIKE ?',(prefix+'%',))]


class LambdaPort:
    """El adaptador de A conserva la propiedad de sus tablas y escribe todo o nada."""
    def __init__(self,arn):
        self.arn=arn

    def call(self,payload):
        import boto3
        response=boto3.client('lambda').invoke(FunctionName=self.arn,Payload=json.dumps(payload).encode())
        output=json.loads(response['Payload'].read())
        if response.get('FunctionError') or output.get('error'):
            error=output.get('error',{});raise Problem(error.get('message','Error del adaptador A'),error.get('code','UPSTREAM_ERROR'),error.get('status',502))
        return output.get('data',output)

    def snapshot(self):
        result=self.call({'op':'snapshot','contract_version':'c-1'})
        for kind in COLLECTIONS:result.setdefault(kind,[])
        return result

    def telemetry(self,identifier):return self.call({'op':'telemetry','machine_id':identifier})

    def lookup(self,command_id,request):
        return self.call({'op':'lookup','command_id':command_id,'request':request})

    def commit(self,command_id,expected,changes,result,request=None):
        return self.call({'op':'commit','contract_version':'c-1','command_id':command_id,
                          'expected':expected,'changes':changes,'result':result,'request':request})


class DynamoState:
    def __init__(self,table):
        import boto3
        self.table=boto3.resource('dynamodb').Table(table)

    def state_get(self,key):
        item=self.table.get_item(Key={'pk':key,'sk':'STATE'},ConsistentRead=True).get('Item')
        return json.loads(item['payload']) if item else None

    def state_put(self,key,value,only_new=False):
        from botocore.exceptions import ClientError
        kwargs={'Item':{'pk':key,'sk':'STATE','payload':json.dumps(value)}}
        if 'expires_at' in value:kwargs['Item']['expires_at']=int(value['expires_at'])
        if key.startswith('NOTICE#'):
            kwargs['Item'].update(gsi_pk='NOTICES',gsi_sk=key)
        if only_new:kwargs['ConditionExpression']='attribute_not_exists(pk)'
        try:self.table.put_item(**kwargs);return True
        except ClientError as exc:
            if exc.response['Error']['Code']=='ConditionalCheckFailedException':return False
            raise

    def states(self,prefix):
        from boto3.dynamodb.conditions import Key
        check(prefix=='NOTICE#','Consulta de coordinación no soportada')
        items=[];cursor=None
        while True:
            kwargs={'IndexName':'notice-index','KeyConditionExpression':Key('gsi_pk').eq('NOTICES'),'Limit':200}
            if cursor:kwargs['ExclusiveStartKey']=cursor
            response=self.table.query(**kwargs);items += [json.loads(x['payload']) for x in response['Items']]
            cursor=response.get('LastEvaluatedKey')
            if not cursor:return items
