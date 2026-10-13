from django.core.management.base import BaseCommand

from personal_knowledge_base.document_processing import relink_knowledge_chunks
from personal_knowledge_base.models import Chunk, Knowledge


class Command(BaseCommand):
    help = "按当前可检索块集合重算 chunk 的 pre/next 链路，修复指向禁用块/父块/媒体容器的历史数据。"

    def add_arguments(self, parser):
        parser.add_argument("--knowledge-id", action="append", default=[], help="只处理指定文档（可多次传入）")
        parser.add_argument("--knowledge-base-id", default="", help="只处理指定知识库")
        parser.add_argument("--dry-run", action="store_true", help="只统计需要修正的块数，不写库")

    def handle(self, *args, **options):
        knowledge_ids = [str(value) for value in options["knowledge_id"]]
        knowledge_base_id = str(options["knowledge_base_id"] or "")
        dry_run = bool(options["dry_run"])

        queryset = Knowledge.objects.filter(deleted_at__isnull=True)
        if knowledge_ids:
            queryset = queryset.filter(id__in=knowledge_ids)
        if knowledge_base_id:
            queryset = queryset.filter(knowledge_base_id=knowledge_base_id)

        total_knowledge = 0
        total_fixed = 0
        for knowledge in queryset.iterator():
            total_knowledge += 1
            if dry_run:
                before = self._broken_count(knowledge)
                total_fixed += before
                if before:
                    self.stdout.write(f"{knowledge.id} {knowledge.title}: {before} 条链路需要修正")
                continue
            fixed = relink_knowledge_chunks(knowledge)
            total_fixed += fixed
            if fixed:
                self.stdout.write(f"{knowledge.id} {knowledge.title}: 修正 {fixed} 条链路")

        scope = "将修正" if dry_run else "已修正"
        self.stdout.write(self.style.SUCCESS(f"检查 {total_knowledge} 个文档，{scope} {total_fixed} 条链路"))

    @staticmethod
    def _broken_count(knowledge: Knowledge) -> int:
        valid_ids = set(
            Chunk.objects.filter(
                knowledge=knowledge,
                deleted_at__isnull=True,
                is_enabled=True,
                chunk_type__in={"text", "image_ocr", "image_caption"},
            ).values_list("id", flat=True)
        )
        broken = 0
        for chunk in Chunk.objects.filter(knowledge=knowledge, deleted_at__isnull=True).iterator():
            for value in (chunk.pre_chunk_id, chunk.next_chunk_id):
                if value and value not in valid_ids:
                    broken += 1
                    break
        return broken
