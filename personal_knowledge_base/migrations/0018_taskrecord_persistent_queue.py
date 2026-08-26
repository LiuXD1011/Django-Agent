from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("personal_knowledge_base", "0017_stream_persistence")]

    operations = [
        migrations.AddField(
            model_name="taskrecord",
            name="queue_name",
            field=models.CharField(db_index=True, default="default", max_length=32),
        ),
        migrations.AddField(
            model_name="taskrecord",
            name="lease_expires_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="taskrecord",
            name="attempt_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="taskrecord",
            name="cancel_requested_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="taskrecord",
            name="claimed_by",
            field=models.CharField(blank=True, default="", max_length=128),
        ),
    ]
