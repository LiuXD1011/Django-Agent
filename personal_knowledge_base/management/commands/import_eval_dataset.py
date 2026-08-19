import hashlib
import json

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from personal_knowledge_base.document_processing import create_chunks
from personal_knowledge_base.eval_dataset_registry import DatasetNotFoundError, get_dataset_spec, registered_dataset_ids
from personal_knowledge_base.eval_dataset_sources import load_dataset_payload, normalize_dataset_records
from personal_knowledge_base.models import Knowledge, KnowledgeBase, Tenant


class Command(BaseCommand):
    help = "Normalize a registered evaluation subset, or import its source documents into one tenant knowledge base."

    def add_arguments(self, parser):
        parser.add_argument("--dataset", required=True, choices=registered_dataset_ids())
        parser.add_argument("--dataset-version", dest="dataset_version", default="v1")
        parser.add_argument("--mode", choices=("evaluation", "knowledge-base"), default="evaluation")
        parser.add_argument("--tenant", type=int, help="Tenant primary key; required for knowledge-base mode.")
        parser.add_argument("--knowledge-base", dest="knowledge_base_id", help="Existing tenant knowledge base ID.")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--download", action="store_true", help="Fetch the registered source into its verified cache path.")
        parser.add_argument("--cache-dir", help="Override the evaluation dataset cache root.")

    def handle(self, *args, **options):
        try:
            spec = get_dataset_spec(options["dataset"], options["dataset_version"])
            payload = load_dataset_payload(spec, download=options["download"], cache_dir=options["cache_dir"])
        except (DatasetNotFoundError, ValueError, OSError, json.JSONDecodeError) as exc:
            raise CommandError(str(exc)) from exc
        records = normalize_dataset_records(spec.dataset_id, spec.version, payload)
        ready = [record for record in records if record["status"] == "ready"]
        if options["mode"] == "evaluation":
            self.stdout.write(json.dumps({"dataset_id": spec.dataset_id, "dataset_version": spec.version, "license": spec.license, "source_url": spec.source_url, "sha256": spec.sha256, "cache_path": str(spec.cache_path), "records": records}, ensure_ascii=False))
            return
        tenant_id = options.get("tenant")
        if not tenant_id:
            raise CommandError("--tenant is required for knowledge-base mode")
        tenant = Tenant.objects.filter(pk=tenant_id, deleted_at__isnull=True).first()
        if tenant is None:
            raise CommandError("tenant not found")
        if options["dry_run"]:
            self.stdout.write(self.style.SUCCESS(f"Dry run: {len(ready)} ready records, {len({doc['document_id'] for record in ready for doc in record['documents']})} documents; no data written."))
            return
        with transaction.atomic():
            knowledge_base = self._resolve_knowledge_base(tenant, spec, options.get("knowledge_base_id"))
            imported = self._import_documents(tenant, knowledge_base, spec, ready)
        self.stdout.write(self.style.SUCCESS(f"Imported {imported} documents from {spec.dataset_id}@{spec.version} into knowledge base {knowledge_base.id}."))

    def _resolve_knowledge_base(self, tenant, spec, knowledge_base_id):
        if knowledge_base_id:
            knowledge_base = KnowledgeBase.objects.filter(id=knowledge_base_id, tenant=tenant, deleted_at__isnull=True).first()
            if knowledge_base is None:
                raise CommandError("knowledge base not found for tenant")
            return knowledge_base
        return KnowledgeBase.objects.get_or_create(
            tenant=tenant,
            name=f"eval-dataset:{spec.dataset_id}:{spec.version}",
            defaults={"description": f"Imported source documents for {spec.dataset_id}@{spec.version}", "type": "document"},
        )[0]

    def _import_documents(self, tenant, knowledge_base, spec, records):
        documents = {}
        evidence_by_document = {}
        for record in records:
            for document in record["documents"]:
                documents.setdefault(document["document_id"], document)
            for evidence in record["evidence"]:
                evidence_by_document.setdefault(evidence["document_id"], []).append(evidence)
        imported = 0
        for document_id, document in sorted(documents.items()):
            content = document["text"]
            digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
            file_name = f"{spec.dataset_id}-{spec.version}-{hashlib.sha256(document_id.encode('utf-8')).hexdigest()[:16]}.txt"
            knowledge, created = Knowledge.objects.get_or_create(
                tenant=tenant,
                knowledge_base=knowledge_base,
                type="eval_dataset",
                file_hash=digest,
                file_name=file_name,
                deleted_at__isnull=True,
                defaults={
                    "title": document["title"],
                    "source": f"eval-dataset://{spec.dataset_id}/{spec.version}/{document_id}",
                    "parse_status": "processed",
                    "metadata": {"dataset_id": spec.dataset_id, "dataset_version": spec.version, "document_id": document_id, "source_url": spec.source_url, "license": spec.license, "source_spans": evidence_by_document.get(document_id, [])},
                },
            )
            if created:
                create_chunks(knowledge, content, index=False)
                imported += 1
        return imported
