import argparse
import json
import os
import uuid
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from .domain import Problem,ROLES
from .seed import seed
from .store import SQLitePort
from .service import Service

def principal(role):
    return {'sub':'demo-'+role,'role':role,'name':{'maintenance':'Coordinación de mantenimiento','technician':'Lucía Torres','operator':'Operador de excavadora','supervisor':'Supervisión Norte','admin':'Administración Z3','manager':'Gerencia de operación'}[role],
            'zone_ids':['ZONA-NORTE-02','ZONA-CENTRO-01','ZONA-SUR-03'] if role in ('maintenance','admin','manager') else ['ZONA-NORTE-02'],
            'machine_ids':['MCH-000001'],'technician_id':'TEC-0003' if role=='technician' else None}

def create_service(database):
    port=SQLitePort(database);port.seed(seed());service=Service(port,port,mode='demo')
    snapshot=port.snapshot()
    for incident in snapshot['incidents']:
        if incident['status']=='assigned' and not incident.get('acknowledged_at'):
            key=f'TOKEN#{incident["incident_id"]}#ack'
            if not port.state_get(key):service.register_callback(incident['incident_id'],'ack','demo-ack',ttl=86400)
        if incident['status']=='in_progress':
            key=f'TOKEN#{incident["incident_id"]}#close'
            if not port.state_get(key):service.register_callback(incident['incident_id'],'close','demo-close',ttl=86400)
    for alert in snapshot['alerts']:service.notify(alert)
    return service

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8000);parser.add_argument('--database',default='.local/demo.sqlite')
    args=parser.parse_args();service=create_service(args.database)
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):self.handle_request()
        def do_POST(self):self.handle_request()
        def handle_request(self):
            path=self.path.split('?')[0]
            if path=='/health':return self.respond(200,{'status':'ok','mode':'demo'})
            role=self.headers.get('X-Demo-Role','maintenance')
            if role not in ROLES:return self.respond(403,{'error':{'message':'Rol de demo inválido'}})
            try:
                size=int(self.headers.get('Content-Length','0'))
                if size>262144:raise Problem('Cuerpo demasiado grande','VALIDATION_ERROR',413)
                body=json.loads(self.rfile.read(size)) if size else {}
                result=service.route(self.command,path,body,principal(role),self.headers.get('Idempotency-Key',str(uuid.uuid4())))
                self.respond(200,{'data':result})
            except Problem as exc:self.respond(exc.status,{'error':{'code':exc.code,'message':str(exc)}})
            except (ValueError,KeyError,TypeError) as exc:self.respond(400,{'error':{'code':'VALIDATION_ERROR','message':str(exc)}})
            except Exception:
                import traceback;traceback.print_exc();self.respond(500,{'error':{'message':'Error local; consultar terminal'}})
        def respond(self,status,payload):
            raw=json.dumps(payload,ensure_ascii=False,allow_nan=False).encode();self.send_response(status)
            self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        def log_message(self,fmt,*args):print(self.command,self.path,args[1] if len(args)>1 else '')
    print(f'ArquiFusion C demo API http://127.0.0.1:{args.port} · SQLite persistente · Ctrl+C para detener')
    ThreadingHTTPServer(('127.0.0.1',args.port),Handler).serve_forever()

if __name__=='__main__':main()
