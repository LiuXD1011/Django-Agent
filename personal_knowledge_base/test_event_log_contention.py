from unittest.mock import patch

from django.db import OperationalError
from django.test import TestCase

from .event_log import MAINTENANCE_STEP, append_event
from .models import Session, SessionEvent, Tenant


class EventLogContentionTests(TestCase):
    def setUp(self):
        tenant = Tenant.objects.create(name='Event audit', api_key='event-audit-fixture')
        self.session = Session.objects.create(tenant=tenant, title='Event audit')

    def test_transient_lock_retries_and_keeps_a_contiguous_sequence(self):
        create = SessionEvent.objects.create
        calls = []

        def locked_once(**kwargs):
            calls.append(kwargs['seq'])
            if len(calls) == 1:
                raise OperationalError('database is locked')
            return create(**kwargs)

        with patch.object(SessionEvent.objects, 'create', side_effect=locked_once), patch('personal_knowledge_base.event_log.time.sleep'):
            event = append_event(self.session, 'fixture-turn', MAINTENANCE_STEP, {'step': 'summary'})
        self.assertIsNotNone(event)
        self.assertEqual(event.seq, 1)
        self.assertEqual(calls, [1, 1])
        self.session.refresh_from_db()
        self.assertEqual(self.session.event_seq, 1)
        self.assertEqual(SessionEvent.objects.filter(session=self.session).count(), 1)

    def test_permanent_lock_is_bounded_and_does_not_advance_sequence(self):
        with patch.object(SessionEvent.objects, 'create', side_effect=OperationalError('database is locked')) as create, patch('personal_knowledge_base.event_log.time.sleep'):
            self.assertIsNone(append_event(self.session, 'fixture-turn', MAINTENANCE_STEP, {}))
        self.assertEqual(create.call_count, 4)
        self.session.refresh_from_db()
        self.assertEqual(self.session.event_seq, 0)

    def test_unrelated_database_failure_is_not_retried(self):
        with patch.object(SessionEvent.objects, 'create', side_effect=OperationalError('no such table')) as create, patch('personal_knowledge_base.event_log.time.sleep') as sleep:
            self.assertIsNone(append_event(self.session, 'fixture-turn', MAINTENANCE_STEP, {}))
        self.assertEqual(create.call_count, 1)
        sleep.assert_not_called()
