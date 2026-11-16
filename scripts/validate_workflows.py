"""Comprueba referencias locales y llama al validador real de AWS sin crear recursos."""
import argparse
import json
from pathlib import Path
import sys
import boto3

ROOT=Path(__file__).resolve().parents[1]


def check_graph(document, seen=None):
    seen=set() if seen is None else seen
    states=document['States']
    if document['StartAt'] not in states:raise ValueError('StartAt apunta a un estado inexistente')
    def destinations(value):
        if isinstance(value,dict):
            for key,child in value.items():
                if key in ('Next','Default') and isinstance(child,str):yield child
                elif key not in ('Branches','ItemProcessor','Iterator'):
                    yield from destinations(child)
        elif isinstance(value,list):
            for child in value:yield from destinations(child)
    for name,state in states.items():
        if name in seen:raise ValueError('Nombre de estado duplicado: '+name)
        seen.add(name)
        for target in destinations(state):
            if target not in states:raise ValueError(name+' apunta fuera de su ámbito: '+target)
        for child in state.get('Branches',[]):check_graph(child,seen)
        if 'ItemProcessor' in state:check_graph(state['ItemProcessor'],seen)
        if 'Iterator' in state:check_graph(state['Iterator'],seen)
    return seen


def render(path,account,region):
    text=Path(path).read_text(encoding='utf-8')
    substitutions={'WorkflowFunctionArn':f'arn:aws:lambda:{region}:{account}:function:af-validation',
                   'CStateTable':'af-validation-table','TopicArn':f'arn:aws:sns:{region}:{account}:af-validation',
                   'EventBusName':'af-validation-events','ErrorsQueueUrl':f'https://sqs.{region}.amazonaws.com/{account}/af-validation'}
    for key,value in substitutions.items():text=text.replace('${'+key+'}',value)
    if '${' in text:raise ValueError('Quedan variables sin sustituir en '+str(path))
    return text


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--region',default='us-east-1');parser.add_argument('--account');parser.add_argument('--local-only',action='store_true')
    args=parser.parse_args();client=None
    if not args.local_only:
        session=boto3.Session(region_name=args.region)
        args.account=args.account or session.client('sts').get_caller_identity()['Account']
        client=session.client('stepfunctions')
    failed=False
    for filename,kind in [('sf1-incident.asl.json','STANDARD'),('sf3-notifications.asl.json','EXPRESS')]:
        path=ROOT/'infra/part-c'/filename
        names=check_graph(json.loads(path.read_text(encoding='utf-8')))
        print(filename+': '+str(len(names))+' estados únicos; referencias locales correctas')
        if client:
            result=client.validate_state_machine_definition(definition=render(path,args.account,args.region),type=kind,severity='ERROR',maxResults=100)
            print(json.dumps({'file':filename,'result':result['result'],'diagnostics':result.get('diagnostics',[])},ensure_ascii=False))
            failed=failed or result['result']!='OK'
    if failed:raise SystemExit('AWS rechazó una definición. No se debe desplegar.')


if __name__=='__main__':main()
