from django.contrib import admin

from .models import StoredFile, UploadSession, UserFile

admin.site.register(StoredFile)
admin.site.register(UserFile)
admin.site.register(UploadSession)

# Register your models here.
