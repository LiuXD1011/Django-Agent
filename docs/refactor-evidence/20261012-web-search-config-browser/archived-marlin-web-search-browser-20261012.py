import base64,datetime,hashlib,json,subprocess,sys,time
from pathlib import Path
root=Path('/home/liuxuedeng/Django-Agent')
evidence=root/'docs/refactor-evidence/20261012-web-search-config-browser'
evidence.mkdir(parents=True,exist_ok=True)
page='22e0e212-30aa-4945-8a3d-7176cdfffdff'
label=sys.argv[1]
command=['orca-ide',*sys.argv[2:],'--page',page,'--json']
started=datetime.datetime.now(datetime.timezone.utc).isoformat();clock=time.monotonic()
try:
    p=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=45)
    raw=p.stdout.decode(errors='replace');stderr=p.stderr.decode(errors='replace')
    try:receipt=json.loads(raw[raw.find('{'):])
    except Exception:receipt={'unparsed':raw}
    result={'started_at':started,'finished_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'page':page,'command':command,'exit_code':p.returncode,'elapsed_ms':round((time.monotonic()-clock)*1000,3),'receipt':receipt,'stderr':stderr}
except subprocess.TimeoutExpired as e:
    result={'started_at':started,'page':page,'command':command,'exit_code':None,'elapsed_ms':round((time.monotonic()-clock)*1000,3),'timeout':True,'stdout':(e.stdout or b'').decode(errors='replace'),'stderr':(e.stderr or b'').decode(errors='replace')}
if 'screenshot' in command:
    data=result.get('receipt',{}).get('result',{}).get('data')
    if isinstance(data,str):
        try:
            raw=base64.b64decode(data.split(',',1)[-1],validate=True)
            if raw.startswith(b'\x89PNG\r\n\x1a\n'):
                path=evidence/(label+'.png');path.write_bytes(raw)
                result['receipt']['result']['data']='<PNG saved separately>'
                result['receipt']['result']['image_file']=str(path)
                result['receipt']['result']['image_sha256']=hashlib.sha256(raw).hexdigest()
        except ValueError:pass
(evidence/(label+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
display=dict(result)
receipt=display.get('receipt',{})
if 'snapshot' in receipt.get('result',{}):
    data=receipt['result']
    display['receipt']={'ok':receipt.get('ok'),'result':{key:data[key] for key in ['origin','snapshot','browserPageId'] if key in data}}
if 'data' in receipt.get('result', {}) and isinstance(receipt['result']['data'], str):
    display['receipt']={'ok':receipt.get('ok'),'result':{k:v for k,v in receipt['result'].items() if k!='data'},'encoded_data_length':len(receipt['result']['data'])}
print(json.dumps(display,ensure_ascii=False,indent=2))
sys.exit(result.get('exit_code') if result.get('exit_code') is not None else 1)
