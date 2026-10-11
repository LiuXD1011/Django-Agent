"""Pure logic/static metadata tests; no Windows/Core/SQL/API or installation."""
import ast
import contextlib
import copy
import hashlib
import io
import json
import tempfile
import types
import unittest
from pathlib import Path

SOURCE=Path("/tmp/marlin-installed-lifecycle-recovery-20261010.py")
m=types.ModuleType("recovery_under_test");m.__file__=str(SOURCE)
exec(compile(SOURCE.read_bytes(),str(SOURCE),"exec"),m.__dict__)
fixtures=json.loads(Path("/home/liuxuedeng/Django-Agent/docs/refactor-evidence/20261010-installed-lifecycle-recovery-parser-baseline-fixtures.json").read_text())

def tables():
    return {name:{"count":2 if name=="device_sessions" else 0,"rows_sha256":hashlib.sha256(name.encode()).hexdigest()} for name in m.TABLES}
def origin(value=None):
    f=copy.deepcopy(fixtures if value is None else value)
    return m.validate_origin(f['receipt'],f['attempt'],f['smoke'],f['auth'],f['files'])
def prior(phase):
    return {'format':m.FORMAT,'state':'verified','phase':m.PHASES[m.PHASES.index(phase)-1],'identity':copy.deepcopy(m.IDENTITY),'reviewed_recovery_sha256':'a'*64,'reviewed_harness_sha256':m.HARNESS_SHA,'original_failed_receipt_sha256':m.FAILED_SHA,'original_proof_files':copy.deepcopy(m.ORIGIN_FILES),'retained_baseline_sha256':'b'*64,'protected_user_qa_handle_still_alive':True,'original_failed_receipt_preserved':True,'old_probes_replayed':False,'paid_model_calls':0,**{name:False for name in ('manual_gui_verified','normal_tray_quit_verified','user_qa_process_stopped','generic_process_kill_used','delete_app_data_requested','automatic_retry_or_resume')}}

class RecoveryLogic(unittest.TestCase):
    def test_actual_refresh_can_change_only_device_rows_without_claiming_old_hash_exact(self):
        before=tables();after=tables();after['device_sessions']['rows_sha256']='a'*64
        self.assertEqual(m.compare_tables(after,before,True),['device_sessions'])
    def test_no_change_has_empty_difference(self):
        self.assertEqual(m.compare_tables(tables(),tables(),False),[])
    def test_no_refresh_cannot_claim_changed_devices(self):
        after=tables();after['device_sessions']['rows_sha256']='a'*64
        with self.assertRaises(m.Refusal):m.compare_tables(after,tables(),False)
    def test_any_other_table_and_changed_device_count_are_refused(self):
        for table in m.TABLES:
            with self.subTest(table=table):
                after=tables()
                if table=='device_sessions':after[table]['count']+=1
                else:after[table]['rows_sha256']='a'*64
                with self.assertRaises(m.Refusal):m.compare_tables(after,tables(),True)
    def test_table_projection_rejects_missing_tables_boolean_count_and_malformed_sha(self):
        for edit in [lambda v:v.pop('sessions'),lambda v:v['users'].update(count=True),lambda v:v['users'].update(rows_sha256='short')]:
            after=tables();edit(after)
            with self.assertRaises(m.Refusal):m.compare_tables(after,tables(),True)
    def test_current_zero_process_facts_do_not_establish_old_failure_cause(self):
        safe={'candidate_count':0,'cim_available':True,'policy':'Undefined'}
        self.assertEqual(m.validate_process_facts(safe),safe)
    def test_process_count_policy_and_cim_fail_closed(self):
        for edit in [('candidate_count',1),('candidate_count',True),('policy','Restricted'),('policy','InventedPolicy'),('cim_available',False)]:
            value={'candidate_count':0,'cim_available':True,'policy':'Undefined'};value[edit[0]]=edit[1]
            with self.assertRaises(m.Refusal):m.validate_process_facts(value)
    def test_current_process_facts_refuse_private_extra_fields(self):
        with self.assertRaises(m.Refusal):m.validate_process_facts({'candidate_count':0,'cim_available':True,'policy':'Undefined','CommandLine':'not allowed'})
    def test_actual_original_third_safe_metadata_and_hashes_pass_without_replaying(self):
        proof=origin();self.assertEqual(proof['saved_auth']['auth_me_status'],200);self.assertEqual(proof['saved_auth']['knowledge_base_status'],200);self.assertTrue(proof['saved_auth']['normal_refresh_used']);self.assertTrue(proof['hidden_smoke']['complete_owned_tree_exited'])
    def test_original_failure_harness_and_installer_identity_are_exact(self):
        for key,value in [('state','verified'),('error_code','invented_reason'),('reviewed_script_sha256','f'*64),('identity',{})]:
            f=copy.deepcopy(fixtures);f['receipt'][key]=value
            with self.assertRaises(m.Refusal):origin(f)
    def test_missing_or_modified_probe_original_bytes_are_refused(self):
        for edit in [lambda v:v.pop('post-upgrade-saved-auth.json'),lambda v:v['post-upgrade-smoke.log'].update(sha256='a'*64),lambda v:v['post-upgrade.json'].update(bytes=1)]:
            f=copy.deepcopy(fixtures);edit(f['files'])
            with self.assertRaises(m.Refusal):origin(f)
    def test_owned_smoke_tree_and_external_url_cannot_be_relabelled_success(self):
        for edit in [lambda f:f['receipt']['application_probes']['hidden_smoke'].update(owned_job_active_processes=1),lambda f:f['smoke'].update(url='https://foreign.invalid/login'),lambda f:f['smoke']['core'].update(http_listener=True)]:
            f=copy.deepcopy(fixtures);edit(f)
            with self.assertRaises(m.Refusal):origin(f)
    def test_auth_other_owner_missing_refresh_and_model_usage_refused(self):
        for change in [('user_id','other-user'),('normal_refresh_used',False),('network_attempts',1),('constructed_auth_context',True)]:
            f=copy.deepcopy(fixtures);f['auth'][change[0]]=change[1];f['receipt']['application_probes']['saved_auth']=copy.deepcopy(f['auth'])
            with self.assertRaises(m.Refusal):origin(f)
    def test_every_remaining_phase_requires_its_exact_verified_predecessor(self):
        for phase in m.PHASES[1:]:m.validate_prior(prior(phase),phase,'a'*64,'b'*64)
    def test_failed_wrong_phase_changed_baseline_and_changed_root_tool_refused(self):
        for key,value in [('state','failed'),('phase','reinstall'),('retained_baseline_sha256','c'*64),('reviewed_recovery_sha256','c'*64),('reviewed_harness_sha256','c'*64),('original_failed_receipt_sha256','c'*64)]:
            p=prior('uninstall-retain');p[key]=value
            with self.assertRaises(m.Refusal):m.validate_prior(p,'uninstall-retain','a'*64,'b'*64)
    def test_prior_cannot_allow_replay_stop_qa_paid_or_delete_data(self):
        for key,value in [('old_probes_replayed',True),('protected_user_qa_handle_still_alive',False),('original_failed_receipt_preserved',False),('paid_model_calls',1),('delete_app_data_requested',True),('automatic_retry_or_resume',True)]:
            p=prior('uninstall-retain');p[key]=value
            with self.assertRaises(m.Refusal):m.validate_prior(p,'uninstall-retain','a'*64,'b'*64)
    def test_default_review_and_explicit_phase_review_do_not_import_harness(self):
        self.assertFalse(m.parse_args([]).execute_reviewed_phase)
        for phase in m.PHASES:
            output=io.StringIO()
            with contextlib.redirect_stdout(output):m.main(['--phase',phase])
            result=json.loads(output.getvalue());self.assertEqual(result['windows_processes_started'],0);self.assertFalse(result['sqlite_opened']);self.assertFalse(result['installer_or_uninstaller_executed']);self.assertEqual(result['application_or_api_calls'],0)
    def test_execution_requires_explicit_root_hash_and_predecessor(self):
        common=['--execute-reviewed-phase','--reviewed-recovery-sha256','a'*64,'--reviewed-harness-sha256',m.HARNESS_SHA]
        self.assertEqual(m.parse_args(common).phase,'recover-post-upgrade')
        for phase in m.PHASES[1:]:
            with self.assertRaises(m.Refusal):m.parse_args(['--phase',phase,*common])
            self.assertEqual(m.parse_args(['--phase',phase,*common,'--prior-receipt-sha256','b'*64]).prior_receipt_sha256,'b'*64)
        for argv in [['--execute-reviewed-phase'],['--reviewed-recovery-sha256','a'*64],['--unknown'],['--phase','recover-post-upgrade','--phase','reinstall'],['--phase=reinstall'],['--phase','post-upgrade'],['--stage-root','visible-data']]:
            with self.assertRaises(m.Refusal):m.parse_args(argv)
    def test_actual_exclusive_fsync_receipt_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory(prefix='marlin-lifecycle-recovery-static-') as directory:
            path=Path(directory)/'attempt.json';value={'phase':'recover-post-upgrade','automatic_retry_or_resume':False}
            m.durable_write_new(path,value);self.assertEqual(json.loads(path.read_text()),value)
            with self.assertRaises(FileExistsError):m.durable_write_new(path,{'phase':'other'})
            self.assertEqual(json.loads(path.read_text()),value)
    def test_post_reinstall_queries_stopped_scope_before_offline_read(self):
        text=SOURCE.read_text();probe=text.index('report["application_probes"] = h.smoke_and_auth(native, args.phase)');read=text.index('after_probe = h.retained_state()',probe)
        self.assertIn('query_process_facts(h)',text[probe:read],"Current zero-process proof must precede offline read after probes")
    def test_integer_zero_paid_contract_refuses_boolean_false(self):
        p=prior('uninstall-retain');p['paid_model_calls']=False
        with self.assertRaises(m.Refusal):m.validate_prior(p,'uninstall-retain','a'*64,'b'*64)
    def test_static_ast_has_no_old_harness_run_or_generic_process_kill(self):
        tree=ast.parse(SOURCE.read_bytes());attributes=[node.func.attr for node in ast.walk(tree) if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and isinstance(node.func.value,ast.Name) and node.func.value.id=='h']
        self.assertNotIn('run',attributes);self.assertNotIn('main',attributes)
        self.assertEqual(attributes.count('smoke_and_auth'),1)
        text=SOURCE.read_text();self.assertNotIn('taskkill',text.lower());self.assertNotIn('TerminateProcess(',text);self.assertNotIn('delete-app-data',text)

if __name__=='__main__':unittest.main(verbosity=2)
