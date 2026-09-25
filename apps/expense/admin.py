from django.contrib import admin
from django.db.models import Sum
from .models import ExpenseCategory, Expense, RecurringExpense


class ExpenseInline(admin.TabularInline):
    model = Expense
    extra = 1
    fields = ("amount", "date", "note")


@admin.register(ExpenseCategory)
class ExpenseCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "get_total_spent", "created_at")
    list_filter = ("is_active", "user", "created_at")
    search_fields = ("name", "user__username")
    inlines = [ExpenseInline]

    @admin.display(description="Total Spent")
    def get_total_spent(self, obj):
        total = obj.expenses.aggregate(total=Sum("amount"))["total"] or 0
        return f"৳{total:,.2f}"


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ("category", "amount", "date", "user")
    list_filter = ("date", "category", "user")
    search_fields = ("category__name", "note", "user__username")


@admin.register(RecurringExpense)
class RecurringExpenseAdmin(admin.ModelAdmin):
    list_display = ("category", "amount", "frequency", "next_run_date", "is_active", "user")
    list_filter = ("frequency", "is_active", "user")
    search_fields = ("category__name", "user__username")
