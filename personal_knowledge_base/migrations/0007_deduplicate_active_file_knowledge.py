from django.db import migrations, models
from django.db.models import Q
from django.utils import timezone


def _table_exists(connection, name):
    return name in connection.introspection.table_names()


def deduplicate_active_file_knowledge(apps, schema_editor):
    Knowledge = apps.get_model("personal_knowledge_base", "Knowledge")
    Chunk = apps.get_model("personal_knowledge_base", "Chunk")
    connection = schema_editor.connection

    duplicates = (
        Knowledge.objects.filter(deleted_at__isnull=True, type="file")
        .exclude(file_hash="")
        .exclude(file_name="")
        .values("knowledge_base_id", "file_hash", "file_name")
        .annotate(count=models.Count("id"))
        .filter(count__gt=1)
    )
    now = timezone.now()
    for group in duplicates:
        rows = list(
            Knowledge.objects.filter(
                deleted_at__isnull=True,
                type="file",
                knowledge_base_id=group["knowledge_base_id"],
                file_hash=group["file_hash"],
                file_name=group["file_name"],
            ).order_by("created_at", "id")
        )
        for item in rows[1:]:
            chunk_rows = list(Chunk.objects.filter(knowledge_id=item.id).values_list("id", "seq_id"))
            chunk_ids = [row[0] for row in chunk_rows]
            if chunk_ids and _table_exists(connection, "chunks_fts"):
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"DELETE FROM chunks_fts WHERE chunk_id IN ({','.join(['%s'] * len(chunk_ids))})",
                        chunk_ids,
                    )
            seq_ids = [row[1] for row in chunk_rows if row[1]]
            if seq_ids and _table_exists(connection, "chunk_embeddings_vec"):
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"DELETE FROM chunk_embeddings_vec WHERE rowid IN ({','.join(['%s'] * len(seq_ids))})",
                        seq_ids,
                    )
            Chunk.objects.filter(knowledge_id=item.id).delete()
            item.deleted_at = now
            item.parse_status = "cancelled"
            item.error_message = "duplicate file removed by migration"
            item.save(update_fields=["deleted_at", "parse_status", "error_message", "updated_at"])


class Migration(migrations.Migration):

    dependencies = [
        ("personal_knowledge_base", "0006_remove_legacy_builtin_models"),
    ]

    operations = [
        migrations.RunPython(deduplicate_active_file_knowledge, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="knowledge",
            constraint=models.UniqueConstraint(
                fields=("knowledge_base", "file_hash", "file_name"),
                condition=Q(deleted_at__isnull=True, type="file", file_hash__gt="", file_name__gt=""),
                name="uniq_active_kb_file_hash_name",
            ),
        ),
    ]
