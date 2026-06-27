from django.db import migrations, models
import django.db.models.deletion
import personal_knowledge_base.models


def clear_legacy_graph_state(apps, schema_editor):
    Knowledge = apps.get_model("personal_knowledge_base", "Knowledge")
    Chunk = apps.get_model("personal_knowledge_base", "Chunk")
    Chunk.objects.update(relation_chunks=None, indirect_relation_chunks=None)
    for item in Knowledge.objects.exclude(metadata__isnull=True):
        metadata = dict(item.metadata or {})
        if "graph" not in metadata:
            continue
        metadata.pop("graph", None)
        item.metadata = metadata
        item.save(update_fields=["metadata"])


class Migration(migrations.Migration):

    dependencies = [
        ("personal_knowledge_base", "0002_message_attachments"),
    ]

    operations = [
        migrations.CreateModel(
            name="ModelUsage",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                ("id", models.CharField(default=personal_knowledge_base.models.uuid_str, max_length=36, primary_key=True, serialize=False)),
                ("model_id", models.CharField(blank=True, default="", max_length=128)),
                ("model_name", models.CharField(blank=True, default="", max_length=255)),
                ("model_type", models.CharField(blank=True, default="", max_length=50)),
                ("provider", models.CharField(blank=True, default="", max_length=64)),
                ("scenario", models.CharField(blank=True, default="", max_length=64)),
                ("success", models.BooleanField(default=True)),
                ("request_count", models.IntegerField(default=1)),
                ("prompt_tokens", models.IntegerField(default=0)),
                ("completion_tokens", models.IntegerField(default=0)),
                ("total_tokens", models.IntegerField(default=0)),
                ("cached_tokens", models.IntegerField(default=0)),
                ("duration_ms", models.IntegerField(default=0)),
                ("error_message", models.TextField(blank=True, default="")),
                ("metadata", models.JSONField(default=dict)),
                ("tenant", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to="personal_knowledge_base.tenant")),
            ],
            options={
                "db_table": "model_usage",
                "indexes": [
                    models.Index(fields=["tenant", "created_at"], name="model_usage_tenant__ad5fe5_idx"),
                    models.Index(fields=["tenant", "model_type"], name="model_usage_tenant__b6e49d_idx"),
                    models.Index(fields=["tenant", "model_id"], name="model_usage_tenant__40f12b_idx"),
                    models.Index(fields=["tenant", "scenario"], name="model_usage_tenant__16d85b_idx"),
                ],
            },
        ),
        migrations.RunPython(clear_legacy_graph_state, migrations.RunPython.noop),
    ]
