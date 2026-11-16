import {refreshAccess} from './auth.js';
export const mode=import.meta.env?.VITE_DATA_MODE || 'demo';
export const base=(import.meta.env?.VITE_API_BASE || '').replace(/\/$/,'');
export const roleNames={maintenance:'Mantenimiento',technician:'Técnico',operator:'Operador',supervisor:'Supervisor',admin:'Administrador',manager:'Gerencia'};
export const statusNames={operating:'Operativa',idle:'En espera',stopped:'Detenida',maintenance:'Mantenimiento',fault:'Requiere atención',open:'Sin asignar',assigned:'Asignado',in_progress:'En atención',closed:'Resuelto'};
export const severityNames={critical:'Crítica',high:'Alta',medium:'Media',low:'Baja',info:'Informativa'};
export async function request(path,{method='GET',body,role='maintenance',key}={}){
  const headers={'content-type':'application/json'};
  if(mode==='demo') headers['X-Demo-Role']=role;
  else {const token=sessionStorage.getItem('af_id_token');if(token) headers.Authorization=`Bearer ${token}`;}
  if(method!=='GET') headers['Idempotency-Key']=key||crypto.randomUUID();
  const send=()=>fetch(base+path,{method,headers,body:body===undefined?undefined:JSON.stringify(body),signal:AbortSignal.timeout(30000)});
  let response=await send();
  if(response.status===401&&mode!=='demo'&&await refreshAccess()){headers.Authorization=`Bearer ${sessionStorage.getItem('af_id_token')}`;response=await send();}

  const payload=await response.json().catch(()=>({error:{message:'Respuesta inválida del servicio'}}));
  if(!response.ok)throw new Error(payload.error?.message||`Error HTTP ${response.status}`);
  return payload.data??payload;
}
export function fmtTime(value,full=false){return value?new Intl.DateTimeFormat('es-PE',{timeZone:'America/Lima',...(full?{day:'2-digit',month:'short'}:{}),hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(value)):'—';}
export function number(value,digits=0){return value===null||value===undefined?'—':new Intl.NumberFormat('es-PE',{maximumFractionDigits:digits}).format(value);}
export function riskTone(score){return score>=90?'critical':score>=75?'high':score>=50?'medium':'low';}
