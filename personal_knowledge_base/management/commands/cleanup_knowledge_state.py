import json

from django.core.management.base import BaseCommand, CommandError

from personal_knowledge_base.knowledge_cleanup import execute_knowledge_cleanup, plan_knowledge_cleanup


class Command(BaseCommand):
    help = "Plan duplicate knowledge and stale task cleanup; execute only with --confirm."

    def add_arguments(self, parser):
        parser.add_argument("--confirm", action="store_true")

    def handle(self, *args, **options):
        plan = plan_knowledge_cleanup()
        summary = {
            "keep": {"count": len(plan.keep_ids), "ids": plan.keep_ids},
            "delete": {"count": len(plan.delete_ids), "ids": plan.delete_ids},
            "invalid_tasks": {"count": len(plan.invalid_task_ids), "ids": plan.invalid_task_ids},
            "superseded_tasks": {"count": len(plan.superseded_task_ids), "ids": plan.superseded_task_ids},
        }
        self.stdout.write(json.dumps(summary, ensure_ascii=False, indent=2))
        if not options["confirm"]:
            return

        result = execute_knowledge_cleanup(plan)
        rendered = json.dumps(result, ensure_ascii=False, indent=2)
        self.stdout.write(rendered)
        if result["errors"]:
            raise CommandError(f"Knowledge cleanup completed with errors: {rendered}")
