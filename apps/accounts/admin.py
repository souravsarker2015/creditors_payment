from django.contrib import admin
from .models import UserProfile


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "theme_mode", "accent", "language")
    list_filter = ("theme_mode", "accent", "language")
    search_fields = ("user__username",)
