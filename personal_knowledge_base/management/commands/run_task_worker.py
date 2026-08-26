import os
import socket
import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from personal_knowledge_base.models import TaskRecord
from personal_knowledge_base.tasks import run_persisted_task


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
        queues = options["queues"]
        worker_id = f"{socket.gethostname()}:{os.getpid()}"
        self.stdout.write(f"task worker {worker_id} listening on {', '.join(queues)}")
        while True:
            close_old_connections()
            record = (
                TaskRecord.objects.filter(status="pending", queue_name__in=queues)
                .order_by("created_at", "id")
                .first()
            )
            if record is not None:
                run_persisted_task(record.id)
                continue
            if options["once"]:
                return
            time.sleep(max(0.1, options["poll_interval"]))
