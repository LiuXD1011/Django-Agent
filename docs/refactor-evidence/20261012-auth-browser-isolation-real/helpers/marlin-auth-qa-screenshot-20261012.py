import base64
import datetime
import json
import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path('/home/liuxuedeng/Django-Agent')
OUT = ROOT/'docs/refactor-evidence/20261012-auth-browser-isolation-real'
page = sys.argv[1]
label = sys.argv[2]
if page not in {'e4fa4cd8-169e-4b52-9584-8782c73189a7','e87a76af-50bc-49b2-9b29-e9f6d19c88a5','9196f757-1a9d-407e-b44a-c32566d70c4e','c238d027-40e5-4e54-91f0-6890763922a3'}: raise SystemExit('Only owned public device page screenshot allowed')
args=['orca-ide','screenshot','--page',page,'--format','png','--json']
result=subprocess.run(args,cwd=ROOT,capture_output=True,text=True,timeout=90)
data=json.loads(result.stdout[result.stdout.find('{'):])
saved=[]
def visit(node, chain=''):
    if isinstance(node,dict):
        for key,value in node.items(): visit(value,chain+'/'+key)
    elif isinstance(node,list):
        for i,value in enumerate(node): visit(value,chain+'/'+str(i))
    elif isinstance(node,str):
        if node.startswith('data:image/png;base64,'):
            target=OUT/(label+'.png')
            if target.exists(): raise FileExistsError(target)
            target.write_bytes(base64.b64decode(node.split(',',1)[1]));saved.append({'field':chain,'path':str(target.relative_to(ROOT))})
        elif node.lower().endswith('.png') and (node.startswith('/') or len(node)>3 and node[1:3] in [':\\',':/']):
            source=pathlib.Path('/mnt/'+node[0].lower()+'/'+node[3:].replace('\\','/')) if node[1:3] in [':\\',':/'] else pathlib.Path(node)
            if source.is_file():
                target=OUT/(label+'.png')
                if not target.exists(): shutil.copyfile(source,target)
                saved.append({'field':chain,'path':str(target.relative_to(ROOT))})
payload=data.get('result',{})
if payload.get('format') == 'png' and isinstance(payload.get('data'), str):
    target=OUT/(label+'.png')
    if target.exists(): raise FileExistsError(target)
    image=base64.b64decode(payload['data'], validate=True)
    if not image.startswith(b'\x89PNG\r\n\x1a\n'): raise RuntimeError('Unexpected screenshot image signature')
    target.write_bytes(image);saved.append({'field':'/result/data','path':str(target.relative_to(ROOT))})
else: visit(payload)
record={'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'arguments':args,'exit_code':result.returncode,'ok':data.get('ok'),'error':data.get('error'),'result_keys':list(data.get('result',{})),'saved':saved,'raw_base64_printed_or_persisted':False,'public_qa_view_only':True}
p=OUT/(label+'.json')
if p.exists():raise FileExistsError(p)
p.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n');print(json.dumps(record,ensure_ascii=False,indent=2))
