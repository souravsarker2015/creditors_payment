from django.contrib import admin
from .models import Debtor, Transaction


@admin.register(Debtor)
class DebtorAdmin(admin.ModelAdmin):
    list_display = ("name", "phone", "user", "created_at")
    search_fields = ("name", "phone")
    list_filter = ("user",)


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ("debtor", "transaction_type", "amount", "date")
    list_filter = ("transaction_type", "date")
    search_fields = ("debtor__name", "note")
