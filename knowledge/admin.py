from django.contrib import admin

from .models import ContentExtraction, KBChunk, KBDocument, KnowledgeBase, WikiBuildJob, WikiLink, WikiPage

admin.site.register(ContentExtraction)
admin.site.register(KnowledgeBase)
admin.site.register(KBDocument)
admin.site.register(KBChunk)
admin.site.register(WikiPage)
admin.site.register(WikiLink)
admin.site.register(WikiBuildJob)

# Register your models here.
