from django.contrib import admin

from .models import FarmPaper


@admin.register(FarmPaper)
class FarmPaperAdmin(admin.ModelAdmin):
    list_display = ("title", "business", "kind", "expires_on")
    list_filter = ("kind",)
    search_fields = ("title", "number")
