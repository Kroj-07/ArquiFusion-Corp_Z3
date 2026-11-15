"""Genera ASL a partir de piezas pequeñas; JSON final se incluye en el paquete."""
import json
from pathlib import Path

ROOT=Path(__file__).parent
RETRY=[{'ErrorEquals':['Lambda.ServiceException','Lambda.AWSLambdaException','Lambda.SdkClientException','Lambda.TooManyRequestsException'],'IntervalSeconds':2,'MaxAttempts':3,'BackoffRate':2}]


def task(action,payload,next_state=None,result=None,end=False):
    state={'Type':'Task','Resource':'arn:aws:states:::lambda:invoke','Parameters':{'FunctionName':'${WorkflowFunctionArn}','Payload':{'action':action,**payload}},'Retry':RETRY,'OutputPath':'$.Payload'}
    if result is not None:state.pop('OutputPath');state['ResultSelector']={'data.$':'$.Payload'};state['ResultPath']=result
    if next_state:state['Next']=next_state
    if end:state['End']=True
    return state


def branch(action):return {'StartAt':'Run','States':{'Run':task(action,{'alert.$':'$.alert'},end=True)}}


def build():
    states={
      'RecordAlert':{'Type':'Task','Resource':'arn:aws:states:::dynamodb:putItem','Parameters':{
          'TableName':'${CStateTable}','Item':{'pk':{'S.$':"States.Format('EVENT#{}', $.alert.alert_id)"},'sk':{'S':'ALERT'},'alert':{'S.$':'States.JsonToString($.alert)'}},'ConditionExpression':'attribute_not_exists(pk)'},
          'ResultPath':None,'Catch':[{'ErrorEquals':['DynamoDB.ConditionalCheckFailedException'],'Next':'AlreadyRecorded'},{'ErrorEquals':['States.ALL'],'ResultPath':'$.failure','Next':'QueueFailure'}],'Next':'CheckSeverity'},
      'AlreadyRecorded':{'Type':'Succeed'},
      'CheckSeverity':{'Type':'Choice','Choices':[{'Or':[{'Variable':'$.alert.severity','StringEquals':'info'},{'Variable':'$.alert.severity','StringEquals':'low'}],'Next':'RecordedOnly'}],'Default':'PrepareInParallel'},
      'RecordedOnly':{'Type':'Succeed'},
      'PrepareInParallel':{'Type':'Parallel','Branches':[branch('create'),branch('context'),branch('explain')],'ResultPath':'$.prepared','Next':'SetContext'},
      'SetContext':{'Type':'Pass','Parameters':{'alert.$':'$.alert','incident_id.$':'$.prepared[0].incident_id','excluded.$':'$.excluded','attempt':0},'Next':'AssignTechnician'},
      'AssignTechnician':task('assign',{'incident_id.$':'$.incident_id','excluded.$':'$.excluded'},'Assigned?',result='$.assignment'),
      'Assigned?':{'Type':'Choice','Choices':[{'Variable':'$.assignment.data.assigned','BooleanEquals':True,'Next':'NotifyTechnician'}],'Default':'NotifySupervisor'},
      'NotifySupervisor':{'Type':'Task','Resource':'arn:aws:states:::sns:publish','Parameters':{'TopicArn':'${TopicArn}','Message.$':"States.Format('Sin técnico disponible para {}. Se requiere asignación manual.', $.incident_id)"},'ResultPath':None,'Next':'WaitForAssignment'},
      'WaitForAssignment':{'Type':'Task','Resource':'arn:aws:states:::lambda:invoke.waitForTaskToken','Parameters':{'FunctionName':'${WorkflowFunctionArn}','Payload':{'action':'wait','incident_id.$':'$.incident_id','phase':'assignment','task_token.$':'$$.Task.Token','execution.$':'$$.Execution.Id','ttl':3630}},'TimeoutSeconds':3600,'ResultPath':'$.manual_assignment','Next':'AssignTechnician'},
      'NotifyTechnician':task('notify',{'alert.$':'$.alert','role':'technician'},'WaitForAcknowledgement',result='$.technician_notification'),
      'WaitForAcknowledgement':{'Type':'Task','Resource':'arn:aws:states:::lambda:invoke.waitForTaskToken','Parameters':{'FunctionName':'${WorkflowFunctionArn}','Payload':{'action':'wait','incident_id.$':'$.incident_id','phase':'ack','task_token.$':'$$.Task.Token','execution.$':'$$.Execution.Id','ttl':330}},'TimeoutSeconds':300,'ResultPath':'$.ack','Catch':[{'ErrorEquals':['States.Timeout'],'ResultPath':'$.timeout','Next':'Escalate'},{'ErrorEquals':['States.ALL'],'ResultPath':'$.failure','Next':'QueueFailure'}],'Next':'RecordAcknowledgement'},
      'RecordAcknowledgement':task('ack',{'incident_id.$':'$.incident_id','callback.$':'$.ack'},'WaitForClosure',result='$.ack_record'),
      'Escalate':task('escalate',{'incident_id.$':'$.incident_id','excluded.$':'$.excluded','command_id.$':"States.Format('escalate:{}:{}', $.incident_id, $.attempt)"},'CheckAcknowledgementRace',result='$.escalation'),
      'CheckAcknowledgementRace':{'Type':'Choice','Choices':[{'Variable':'$.escalation.data.already_acknowledged','BooleanEquals':True,'Next':'WaitForClosure'}],'Default':'NextAttempt'},
      'NextAttempt':{'Type':'Pass','Parameters':{'alert.$':'$.alert','incident_id.$':'$.incident_id','excluded.$':'$.escalation.data.excluded','attempt.$':'States.MathAdd($.attempt, 1)'},'Next':'AttemptLimit'},
      'AttemptLimit':{'Type':'Choice','Choices':[{'Variable':'$.attempt','NumericGreaterThanEquals':3,'Next':'NotifySupervisor'}],'Default':'AssignTechnician'},
      'WaitForClosure':{'Type':'Task','Resource':'arn:aws:states:::lambda:invoke.waitForTaskToken','Parameters':{'FunctionName':'${WorkflowFunctionArn}','Payload':{'action':'wait','incident_id.$':'$.incident_id','phase':'close','task_token.$':'$$.Task.Token','execution.$':'$$.Execution.Id','ttl':86430}},'TimeoutSeconds':86400,'ResultPath':'$.closure','Next':'FinalizeAtomically'},
      'FinalizeAtomically':task('finalize',{'incident_id.$':'$.incident_id','callback.$':'$.closure'},'LowStockNotifications',result='$.final'),
      'LowStockNotifications':{'Type':'Map','ItemsPath':'$.final.data.stock_alerts','MaxConcurrency':2,'ItemProcessor':{'ProcessorConfig':{'Mode':'INLINE'},'StartAt':'NotifyLowStock','States':{'NotifyLowStock':task('stock_low',{'part.$':'$'},end=True)}},'ResultPath':None,'Next':'PublishIncidentClosed'},
      'PublishIncidentClosed':{'Type':'Task','Resource':'arn:aws:states:::events:putEvents','Parameters':{'Entries':[{'EventBusName':'${EventBusName}','Source':'arquifusion.operations','DetailType':'incident.closed','Detail.$':'States.JsonToString($.final.data)'}]},'ResultPath':'$.published','Next':'CheckPublished'},
      'CheckPublished':{'Type':'Choice','Choices':[{'Variable':'$.published.FailedEntryCount','NumericGreaterThan':0,'Next':'QueueFailure'}],'Default':'Resolved'},
      'QueueFailure':{'Type':'Task','Resource':'arn:aws:states:::sqs:sendMessage','Parameters':{'QueueUrl':'${ErrorsQueueUrl}','MessageBody.$':'States.JsonToString($)'},'ResultPath':None,'Next':'Failed'},
      'Resolved':{'Type':'Succeed'},'Failed':{'Type':'Fail','Error':'INCIDENT_ACTION_REQUIRED'}
    }
    for name,state in states.items():
        if state['Type'] in ('Task','Parallel','Map') and name not in ('RecordAlert','QueueFailure') and 'Catch' not in state:
            state['Catch']=[{'ErrorEquals':['States.ALL'],'ResultPath':'$.failure','Next':'QueueFailure'}]
        if state['Type']=='Task' and 'waitForTaskToken' in state.get('Resource',''):state['Retry']=RETRY
    workflow={'Comment':'C · Standard. Callback tokens privados; cierre e inventario en una sola transacción.','StartAt':'RecordAlert','TimeoutSeconds':172800,'States':states}
    roles=['operator','technician','maintenance','supervisor','admin','manager']
    branches=[]
    for role in roles:branches.append({'StartAt':'NotifyRole','States':{'NotifyRole':task('notify',{'alert.$':'$.alert','role':role},end=True)}})
    fanout={'Comment':'C · Express. Inbox deduplicado por alert_id/rol/alcance. SNS puede entregar más de una vez.','StartAt':'FanOutByRole','TimeoutSeconds':240,'States':{
      'FanOutByRole':{'Type':'Parallel','Branches':branches,'ResultPath':None,'Catch':[{'ErrorEquals':['States.ALL'],'ResultPath':'$.failure','Next':'QueueFailure'}],'Next':'Delivered'},
      'QueueFailure':states['QueueFailure'],'Failed':{'Type':'Fail','Error':'NOTIFICATION_ACTION_REQUIRED'},'Delivered':{'Type':'Succeed'}}}
    (ROOT/'sf1-incident.asl.json').write_text(json.dumps(workflow,indent=2),encoding='utf-8')
    (ROOT/'sf3-notifications.asl.json').write_text(json.dumps(fanout,indent=2),encoding='utf-8')

if __name__=='__main__':build()
