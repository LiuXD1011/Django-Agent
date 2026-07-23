from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("personal_knowledge_base", "0014_modelconfig_fallback_priority"),
    ]

    operations = [
        migrations.RenameField(
            model_name="chunk",
            old_name="parent_chunk_id",
            new_name="media_parent_id",
        ),
        migrations.AlterField(
            model_name="chunk",
            name="media_parent_id",
            field=models.CharField(blank=True, db_index=True, max_length=36, null=True),
        ),
        migrations.AddField(
            model_name="chunk",
            name="anchor_chunk_id",
            field=models.CharField(blank=True, db_index=True, max_length=36, null=True),
        ),
        migrations.AddField(
            model_name="chunk",
            name="chunking_version",
            field=models.CharField(blank=True, default="", max_length=32),
        ),
        migrations.AddField(
            model_name="chunk",
            name="context_header",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="chunk",
            name="context_parent_id",
            field=models.CharField(blank=True, db_index=True, max_length=36, null=True),
        ),
        migrations.AddIndex(
            model_name="chunk",
            index=models.Index(fields=["knowledge", "chunk_type"], name="chunk_knowledge_type_idx"),
        ),
    ]
