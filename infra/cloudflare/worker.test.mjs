import test from 'node:test';
import assert from 'node:assert/strict';
import {createHmac} from 'node:crypto';
import worker from './worker.mjs';

function signed(body, stamp=String(Math.floor(Date.now()/1000)), secret='test-shared-secret') {
 const raw=JSON.stringify(body), path='/v1/ai/explain';
 const signature=createHmac('sha256',secret).update(stamp+'\nPOST\n'+path+'\n'+raw).digest('hex');
 return new Request('https://worker.example'+path,{method:'POST',body:raw,headers:{'x-timestamp':stamp,'x-signature-version':'c-1','x-signature':signature}});
}
const body={role:'technician',alert:{alert_id:'ALT-1',machine_id:'MCH-000001',evidence:[]}};
test('unsigned requests do not invoke AI',async()=>{
 let called=false; const response=await worker.fetch(new Request('https://w.example/v1/ai/explain',{method:'POST',body:'{}'}),{SHARED_KEY:'test-shared-secret',AI:{run:()=>{called=true;}}});
 assert.equal(response.status,401);assert.equal(called,false);
});
test('c-1 signature authenticates body and generates sourced response',async()=>{
 const response=await worker.fetch(signed(body),{SHARED_KEY:'test-shared-secret',AI:{run:async()=>({response:'Evidencia ALT-1: revisar MCH-000001.'})}});
 assert.equal(response.status,200); const result=await response.json();assert.equal(result.data.provider,'cloudflare-workers-ai');assert.deepEqual(result.data.grounded_on,['ALT-1','MCH-000001']);
});
test('old signatures are rejected',async()=>{
 const response=await worker.fetch(signed(body,'1'),{SHARED_KEY:'test-shared-secret'});assert.equal(response.status,401);
});
test('AI failure is not converted to a made up success',async()=>{
 const response=await worker.fetch(signed(body),{SHARED_KEY:'test-shared-secret',AI:{run:async()=>{throw Error('quota');}}});assert.equal(response.status,502);
});
