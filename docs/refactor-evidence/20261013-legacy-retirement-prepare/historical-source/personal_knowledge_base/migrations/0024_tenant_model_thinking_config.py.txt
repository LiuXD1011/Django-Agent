from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("personal_knowledge_base", "0023_modelusage_request_id")]
    operations = [
        migrations.AddField(model_name="tenant", name="model_thinking_config",
                            field=models.JSONField(default=dict)),
    ]
