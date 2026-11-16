const domain=(import.meta.env?.VITE_COGNITO_DOMAIN||'').replace(/\/$/,'');
const authMode=import.meta.env?.VITE_AUTH_MODE;
const apiBase=(import.meta.env?.VITE_API_BASE||'').replace(/\/$/,'');
let renewal=null;
const client=import.meta.env?.VITE_COGNITO_CLIENT_ID||'';
const b64=bytes=>btoa(String.fromCharCode(...bytes)).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');
async function sessionRequest(path,body){
 const response=await fetch(apiBase+path,{method:'POST',credentials:'same-origin',headers:{'content-type':'application/json'},body:JSON.stringify(body||{})});
 const payload=await response.json().catch(()=>({error:{message:'Respuesta de acceso invalida'}}));
 if(!response.ok)throw new Error(payload.error?.message||'No se pudo iniciar sesion.');
 return payload.data;
}
export async function refreshAccess(){
 if(authMode!=='password')return false;
 if(renewal)return renewal;
 renewal=(async()=>{try{const data=await sessionRequest('/v1/auth/refresh');if(!data.access_token)return false;sessionStorage.setItem('af_id_token',data.access_token);return true;}catch{sessionStorage.removeItem('af_id_token');return false;}})();
 try{return await renewal;}finally{renewal=null;}
}
export async function login(username,password){
 if(authMode==='password'){const data=await sessionRequest('/v1/auth/login',{username,password});if(!data?.access_token)throw new Error('No se recibio una sesion valida.');sessionStorage.setItem('af_id_token',data.access_token);location.reload();return;}

 if(import.meta.env?.VITE_AUTH_MODE==='pilot-token'){const token=window.prompt('Pega tu token temporal de acceso. Se valida en AWS; no es una contraseña.');if(!token)return;sessionStorage.setItem('af_id_token',token.trim());location.reload();return;}
 if(!domain.startsWith('https://')||!client)throw new Error('Configura el dominio y cliente público de Cognito.');
 const verifier=b64(crypto.getRandomValues(new Uint8Array(48))),state=crypto.randomUUID();
 sessionStorage.setItem('af_pkce',JSON.stringify({verifier,state}));
 const challenge=b64(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(verifier))));
 location.assign(`${domain}/oauth2/authorize?${new URLSearchParams({client_id:client,response_type:'code',scope:'openid profile email',redirect_uri:location.origin,code_challenge:challenge,code_challenge_method:'S256',state})}`);
}
export async function finishLogin(){
 if(authMode==='password'){if(!hasSession())await refreshAccess();return;}

 const params=new URLSearchParams(location.search);if(!params.has('code'))return;
 const saved=JSON.parse(sessionStorage.getItem('af_pkce')||'null');
 if(!saved||saved.state!==params.get('state'))throw new Error('No se pudo validar el estado de la sesión.');
 const response=await fetch(`${domain}/oauth2/token`,{method:'POST',headers:{'content-type':'application/x-www-form-urlencoded'},body:new URLSearchParams({grant_type:'authorization_code',client_id:client,redirect_uri:location.origin,code:params.get('code'),code_verifier:saved.verifier})});
 const result=await response.json();if(!response.ok)throw new Error(result.error_description||'Cognito no pudo completar el acceso');
 if(!result.id_token)throw new Error('La sesión no incluyó el ID token requerido por esta API.');
 sessionStorage.setItem('af_id_token',result.id_token);sessionStorage.removeItem('af_pkce');history.replaceState({},'',location.pathname);
}
export function hasSession(){return !!sessionStorage.getItem('af_id_token');}
export function logout(){if(authMode==='password'){sessionStorage.removeItem('af_id_token');sessionRequest('/v1/auth/logout').finally(()=>location.reload());return;}
sessionStorage.removeItem('af_id_token');sessionStorage.removeItem('af_pkce');if(domain&&client)location.assign(`${domain}/logout?${new URLSearchParams({client_id:client,logout_uri:location.origin})}`);else location.reload();}
