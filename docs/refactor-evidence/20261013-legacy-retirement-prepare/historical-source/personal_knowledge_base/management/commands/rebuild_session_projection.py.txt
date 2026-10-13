"""从会话事件重建 Message 投影。

用法：
    python manage.py rebuild_session_projection <session_id> [--apply]

默认 dry-run：只报告会话事件与可重建轮次数量，不改动数据。
--apply 执行重建：删除这些 request_id 对应的消息并从事件重新创建。

校验"事件 > 投影"不变量：在线双写丢失或损坏时，用本命令恢复轨迹事实。
"""

from django.core.management.base import BaseCommand, CommandError

from personal_knowledge_base.event_log import rebuild_projection
from personal_knowledge_base.models import Session, SessionEvent


class Command(BaseCommand):
    help = "从 SessionEvent 事件流重建 Message 投影（默认 dry-run，--apply 落盘）"

    def add_arguments(self, parser):
        parser.add_argument("session_id")
        parser.add_argument("--apply", action="store_true", help="实际执行重建；缺省只报告")

    def handle(self, *args, **options):
        session_id = options["session_id"]
        if not Session.objects.filter(pk=session_id).exists():
            raise CommandError(f"session not found: {session_id}")
        event_count = SessionEvent.objects.filter(session_id=session_id).count()
        if not options["apply"]:
            self.stdout.write(f"session {session_id}: {event_count} events (dry-run, use --apply to rebuild)")
            return
        result = rebuild_projection(session_id)
        self.stdout.write(
            self.style.SUCCESS(
                f"rebuilt session {session_id}: {result['turns_rebuilt']} turns from {result['events_folded']} events"
            )
        )
