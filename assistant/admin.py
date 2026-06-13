from django.contrib import admin

from .models import AgentEvent, AgentRun, ChatMessage, Conversation, ConversationMemory

admin.site.register(Conversation)
admin.site.register(ChatMessage)
admin.site.register(ConversationMemory)
admin.site.register(AgentRun)
admin.site.register(AgentEvent)

# Register your models here.
