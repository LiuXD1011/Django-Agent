import ctypes, datetime, hashlib, json, os, pathlib, platform, re, select, signal, sqlite3, time
ROOT=pathlib.Path('/home/liuxuedeng/Django-Agent')
OUT=ROOT/'docs/refactor-evidence/20261012-auth-browser-isolation-real'
DATA=pathlib.Path('/home/liuxuedeng/.local/share/marlin-refactor/20261012-auth-browser-isolation')
BASE=json.loads((OUT/'002-startup.json').read_text())
SOURCE=json.loads((OUT/'000-preflight.json').read_text())['source_process']
if (platform.system(),platform.machine())!=('Linux','x86_64'): raise RuntimeError('Unsupported inspected syscall platform')
header=pathlib.Path('/usr/include/x86_64-linux-gnu/asm/unistd_64.h').read_text()
def number(name):
    m=re.search(r'^#define __NR_'+name+r' (\d+)$',header,re.M)
    if not m: raise RuntimeError('Installed syscall header missing')
    return int(m.group(1))
libc=ctypes.CDLL(None,use_errno=True)
libc.syscall.restype=ctypes.c_long
libc.syscall.argtypes=[ctypes.c_long]
def native_call(n,*args):
    result=libc.syscall(ctypes.c_long(n),*args)
    if result==-1: raise OSError(ctypes.get_errno(),os.strerror(ctypes.get_errno()))
    return result
def pidfd_open(pid): return native_call(number('pidfd_open'),ctypes.c_int(pid),ctypes.c_uint(0))
def pidfd_send_term(fd): return native_call(number('pidfd_send_signal'),ctypes.c_int(fd),ctypes.c_int(signal.SIGTERM),ctypes.c_void_p(None),ctypes.c_uint(0))
def process(pid):
    p=pathlib.Path('/proc')/str(pid)
    if not p.exists(): return None
    suffix=(p/'stat').read_text().rsplit(') ',1)[1].split()
    return {'pid':pid,'state':suffix[0],'start_ticks':suffix[19],'exe':os.readlink(p/'exe'),'cwd':os.readlink(p/'cwd'),'args':(p/'cmdline').read_bytes().decode().strip('\0').split('\0')}
def source_ok():
    info=process(SOURCE['pid'])
    return bool(info and info['start_ticks']==SOURCE['start_ticks'] and info['exe']==SOURCE['exe'] and info['args']==SOURCE['argv'])
def public_state():
    db=sqlite3.connect('file:'+str(DATA/'marlin.sqlite3')+'?mode=ro',uri=True)
    db.row_factory=sqlite3.Row
    columns='id,user_id,name,client_type,created_at,last_seen_at,access_expires_at,idle_expires_at,absolute_expires_at,revoked_at,revoke_reason'
    devices=[dict(r) for r in db.execute('select '+columns+' from device_sessions order by created_at')]
    counts={t:db.execute('select count(*) from '+t).fetchone()[0] for t in ['users','tenants','device_sessions','knowledge_bases','knowledges','chunks','model_usage','desktop_jobs']}
    db.close()
    return {'public_devices':devices,'counts':counts}
if not source_ok(): raise RuntimeError('Original source ownership guard mismatch')
before=public_state()
if before['counts']['device_sessions']!=4 or any(not d['revoked_at'] for d in before['public_devices']): raise RuntimeError('Own QA devices not all durably revoked')
for t in ['knowledge_bases','knowledges','chunks','model_usage','desktop_jobs']:
    if before['counts'][t]!=0: raise RuntimeError('Unexpected own QA business activity')
record={'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'source_guard_before':True,'before':before,'signals':[]}
for binding in reversed(BASE['processes']):
    if not source_ok(): raise RuntimeError('Original source changed before owned stop')
    current=process(binding['pid'])
    if not current or any(current[k]!=binding[k] for k in ['start_ticks','exe','cwd','args']): raise RuntimeError('Owned process binding mismatch')
    fd=pidfd_open(binding['pid'])
    try:
        current2=process(binding['pid'])
        if not current2 or current2['start_ticks']!=binding['start_ticks']: raise RuntimeError('Owned PID reuse detected')
        tick=time.monotonic()
        pidfd_send_term(fd)
        poller=select.poll();poller.register(fd,select.POLLIN)
        exited=bool(poller.poll(20000))
        record['signals'].append({'binding':binding,'signal':'SIGTERM','through':'pidfd','kernel_exit_observed':exited,'wait_duration_ms':round((time.monotonic()-tick)*1000,3),'forced_termination':False})
        if not exited: raise RuntimeError('Owned normal stop not observed; no escalation sent')
    finally: os.close(fd)
record.update({'ended_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'source_guard_after':source_ok(),'after':public_state(),'remaining_own_process_pids':[p['pid'] for p in BASE['processes'] if pathlib.Path('/proc',str(p['pid'])).exists()],'database_files_after':[p.name for p in DATA.iterdir() if p.is_file()],'private_key_read':False,'data_root_retained':True,'browser_commands_after_gui_handover':0})
record['public_auth_state_unchanged_across_stop']=record['before']==record['after']
target=OUT/'158-owned-services-normal-stop.json'
if target.exists():raise FileExistsError(target)
target.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(record,ensure_ascii=False,indent=2))
if not record['source_guard_after'] or not record['public_auth_state_unchanged_across_stop']: raise SystemExit(1)
