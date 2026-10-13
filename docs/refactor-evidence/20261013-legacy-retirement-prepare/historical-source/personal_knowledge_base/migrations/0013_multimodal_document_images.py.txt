from django.db import migrations, models
import django.db.models.deletion
import personal_knowledge_base.models


def purge_legacy_knowledge(apps, schema_editor):
    from django.conf import settings
    from django.core.files.storage import default_storage

    Knowledge = apps.get_model("personal_knowledge_base", "Knowledge")
    rows = list(Knowledge.objects.values("file_path"))
    if rows and settings.NEO4J_ENABLE:
        raise RuntimeError("Run `python manage.py purge_legacy_knowledge --confirm` before migrating while Neo4j is enabled")
    for row in rows:
        if row["file_path"]:
            default_storage.delete(row["file_path"])
    connection = schema_editor.connection
    tables = set(connection.introspection.table_names())
    with connection.cursor() as cursor:
        if "chunks_fts" in tables:
            cursor.execute("DELETE FROM chunks_fts")
        if "chunk_embeddings_vec" in tables:
            cursor.execute("DELETE FROM chunk_embeddings_vec")
    apps.get_model("personal_knowledge_base", "TaskRecord").objects.filter(task_type="process_knowledge").delete()
    apps.get_model("personal_knowledge_base", "WikiPendingOp").objects.all().delete()
    apps.get_model("personal_knowledge_base", "WikiLogEntry").objects.all().delete()
    apps.get_model("personal_knowledge_base", "WikiPage").objects.all().delete()
    apps.get_model("personal_knowledge_base", "WikiFolder").objects.all().delete()
    Knowledge.objects.all().delete()


def irreversible(apps, schema_editor):
    raise RuntimeError("The legacy knowledge purge cannot be reversed")


class Migration(migrations.Migration):
    dependencies = [("personal_knowledge_base", "0012_remove_audio_video_support")]

    operations = [
        migrations.RunPython(purge_legacy_knowledge, reverse_code=irreversible),
        migrations.CreateModel(
            name="KnowledgeImage",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                ("id", models.CharField(default=personal_knowledge_base.models.uuid_str, max_length=36, primary_key=True, serialize=False)),
                ("content_hash", models.CharField(db_index=True, max_length=64)),
                ("storage_path", models.TextField()),
                ("storage_owned", models.BooleanField(default=True)),
                ("mime_type", models.CharField(default="application/octet-stream", max_length=100)),
                ("width", models.IntegerField(default=0)),
                ("height", models.IntegerField(default=0)),
                ("source_type", models.CharField(max_length=32)),
                ("source_ref", models.TextField(blank=True, default="")),
                ("page_index", models.IntegerField(blank=True, null=True)),
                ("block_index", models.IntegerField(default=0)),
                ("status", models.CharField(default="pending", max_length=20)),
                ("ocr_text", models.TextField(blank=True, default="")),
                ("caption", models.TextField(blank=True, default="")),
                ("error_message", models.TextField(blank=True, default="")),
                ("metadata", models.JSONField(default=dict)),
                ("knowledge", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="images", to="personal_knowledge_base.knowledge")),
                ("knowledge_base", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="personal_knowledge_base.knowledgebase")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="personal_knowledge_base.tenant")),
            ],
            options={
                "db_table": "knowledge_images",
                "indexes": [
                    models.Index(fields=["knowledge", "block_index"], name="knowledge_image_order_idx"),
                    models.Index(fields=["tenant", "status"], name="knowledge_image_status_idx"),
                ],
            },
        ),
    ]
