from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("personal_knowledge_base", "0009_contextsnapshot"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="contextsnapshot",
            constraint=models.UniqueConstraint(
                fields=("session", "mode"),
                condition=models.Q(is_active=True),
                name="uniq_active_context_snapshot",
            ),
        ),
    ]
