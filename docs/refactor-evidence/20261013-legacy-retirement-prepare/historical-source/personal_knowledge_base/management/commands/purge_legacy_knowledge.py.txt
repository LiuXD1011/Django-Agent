from django.core.management.base import BaseCommand, CommandError

from personal_knowledge_base.legacy_cleanup import purge_legacy_knowledge


class Command(BaseCommand):
    help = "Irreversibly delete all legacy knowledge, indexes, wiki data, graphs, and tracked files."

    def add_arguments(self, parser):
        parser.add_argument("--confirm", action="store_true")

    def handle(self, *args, **options):
        if not options["confirm"]:
            raise CommandError("Refusing destructive cleanup without --confirm")
        try:
            result = purge_legacy_knowledge()
        except RuntimeError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            self.style.SUCCESS(
                f"Deleted {result['knowledge_deleted']} knowledge records and {result['files_deleted']} tracked files."
            )
        )
