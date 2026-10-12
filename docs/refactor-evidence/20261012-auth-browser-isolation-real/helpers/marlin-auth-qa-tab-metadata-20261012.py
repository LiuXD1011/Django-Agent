import datetime
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path('/home/liuxuedeng/Django-Agent')
OUT = ROOT / 'docs/refactor-evidence/20261012-auth-browser-isolation-real'
OWN_PROFILES = {'f97e4ab1-3837-49fd-881a-45ebecd5d211','a372a0fd-72c3-4efe-b908-855756682c3c'}

def inspect(label):
    args = ['orca-ide', 'tab', 'list', '--worktree', 'all', '--json']
    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=60)
    data = json.loads(result.stdout[result.stdout.find('{'):])
    tabs = data.get('result', {}).get('tabs', [])
    fields = ['browserPageId','index','url','title','active','worktreeId','profileId','profileLabel']
    owned = [{key: tab.get(key) for key in fields} for tab in tabs if tab.get('profileId') in OWN_PROFILES]
    backup = [{key: tab.get(key) for key in fields} for tab in tabs if tab.get('browserPageId') == '9189275e-8517-421e-a990-0777181930e5']
    unknown_blank = [{'browserPageId': tab.get('browserPageId'), 'profileId': tab.get('profileId')} for tab in tabs if tab.get('url') == 'about:blank' and tab.get('profileId') not in OWN_PROFILES]
    record = {'observed_at': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'arguments': args, 'exit_code': result.returncode, 'ok': data.get('ok'), 'error': data.get('error'), 'total_tabs': len(tabs), 'owned_profile_tabs': owned, 'authorized_backup_page': backup, 'other_about_blank_ids_ownership_unknown': unknown_blank, 'other_tab_details_persisted': False, 'gui_mutations_sent': 0}
    destination = OUT/(label+'.json')
    if destination.exists(): raise FileExistsError(destination)
    destination.write_text(json.dumps(record, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(record, ensure_ascii=False, indent=2))

if __name__ == '__main__': inspect(sys.argv[1])
