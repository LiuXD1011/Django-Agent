from django.test import TestCase, override_settings

from .models import Knowledge, KnowledgeBase, Tenant
from .span_tracker import SpanTracker


@override_settings(LANGFUSE_ENABLED=False)
class SpanTrackerAttemptTests(TestCase):
    def setUp(self):
        tenant = Tenant.objects.create(name='Span audit', api_key='span-audit-fixture')
        kb = KnowledgeBase.objects.create(tenant=tenant, name='Span audit')
        self.knowledge = Knowledge.objects.create(tenant=tenant, knowledge_base=kb, type='file', title='fixture', source='fixture.md')

    def test_reparse_finalizes_its_own_root_when_attempt_number_is_reused(self):
        first = SpanTracker(self.knowledge.id)
        original = first.open_attempt()
        first.finalize_attempt()
        original.refresh_from_db()
        original_finished = original.finished_at
        reparse = SpanTracker(self.knowledge.id)
        current = reparse.open_attempt()
        reparse.finalize_attempt()
        current.refresh_from_db()
        original.refresh_from_db()
        self.assertEqual(current.status, 'done')
        self.assertIsNotNone(current.finished_at)
        self.assertEqual(original.finished_at, original_finished)
