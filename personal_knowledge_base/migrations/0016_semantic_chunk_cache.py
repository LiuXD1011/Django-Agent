from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("personal_knowledge_base", "0015_chunk_hierarchy"),
    ]

    operations = [
        migrations.CreateModel(
            name="SemanticChunkCache",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("content_hash", models.CharField(max_length=64)),
                ("model_signature", models.CharField(max_length=255)),
                ("algorithm_version", models.CharField(max_length=64)),
                ("window_size", models.PositiveIntegerField()),
                ("percentile", models.FloatField()),
                ("window_inputs", models.JSONField(default=list)),
                ("vectors", models.JSONField(default=list)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"db_table": "semantic_chunk_cache"},
        ),
        migrations.AddConstraint(
            model_name="semanticchunkcache",
            constraint=models.UniqueConstraint(
                fields=("content_hash", "model_signature", "algorithm_version", "window_size", "percentile"),
                name="semantic_cache_unique_key",
            ),
        ),
    ]
