from django.contrib import admin
from django.db.models import Sum, Q, DecimalField, Value
from django.db.models.functions import Coalesce
from .models import Debtor, Transaction


class TransactionInline(admin.TabularInline):
    model = Transaction
    extra = 1
    fields = ("transaction_type", "amount", "date", "note")


@admin.register(Debtor)
class DebtorAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "user",
        "get_total_lent",
        "get_total_received",
        "get_remaining",
        "get_is_paid",
    )
    list_filter = ("user", "transactions__transaction_type")
    search_fields = ("name", "phone", "user__username")
    inlines = [TransactionInline]

    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related('user')
        if not request.user.is_superuser:
            qs = qs.filter(user=request.user)
        
        qs = qs.annotate(
            _total_lent=Coalesce(
                Sum(
                    "transactions__amount",
                    filter=Q(transactions__transaction_type=Transaction.LEND),
                ),
                Value(0, output_field=DecimalField()),
            ),
            _total_received=Coalesce(
                Sum(
                    "transactions__amount",
                    filter=Q(transactions__transaction_type=Transaction.RECEIVE),
                ),
                Value(0, output_field=DecimalField()),
            ),
        )
        return qs

    @admin.display(description="Total Lent", ordering="_total_lent")
    def get_total_lent(self, obj):
        return f"৳{obj._total_lent:,.2f}"

    @admin.display(description="Total Received", ordering="_total_received")
    def get_total_received(self, obj):
        return f"৳{obj._total_received:,.2f}"

    @admin.display(description="Remaining")
    def get_remaining(self, obj):
        remaining = obj._total_lent - obj._total_received
        return f"৳{remaining:,.2f}"

    @admin.display(description="Is Paid", boolean=True)
    def get_is_paid(self, obj):
        return obj._total_lent - obj._total_received <= 0


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ("debtor", "transaction_type", "amount", "date", "get_user")
    list_filter = ("transaction_type", "date", "debtor__user")
    search_fields = ("debtor__name", "note", "debtor__user__username")

    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related('debtor__user')
        if not request.user.is_superuser:
            qs = qs.filter(debtor__user=request.user)
        return qs

    @admin.display(description="User")
    def get_user(self, obj):
        return obj.debtor.user.username
