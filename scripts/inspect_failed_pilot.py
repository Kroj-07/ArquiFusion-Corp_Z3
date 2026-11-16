"""Inventario de recuperación de af-z3-pilot: consulta solamente, nunca elimina recursos."""
import json
from pathlib import Path
import boto3
from botocore.exceptions import ClientError


def main():
    session=boto3.Session(region_name='us-east-1');account=session.client('sts').get_caller_identity()['Account']
    cf=session.client('cloudformation')
    try:stack=cf.describe_stacks(StackName='af-z3-pilot')['Stacks'][0]
    except ClientError as exc:
        if 'does not exist' in str(exc):print('No existe af-z3-pilot en esta cuenta.');return
        raise
    resources=[]
    for page in cf.get_paginator('list_stack_resources').paginate(StackName=stack['StackId']):resources+=page['StackResourceSummaries']
    retained=[{'logical_id':r['LogicalResourceId'],'type':r['ResourceType'],'physical_id':r.get('PhysicalResourceId'),'status':r['ResourceStatus']} for r in resources if r['ResourceStatus']=='DELETE_SKIPPED']
    report={'account':account,'stack_id':stack['StackId'],'status':stack['StackStatus'],'retained_resources':retained}
    if stack['StackStatus']=='ROLLBACK_COMPLETE':
        report['recovery']='Preservar este inventario. Eliminar SOLO el stack fallido después de validar los flujos, nunca af-test-data ni los recursos retenidos. Coordination tiene nombre generado: al recrear se obtiene una tabla nueva.'
    print(json.dumps(report,indent=2,default=str))
    folder=Path.home()/'.arquifusion-recovery';folder.mkdir(exist_ok=True)
    path=folder/('af-z3-pilot-'+account+'.json');path.write_text(json.dumps(report,indent=2,default=str))
    print('Inventario guardado fuera del repo: '+str(path))


if __name__=='__main__':main()
