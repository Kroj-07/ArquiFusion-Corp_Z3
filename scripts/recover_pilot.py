"""Elimina solo el contenedor CloudFormation fallido, conservando los recursos Retain."""
import argparse
import json
from pathlib import Path
import boto3
from botocore.exceptions import ClientError


def main():
    p=argparse.ArgumentParser();p.add_argument('--stack',choices=['af-z3-pilot','af-z3-c'],required=True);p.add_argument('--expected-account',required=True)
    args=p.parse_args();session=boto3.Session(region_name='us-east-1');account=session.client('sts').get_caller_identity()['Account']
    if account!=args.expected_account:raise SystemExit('Cuenta incorrecta. No se elimino nada.')
    cf=session.client('cloudformation')
    try:stack=cf.describe_stacks(StackName=args.stack)['Stacks'][0]
    except ClientError as exc:
        if 'does not exist' in str(exc):print('Stack nuevo; no hay nada que recuperar.');return
        raise
    status=stack['StackStatus']
    if status in ('CREATE_COMPLETE','UPDATE_COMPLETE'):print('Stack sano; se actualizara normalmente.');return
    if status!='ROLLBACK_COMPLETE':raise SystemExit('No se elimina un stack en estado '+status+'. Revisar manualmente.')
    records=[]
    for page in cf.get_paginator('list_stack_resources').paginate(StackName=stack['StackId']):records+=page['StackResourceSummaries']
    # Solo se espera retencion de tablas propias del piloto. Nunca se elimina una tabla.
    retained=[r for r in records if r['ResourceStatus']=='DELETE_SKIPPED']
    report={'account':account,'stack_id':stack['StackId'],'status':status,'retained_resources':retained}
    folder=Path.home()/'.arquifusion-recovery';folder.mkdir(exist_ok=True)
    path=folder/(args.stack+'-'+account+'.json');path.write_text(json.dumps(report,indent=2,default=str))
    print('Inventario guardado: '+str(path))
    for row in retained:print('CONSERVADO: '+str(row.get('PhysicalResourceId')))
    print('Eliminando SOLO el stack fallido '+args.stack+'; af-test-data y las tablas retenidas permanecen.')
    cf.delete_stack(StackName=stack['StackId'])
    cf.get_waiter('stack_delete_complete').wait(StackName=stack['StackId'])
    print('Contenedor fallido eliminado. El siguiente create usara tablas de coordinacion nuevas.')


if __name__=='__main__':main()
