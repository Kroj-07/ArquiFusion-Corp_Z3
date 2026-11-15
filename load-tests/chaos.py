"""Detiene el consumidor temporalmente y SIEMPRE intenta restaurarlo en finally."""
import argparse
import json
import time
from pathlib import Path
import boto3

def wait_state(client,identifier,target,seconds=60):
    deadline=time.time()+seconds
    while time.time()<deadline:
        state=client.get_event_source_mapping(UUID=identifier)['State']
        if state==target:return
        time.sleep(1)
    raise TimeoutError(f'El mapping no llegó a {target}')

def main():
    p=argparse.ArgumentParser();p.add_argument('--mapping',required=True);p.add_argument('--queue-url',required=True);p.add_argument('--pause-seconds',type=int,default=20);p.add_argument('--manifest');p.add_argument('--telemetry-table');p.add_argument('--output',default='evidence/chaos.json');args=p.parse_args()
    if not 1<=args.pause_seconds<=60:p.error('Pausa de 1 a 60 segundos')
    client=boto3.client('lambda');sqs=boto3.client('sqs');initial=client.get_event_source_mapping(UUID=args.mapping)
    if initial['State']!='Enabled':raise RuntimeError('El consumidor no estaba habilitado. No se modificó.')
    result={'scope':'consumer interruption, not regional failure','initial_state':initial['State']}
    try:
        client.update_event_source_mapping(UUID=args.mapping,Enabled=False);wait_state(client,args.mapping,'Disabled')
        print('Consumidor detenido. Envía la corrida pequeña desde otra terminal ahora.')
        time.sleep(args.pause_seconds)
        result['queue_while_disabled']=sqs.get_queue_attributes(QueueUrl=args.queue_url,AttributeNames=['ApproximateNumberOfMessages','ApproximateNumberOfMessagesNotVisible'])['Attributes']
    finally:
        client.update_event_source_mapping(UUID=args.mapping,Enabled=True);wait_state(client,args.mapping,'Enabled');result['restored']=True
    print('Consumidor restaurado.')
    if args.manifest and args.telemetry_table:
        manifest=json.loads(Path(args.manifest).read_text());keys=manifest['accepted_reading_keys']
        if not manifest.get('manifest_complete'):raise RuntimeError('Manifest incompleto: no se puede afirmar pérdida cero')
        table=boto3.resource('dynamodb').Table(args.telemetry_table);missing=list(keys);deadline=time.time()+120
        while missing and time.time()<deadline:
            missing=[key for key in missing if 'Item' not in table.get_item(Key=key,ConsistentRead=True)];
            if missing:time.sleep(2)
        result.update(accepted_unique=len({(k['machine_id'],k['timestamp']) for k in keys}),missing_keys=missing,loss_zero_verified=not missing)
    else:result['loss_zero_verified']=False;result['note']='Sin conciliación por ID. La profundidad aproximada de SQS no demuestra pérdida cero.'
    path=Path(args.output);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))

if __name__=='__main__':main()
