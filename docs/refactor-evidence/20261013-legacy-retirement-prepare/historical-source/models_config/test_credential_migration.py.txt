"""Exercise legacy plaintext conversion and reversible migration on a test database."""
from pathlib import Path
from tempfile import TemporaryDirectory

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase, override_settings


class CredentialMigrationTests(TransactionTestCase):
    def test_forward_backward_and_forward_again(self):
        old = [('personal_knowledge_base', '0024_tenant_model_thinking_config')]
        new = [('personal_knowledge_base', '0025_encrypted_credentials')]
        with TemporaryDirectory() as directory, override_settings(APP_DATA_DIR=Path(directory)):
            executor = MigrationExecutor(connection)
            latest = executor.loader.graph.leaf_nodes()
            try:
                executor.migrate(old)
                apps = executor.loader.project_state(old).apps
                tenant = apps.get_model('personal_knowledge_base', 'Tenant').objects.create(name='migration', api_key='fixture-tenant', credentials={'api_key': 'legacy-tenant-fixture'})
                apps.get_model('personal_knowledge_base', 'ModelConfig').objects.create(id='migration-fixture', tenant=tenant, name='fixture', parameters={'api_key': 'legacy-model-fixture', 'model': 'fixture'})
                def raw():
                    with connection.cursor() as cursor:
                        cursor.execute('SELECT parameters FROM models WHERE id = %s', ['migration-fixture'])
                        return cursor.fetchone()[0]
                self.assertIn('legacy-model-fixture', raw())
                executor = MigrationExecutor(connection)
                executor.migrate(new)
                self.assertNotIn('legacy-model-fixture', raw())
                self.assertIn('enc:v1:', raw())
                apps = executor.loader.project_state(new).apps
                model = apps.get_model('personal_knowledge_base', 'ModelConfig').objects.get(pk='migration-fixture')
                self.assertEqual(model.parameters['api_key'], 'legacy-model-fixture')
                self.assertEqual(apps.get_model('personal_knowledge_base', 'Tenant').objects.get(pk=tenant.pk).credentials['api_key'], 'legacy-tenant-fixture')
                MigrationExecutor(connection).migrate(old)
                self.assertIn('legacy-model-fixture', raw())
                self.assertNotIn('enc:v1:', raw())
                MigrationExecutor(connection).migrate(new)
                self.assertNotIn('legacy-model-fixture', raw())
            finally:
                MigrationExecutor(connection).migrate(latest)
