import math
import os
import socket
import time

from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections

from personal_knowledge_base.models import TaskRecord
from personal_knowledge_base.task_recovery import run_recovery_round, start_recovery_loop
from personal_knowledge_base.tasks import run_persisted_task


MIN_POLL_INTERVAL = 0.1


def normalised_poll_interval(value) -> float:
    """非法/非有限间隔直接拒绝；正值过小时给安全下界，绝不无限忙等。"""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        raise CommandError(f"--poll-interval must be a number, got {value!r}")
    if not math.isfinite(numeric) or numeric <= 0:
        raise CommandError(f"--poll-interval must be a finite positive number, got {value!r}")
    return max(MIN_POLL_INTERVAL, numeric)


class Command(BaseCommand):
    help = "Run the SQLite-backed persistent task worker."

    def add_arguments(self, parser):
        parser.add_argument(
            "--queue",
            action="append",
            dest="queues",
            required=True,
            choices=("documents", "evaluation", "default"),
            help="Queue to serve. Start separate workers for documents and evaluation.",
        )
        parser.add_argument("--poll-interval", type=float, default=1.0)
        parser.add_argument("--once", action="store_true")

    def handle(self, *args, **options):
        queues = tuple(options["queues"])
        poll_interval = normalised_poll_interval(options["poll_interval"])
        worker_id = f"{socket.gethostname()}:{os.getpid()}"
        self.stdout.write(f"task worker {worker_id} listening on {', '.join(queues)}")

        def drain_pending():
            while True:
                close_old_connections()
                record = (
                    TaskRecord.objects.filter(status="pending", queue_name__in=queues)
                    .order_by("created_at", "id")
                    .first()
                )
                if record is None:
                    return
                run_persisted_task(record.id)

        if options["once"]:
            # 既有 drain 语义：先做一次确定性恢复，把本队列租约过期/遗落的
            # 任务归位，再处理可用 pending 直至空并退出；不启动常驻恢复线程。
            # 恢复轮失败（run_recovery_round 返回 None）必须 CommandError
            # 非零退出——--once 成功报告不得掩盖恢复失败；常驻模式则由
            # loop 在下一周期自动重试。
            if run_recovery_round(queue_names=queues) is None:
                raise CommandError(
                    "startup recovery round failed for queue(s) %s; "
                    "refusing to report a successful --once drain" % (", ".join(queues),)
                )
            drain_pending()
            return

        # 常驻模式：恢复扫描跑在独立 daemon 线程，主循环同步执行长任务或
        # 队列持续繁忙时依然每间隔扫描一次。worker 只恢复自己服务的队列；
        # 启动向重建检查属于 web 的职责，这里不触发。
        recovery_loop = start_recovery_loop(
            queue_names=queues,
            include_startup_reindex_check=False,
        )
        try:
            while True:
                drain_pending()
                time.sleep(poll_interval)
        finally:
            # 命令异常/退出时有限时间停掉自身恢复 loop，不遗留线程。
            recovery_loop.stop()
