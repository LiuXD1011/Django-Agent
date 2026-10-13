import json

from django.core.management.base import BaseCommand, CommandError

from personal_knowledge_base.eval_dataset_registry import DatasetNotFoundError, get_dataset_spec, registered_dataset_ids
from personal_knowledge_base.open_rag_benchmark import dataset_metadata, prepare_open_rag_dataset


class Command(BaseCommand):
    help = "Inspect or synchronously prepare the read-only Open RAG evaluation cache."

    def add_arguments(self, parser):
        parser.add_argument("--dataset", required=True, choices=registered_dataset_ids())
        parser.add_argument("--dataset-version", dest="dataset_version", default="arxiv-v1")
        parser.add_argument("--mode", choices=("evaluation", "knowledge-base"), default="evaluation")
        parser.add_argument("--tenant", type=int, help="Deprecated and ignored for public dataset preparation.")
        parser.add_argument("--knowledge-base", dest="knowledge_base_id", help="Deprecated and ignored.")
        parser.add_argument("--dry-run", action="store_true", help="Print metadata without preparing the cache.")
        parser.add_argument("--download", action="store_true", help="Prepare the pinned Open RAG cache now.")
        parser.add_argument("--cache-dir", help="Deprecated; the cache root is fixed by the manifest.")

    def handle(self, *args, **options):
        if options["mode"] == "knowledge-base":
            raise CommandError("public evaluation datasets are read-only and cannot be imported into a tenant knowledge base")
        try:
            spec = get_dataset_spec(options["dataset"], options["dataset_version"])
        except DatasetNotFoundError as exc:
            raise CommandError(str(exc)) from exc
        if options["download"] and not options["dry_run"]:
            result = prepare_open_rag_dataset(spec)
            self.stdout.write(json.dumps({**dataset_metadata(spec), **result}, ensure_ascii=False))
            return
        self.stdout.write(json.dumps(dataset_metadata(spec), ensure_ascii=False))
