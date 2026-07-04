import django.db.models.deletion
import personal_knowledge_base.models
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("personal_knowledge_base", "0008_knowledgeprocessingspan"),
    ]

    operations = [
        migrations.CreateModel(
            name="ContextSnapshot",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                (
                    "id",
                    models.CharField(
                        default=personal_knowledge_base.models.uuid_str,
                        max_length=36,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("mode", models.CharField(max_length=32)),
                ("boundary_message_id", models.CharField(blank=True, default="", max_length=36)),
                ("boundary_created_at", models.DateTimeField(blank=True, null=True)),
                ("content", models.TextField(blank=True, default="")),
                ("key_info", models.JSONField(default=list)),
                ("summary", models.TextField(blank=True, default="")),
                ("token_before", models.IntegerField(default=0)),
                ("token_after", models.IntegerField(default=0)),
                ("source_message_count", models.IntegerField(default=0)),
                ("is_active", models.BooleanField(default=True)),
                (
                    "session",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="context_snapshots",
                        to="personal_knowledge_base.session",
                    ),
                ),
            ],
            options={
                "db_table": "context_snapshots",
                "indexes": [
                    models.Index(fields=["session", "mode", "is_active"], name="ctx_snapshot_active_idx"),
                    models.Index(fields=["boundary_created_at"], name="ctx_snapshot_boundary_idx"),
                ],
            },
        ),
    ]
