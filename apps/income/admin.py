from django.contrib import admin
from django.db.models import Sum
from .models import IncomeSource, IncomeTransaction


class IncomeTransactionInline(admin.TabularInline):
    model = IncomeTransaction
    extra = 1
    fields = ("amount", "date", "note")


@admin.register(IncomeSource)
class IncomeSourceAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "get_total_income", "created_at")
    list_filter = ("user", "created_at")
    search_fields = ("name", "description", "user__username")
    inlines = [IncomeTransactionInline]

    @admin.display(description="Total Generated Income")
    def get_total_income(self, obj):
        total = obj.transactions.aggregate(total=Sum("amount"))["total"] or 0
        return f"৳{total:,.2f}"


@admin.register(IncomeTransaction)
class IncomeTransactionAdmin(admin.ModelAdmin):
    list_display = ("source", "amount", "date", "get_user")
    list_filter = ("date", "source__user")
    search_fields = ("source__name", "note", "source__user__username")

    @admin.display(description="User")
    def get_user(self, obj):
        return obj.source.user.username
