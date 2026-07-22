from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("personal_knowledge_base", "0013_multimodal_document_images"),
    ]

    operations = [
        migrations.AddField(
            model_name="modelconfig",
            name="fallback_priority",
            field=models.IntegerField(default=0),
        ),
    ]
