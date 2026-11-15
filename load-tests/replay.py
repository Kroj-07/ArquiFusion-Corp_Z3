"""Carga acotada sobre la API de A. No ejecutar contra producción sin coordinar con Kiara."""
import argparse
import concurrent.futures
import getpass
import hashlib
import hmac
import json
import random
import statistics
import time
import urllib.request
from datetime import datetime,timedelta,timezone
from pathlib import Path

def readings(machines,steps,seed):
    rng=random.Random(seed);start=datetime.now(timezone.utc)-timedelta(seconds=steps*10)
    for step in range(steps):
        for n in range(machines):
            stamp=(start+timedelta(seconds=step*10)).isoformat(timespec='milliseconds').replace('+00:00','Z')
            drift=(step/max(1,steps-1))*15 if n%5==0 else 0
            yield {'schema_version':'1.0','machine_id':f'MCH-LOAD-{n:06d}','timestamp':stamp,
                'location':{'lat':-12.04+rng.random()*.04,'lon':-76.95+rng.random()*.04,'zone_id':'ZONA-NORTE-02'},'status':'operating',
                'metrics':{'engine_temp_c':88+rng.gauss(0,2)+drift,'vibration_mm_s':3+rng.random()+drift/10,
                    'pressure_bar':6+rng.random()*.3,'fuel_rate_lph':30+rng.random()*3+drift/3,
                    'load_kg':15000,'speed_kmh':12,'engine_rpm':1800,'operating_hours_total':3200+step/360}}

def main():
    p=argparse.ArgumentParser();p.add_argument('--api',required=True,help='Base HTTPS de A, sin /v1');p.add_argument('--machines',type=int,default=100);p.add_argument('--steps',type=int,default=3);p.add_argument('--batch-size',type=int,default=25);p.add_argument('--workers',type=int,default=2);p.add_argument('--seed',type=int,default=17);p.add_argument('--auth',choices=['bearer','hmac-body','hmac-bound'],default='bearer');p.add_argument('--secret-id',help='AWS Secrets Manager, shared_key; nunca pasar el valor como argumento');p.add_argument('--output',default='evidence/replay.json');args=p.parse_args()
    if not args.api.startswith('https://') or not 1<=args.machines<=5000 or not 1<=args.steps<=100 or not 1<=args.batch_size<=50 or not 1<=args.workers<=8:p.error('HTTPS; máquinas 1..5000, pasos 1..100, lote 1..50, concurrencia 1..8')
    if args.secret_id:
        import boto3
        raw=boto3.client('secretsmanager').get_secret_value(SecretId=args.secret_id)['SecretString'];credential=json.loads(raw)['shared_key']
    else:credential=getpass.getpass('Token o secreto (entrada oculta): ')
    dataset=list(readings(args.machines,args.steps,args.seed));batches=[dataset[n:n+args.batch_size] for n in range(0,len(dataset),args.batch_size)]
    def send(batch):
        body=json.dumps({'readings':batch},separators=(',',':')).encode();headers={'content-type':'application/json'}
        if args.auth=='bearer':headers['authorization']='Bearer '+credential
        else:
            stamp=str(int(time.time()));signed=body if args.auth=='hmac-body' else f'{stamp}\nPOST\n/v1/telemetry\n'.encode()+body
            headers.update({'x-timestamp':stamp,'x-signature':hmac.new(credential.encode(),signed,hashlib.sha256).hexdigest()})
        began=time.perf_counter()
        try:
            with urllib.request.urlopen(urllib.request.Request(args.api.rstrip('/')+'/v1/telemetry',data=body,headers=headers),timeout=40) as response:result=json.load(response)
            result=result.get('data',result);failed={e['index'] for e in result.get('errors',[]) if isinstance(e,dict) and 'index' in e}
            accepted=[r for n,r in enumerate(batch) if n not in failed];complete=result.get('accepted')==len(accepted)
            return {'latency_ms':(time.perf_counter()-began)*1000,'http_ok':True,'accepted':accepted if complete else [],'manifest_complete':complete}
        except Exception as exc:return {'latency_ms':(time.perf_counter()-began)*1000,'http_ok':False,'accepted':[],'error':type(exc).__name__,'manifest_complete':True}
    start=time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:results=list(executor.map(send,batches))
    latency=sorted(r['latency_ms'] for r in results);accepted=[{'machine_id':r['machine_id'],'timestamp':r['timestamp']} for row in results for r in row['accepted']]
    output={'machines':args.machines,'steps':args.steps,'sent_readings':len(dataset),'requests':len(results),'http_failed_requests':sum(not r['http_ok'] for r in results),
        'p95_ingest_http_ms':round(latency[max(0,__import__('math').ceil(.95*len(latency))-1)],2),'duration_seconds':round(time.perf_counter()-start,2),
        'accepted_reading_keys':accepted,'manifest_complete':all(r['manifest_complete'] for r in results),
        'limitation':'Latencia del cliente a la respuesta de ingesta. No mide detección, notificación ni procesamiento completo.'}
    path=Path(args.output);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(output,indent=2))
    print(json.dumps({k:v for k,v in output.items() if k!='accepted_reading_keys'},indent=2));print('Manifest:',path)

if __name__=='__main__':main()
