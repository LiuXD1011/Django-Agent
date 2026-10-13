from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("personal_knowledge_base", "0016_semantic_chunk_cache"),
    ]

    operations = [
        migrations.CreateModel(
            name="StreamState",
            fields=[
                ("message_id", models.CharField(max_length=36, primary_key=True, serialize=False)),
                ("session_id", models.CharField(db_index=True, max_length=36)),
                ("is_complete", models.BooleanField(default=False)),
                ("is_error", models.BooleanField(default=False)),
                ("error_message", models.TextField(blank=True, default="")),
                ("final_content", models.TextField(blank=True, default="")),
                ("final_refs", models.JSONField(default=list)),
                ("final_steps", models.JSONField(default=list)),
                ("final_duration_ms", models.IntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"db_table": "stream_states"},
        ),
        migrations.CreateModel(
            name="StreamEventRecord",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("message_id", models.CharField(max_length=36)),
                ("session_id", models.CharField(db_index=True, max_length=36)),
                ("event_type", models.CharField(max_length=32)),
                ("data", models.JSONField(default=dict)),
                ("offset", models.PositiveIntegerField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"db_table": "stream_events"},
        ),
        migrations.AddConstraint(
            model_name="streameventrecord",
            constraint=models.UniqueConstraint(
                fields=("message_id", "offset"),
                name="stream_event_message_offset_unique",
            ),
        ),
        migrations.AddIndex(
            model_name="streameventrecord",
            index=models.Index(fields=("message_id", "offset"), name="stream_event_message_idx"),
        ),
    ]
