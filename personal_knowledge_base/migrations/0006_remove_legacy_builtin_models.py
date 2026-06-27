from django.db import migrations


def remove_legacy_builtin_models(apps, schema_editor):
    ModelConfig = apps.get_model("personal_knowledge_base", "ModelConfig")
    ModelConfig.objects.filter(id__startswith="builtin-local-").delete()
    ModelConfig.objects.filter(name__in=["local-fallback", "stable-hash"], is_builtin=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("personal_knowledge_base", "0005_weknora_wiki_ingest"),
    ]

    operations = [
        migrations.RunPython(remove_legacy_builtin_models, migrations.RunPython.noop),
    ]
