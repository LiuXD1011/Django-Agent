from django.conf import settings
from django.db import models


class Conversation(models.Model):
    STATUS_ACTIVE = "active"
    STATUS_ARCHIVED = "archived"
    STATUS_CHOICES = (
        (STATUS_ACTIVE, "活跃"),
        (STATUS_ARCHIVED, "已归档"),
    )

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="conversations")
    title = models.CharField(max_length=120, default="新对话")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    default_kb = models.ForeignKey(
        "knowledge.KnowledgeBase",
        on_delete=models.SET_NULL,
        related_name="assistant_conversations",
        null=True,
        blank=True,
    )
    default_use_drive = models.BooleanField(default=False)
    checkpoint = models.TextField(blank=True)
    last_checkpoint_message = models.ForeignKey(
        "assistant.ChatMessage",
        on_delete=models.SET_NULL,
        related_name="+",
        null=True,
        blank=True,
    )
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-created_at"]
        indexes = [
            models.Index(fields=["user", "status", "-updated_at"], name="assistant_c_user_id_4de3d4_idx"),
        ]

    def __str__(self):
        return self.title


class ChatMessage(models.Model):
    AGENT_ASSISTANT = "assistant"
    AGENT_CHOICES = ((AGENT_ASSISTANT, "AI助手"),)
    ROLE_USER = "user"
    ROLE_ASSISTANT = "assistant"
    ROLE_CHOICES = ((ROLE_USER, "用户"), (ROLE_ASSISTANT, "助手"))

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="chat_messages")
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="messages",
        null=True,
        blank=True,
    )
    agent_type = models.CharField(max_length=16, choices=AGENT_CHOICES, default=AGENT_ASSISTANT)
    role = models.CharField(max_length=16, choices=ROLE_CHOICES)
    content = models.TextField()
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["user", "agent_type", "created_at"]),
            models.Index(fields=["conversation", "created_at"], name="assistant_c_convers_2fcd8e_idx"),
        ]


class ConversationMemory(models.Model):
    SCOPE_USER = "user"
    SCOPE_KB = "kb"
    SCOPE_CHOICES = (
        (SCOPE_USER, "用户记忆"),
        (SCOPE_KB, "知识库记忆"),
    )
    STATUS_ACTIVE = "active"
    STATUS_ARCHIVED = "archived"
    STATUS_CHOICES = (
        (STATUS_ACTIVE, "启用"),
        (STATUS_ARCHIVED, "已归档"),
    )
    KIND_FACT = "fact"
    KIND_PREFERENCE = "preference"
    KIND_DECISION = "decision"
    KIND_TASK = "task"
    KIND_CHOICES = (
        (KIND_FACT, "事实"),
        (KIND_PREFERENCE, "偏好"),
        (KIND_DECISION, "决策"),
        (KIND_TASK, "任务"),
    )

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="conversation_memories")
    kb = models.ForeignKey(
        "knowledge.KnowledgeBase",
        on_delete=models.CASCADE,
        related_name="conversation_memories",
        null=True,
        blank=True,
    )
    scope = models.CharField(max_length=16, choices=SCOPE_CHOICES, default=SCOPE_USER)
    kind = models.CharField(max_length=24, choices=KIND_CHOICES, default=KIND_FACT)
    content = models.TextField()
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    source_conversation = models.ForeignKey(
        Conversation,
        on_delete=models.SET_NULL,
        related_name="memory_items",
        null=True,
        blank=True,
    )
    source_message = models.ForeignKey(
        ChatMessage,
        on_delete=models.SET_NULL,
        related_name="memory_items",
        null=True,
        blank=True,
    )
    content_hash = models.CharField(max_length=64, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-created_at"]
        indexes = [
            models.Index(fields=["user", "scope", "status", "-updated_at"], name="assistant_c_user_id_692651_idx"),
            models.Index(fields=["kb", "status", "-updated_at"], name="assistant_c_kb_id_279e76_idx"),
            models.Index(fields=["content_hash"], name="assistant_c_content_7d07ba_idx"),
        ]

    def __str__(self):
        return self.content[:80]


class AgentRun(models.Model):
    STATUS_RUNNING = "running"
    STATUS_SUCCESS = "success"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = (
        (STATUS_RUNNING, "运行中"),
        (STATUS_SUCCESS, "成功"),
        (STATUS_FAILED, "失败"),
    )

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="agent_runs")
    parent_run = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        related_name="child_runs",
        null=True,
        blank=True,
    )
    agent_name = models.CharField(max_length=64)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_RUNNING)
    input = models.JSONField(default=dict, blank=True)
    output = models.JSONField(default=dict, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["user", "-started_at"], name="assistant_a_user_id_863df0_idx"),
            models.Index(fields=["parent_run", "agent_name"], name="assistant_a_parent_0a4e40_idx"),
            models.Index(fields=["agent_name", "status"], name="assistant_a_agent_n_6e9639_idx"),
        ]

    def __str__(self):
        return f"{self.agent_name} {self.status}"


class AgentEvent(models.Model):
    run = models.ForeignKey(AgentRun, on_delete=models.CASCADE, related_name="events")
    event_type = models.CharField(max_length=64)
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["run", "created_at"], name="assistant_a_run_id_c186b3_idx"),
            models.Index(fields=["event_type", "created_at"], name="assistant_a_event_t_ed5380_idx"),
        ]

    def __str__(self):
        return self.event_type

# Create your models here.
