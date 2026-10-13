from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [("personal_knowledge_base", "0018_taskrecord_persistent_queue")]

    operations = [
        migrations.CreateModel(
            name="ModelRateLimitState",
            fields=[
                ("key", models.CharField(max_length=255, primary_key=True, serialize=False)),
                ("provider", models.CharField(max_length=64)),
                ("model_id", models.CharField(max_length=128)),
                ("available_tokens", models.FloatField(default=0)),
                ("capacity", models.FloatField(default=0)),
                ("refill_per_second", models.FloatField(default=0)),
                ("last_refill_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("blocked_until", models.DateTimeField(blank=True, null=True)),
            ],
            options={
                "db_table": "model_rate_limit_state",
                "indexes": [models.Index(fields=["provider", "model_id"], name="model_rate_provider_idx")],
            },
        ),
    ]
