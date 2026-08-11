from django.test import TestCase

from personal_knowledge_base.models import Session, StreamEventRecord, Tenant
from personal_knowledge_base.stream_manager import stream_manager


class StreamPersistenceTests(TestCase):
    def test_events_are_recoverable_without_the_original_worker_cache(self):
        tenant = Tenant.objects.create(name="stream tenant", api_key="stream-key")
        session = Session.objects.create(tenant=tenant, title="stream session")
        message_id = "stream-message"

        stream_manager.ensure_stream(message_id, session.id)
        stream_manager.append_event(message_id, "thinking", {"content": "partial"})
        stream_manager.append_event(message_id, "complete", {"content": "done", "done": True})

        self.assertEqual(StreamEventRecord.objects.filter(message_id=message_id).count(), 2)
        with stream_manager._data_lock:
            stream_manager._streams.pop(message_id, None)

        events = stream_manager.get_events(message_id)
        self.assertEqual([event.event_type for event in events], ["thinking", "complete"])
        self.assertEqual(events[-1].data["content"], "done")
        self.assertTrue(stream_manager.is_complete(message_id))
        stream_manager.remove_stream(message_id)
