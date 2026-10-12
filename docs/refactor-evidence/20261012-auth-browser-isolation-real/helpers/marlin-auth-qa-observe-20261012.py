import datetime
import json
import pathlib
import sqlite3
import sys

ROOT = pathlib.Path('/home/liuxuedeng/Django-Agent')
OUT = ROOT / 'docs/refactor-evidence/20261012-auth-browser-isolation-real'
DATA = pathlib.Path('/home/liuxuedeng/.local/share/marlin-refactor/20261012-auth-browser-isolation')

def observe(label):
    clock = datetime.datetime.now(datetime.timezone.utc)
    connection = sqlite3.connect('file:'+str(DATA/'marlin.sqlite3')+'?mode=ro', uri=True)
    connection.row_factory = sqlite3.Row
    devices = [dict(row) for row in connection.execute('select id,user_id,name,client_type,created_at,last_seen_at,access_expires_at,idle_expires_at,absolute_expires_at,revoked_at,revoke_reason from device_sessions order by created_at')]
    for device in devices:
        device['access_expired_at_observation'] = datetime.datetime.fromisoformat(device['access_expires_at'].replace('Z', '+00:00')) < clock
    users = [dict(row) for row in connection.execute('select id,username,email,tenant_id,is_system_admin,created_at from users order by created_at')]
    counts = {table: connection.execute('select count(*) from '+table).fetchone()[0] for table in ['users','tenants','device_sessions','knowledge_bases','knowledges','chunks','model_usage','desktop_jobs']}
    connection.close()
    record = {'observed_at': clock.isoformat(), 'devices': devices, 'users': users, 'counts': counts, 'database_access': 'readonly select explicit public columns; no credentials/digests', 'original_source_process_alive': pathlib.Path('/proc/2245508').exists()}
    destination = OUT/(label+'.json')
    if destination.exists(): raise FileExistsError(destination)
    destination.write_text(json.dumps(record, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(record, ensure_ascii=False))

if __name__ == '__main__': observe(sys.argv[1])
