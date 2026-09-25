from django.contrib import admin

from .models import GoalEntry, SavingsGoal


class GoalEntryInline(admin.TabularInline):
    model = GoalEntry
    extra = 0


@admin.register(SavingsGoal)
class SavingsGoalAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "target_amount", "target_date", "is_active", "reached_at")
    list_filter = ("is_active",)
    inlines = [GoalEntryInline]
