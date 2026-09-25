from django.contrib import admin

from .models import Budget


@admin.register(Budget)
class BudgetAdmin(admin.ModelAdmin):
    list_display = ("user", "scope", "category", "amount", "alert_at")
    list_filter = ("scope",)
