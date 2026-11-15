"""Nico puede reutilizar verify() en su middleware C→B. No es el protocolo B→A."""
import hashlib
import hmac
import time

def verify(secret,headers,raw_path_and_query,method='GET',body=b'',now=None):
    headers={k.lower():v for k,v in headers.items()};stamp=headers.get('x-timestamp','')
    try:
        if abs((time.time() if now is None else now)-int(stamp))>300:return False
    except (ValueError,TypeError):return False
    if headers.get('x-signature-version')!='c-1':return False
    data=f'{stamp}\n{method}\n{raw_path_and_query}\n'.encode()+body
    expected=hmac.new(secret.encode(),data,hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected,headers.get('x-signature',''))
