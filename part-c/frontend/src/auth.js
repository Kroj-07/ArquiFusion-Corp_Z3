const domain=(import.meta.env.VITE_COGNITO_DOMAIN||'').replace(/\/$/,'');
const client=import.meta.env.VITE_COGNITO_CLIENT_ID||'';
const b64=bytes=>btoa(String.fromCharCode(...bytes)).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');
export async function login(){
 if(!domain.startsWith('https://')||!client)throw new Error('Configura el dominio y cliente público de Cognito.');
 const verifier=b64(crypto.getRandomValues(new Uint8Array(48))),state=crypto.randomUUID();
 sessionStorage.setItem('af_pkce',JSON.stringify({verifier,state}));
 const challenge=b64(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(verifier))));
 location.assign(`${domain}/oauth2/authorize?${new URLSearchParams({client_id:client,response_type:'code',scope:'openid profile email',redirect_uri:location.origin,code_challenge:challenge,code_challenge_method:'S256',state})}`);
}
export async function finishLogin(){
 const params=new URLSearchParams(location.search);if(!params.has('code'))return;
 const saved=JSON.parse(sessionStorage.getItem('af_pkce')||'null');
 if(!saved||saved.state!==params.get('state'))throw new Error('No se pudo validar el estado de la sesión.');
 const response=await fetch(`${domain}/oauth2/token`,{method:'POST',headers:{'content-type':'application/x-www-form-urlencoded'},body:new URLSearchParams({grant_type:'authorization_code',client_id:client,redirect_uri:location.origin,code:params.get('code'),code_verifier:saved.verifier})});
 const result=await response.json();if(!response.ok)throw new Error(result.error_description||'Cognito no pudo completar el acceso');
 if(!result.id_token)throw new Error('La sesión no incluyó el ID token requerido por esta API.');
 sessionStorage.setItem('af_id_token',result.id_token);sessionStorage.removeItem('af_pkce');history.replaceState({},'',location.pathname);
}
export function hasSession(){return !!sessionStorage.getItem('af_id_token');}
export function logout(){sessionStorage.removeItem('af_id_token');sessionStorage.removeItem('af_pkce');if(domain&&client)location.assign(`${domain}/logout?${new URLSearchParams({client_id:client,logout_uri:location.origin})}`);else location.reload();}
