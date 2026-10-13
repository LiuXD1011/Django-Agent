from django.db import migrations, models
import django.db.models.deletion
import personal_knowledge_base.models


class Migration(migrations.Migration):

    dependencies = [
        ("personal_knowledge_base", "0010_contextsnapshot_active_unique"),
    ]

    operations = [
        migrations.AddField(
            model_name="message",
            name="agent_id",
            field=models.CharField(blank=True, default="main", max_length=64),
        ),
        migrations.AddField(
            model_name="message",
            name="visible_to_user",
            field=models.BooleanField(default=True),
        ),
        migrations.AddIndex(
            model_name="message",
            index=models.Index(fields=["session", "agent_id", "created_at"], name="msg_session_agent_idx"),
        ),
        migrations.AddIndex(
            model_name="message",
            index=models.Index(fields=["session", "visible_to_user", "created_at"], name="msg_visible_user_idx"),
        ),
        migrations.CreateModel(
            name="AgentActor",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                ("id", models.CharField(default=personal_knowledge_base.models.uuid_str, max_length=36, primary_key=True, serialize=False)),
                ("parent_actor_id", models.CharField(blank=True, default="", max_length=64)),
                ("actor_id", models.CharField(max_length=64)),
                ("agent_type", models.CharField(max_length=64)),
                ("mode", models.CharField(default="subagent", max_length=32)),
                ("status", models.CharField(default="pending", max_length=32)),
                ("last_outcome", models.CharField(blank=True, default="", max_length=32)),
                ("background", models.BooleanField(default=False)),
                ("tool_whitelist", models.JSONField(default=list)),
                ("input_prompt", models.TextField(blank=True, default="")),
                ("output", models.TextField(blank=True, default="")),
                ("error", models.TextField(blank=True, default="")),
                ("parent_message_id", models.CharField(blank=True, default="", max_length=36)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("metadata", models.JSONField(default=dict)),
                ("session", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="agent_actors", to="personal_knowledge_base.session")),
            ],
            options={
                "db_table": "agent_actors",
                "unique_together": {("session", "actor_id")},
            },
        ),
        migrations.AddIndex(
            model_name="agentactor",
            index=models.Index(fields=["session", "parent_actor_id"], name="actor_session_parent_idx"),
        ),
        migrations.AddIndex(
            model_name="agentactor",
            index=models.Index(fields=["session", "status"], name="actor_session_status_idx"),
        ),
        migrations.AddIndex(
            model_name="agentactor",
            index=models.Index(fields=["parent_message_id"], name="actor_parent_msg_idx"),
        ),
    ]
