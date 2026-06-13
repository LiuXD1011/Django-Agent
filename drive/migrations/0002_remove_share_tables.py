from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("drive", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
            DROP TABLE IF EXISTS shares_shareitem;
            DROP TABLE IF EXISTS shares_share;
            DELETE FROM auth_permission
            WHERE content_type_id IN (
                SELECT id FROM django_content_type WHERE app_label = 'shares'
            );
            DELETE FROM django_content_type WHERE app_label = 'shares';
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
