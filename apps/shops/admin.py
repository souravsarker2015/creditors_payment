from django.contrib import admin
from django.db.models import Sum, Q, DecimalField, Value
from django.db.models.functions import Coalesce

from .models import Shop, Transaction


class TransactionInline(admin.TabularInline):
    """Inline table of purchase/payment transactions on the Shop detail page."""
    model = Transaction
    extra = 1
    fields = ("transaction_type", "amount", "date", "note")
    ordering = ("-date", "-created_at")


@admin.register(Shop)
class ShopAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "user",
        "get_total_due",
        "get_total_paid",
        "get_remaining",
        "get_is_paid",
    )
    list_filter = ("user", "category", "transactions__transaction_type")
    search_fields = ("name", "phone", "user__username")
    inlines = [TransactionInline]

    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related('user')
        if not request.user.is_superuser:
            qs = qs.filter(user=request.user)

        qs = qs.annotate(
            _total_due=Coalesce(
                Sum(
                    "transactions__amount",
                    filter=Q(transactions__transaction_type=Transaction.PURCHASE),
                ),
                Value(0, output_field=DecimalField()),
            ),
            _total_paid=Coalesce(
                Sum(
                    "transactions__amount",
                    filter=Q(transactions__transaction_type=Transaction.PAYMENT),
                ),
                Value(0, output_field=DecimalField()),
            ),
        )
        return qs

    @admin.display(description="Total Due", ordering="_total_due")
    def get_total_due(self, obj):
        return f"৳{obj._total_due:,.2f}"

    @admin.display(description="Total Paid", ordering="_total_paid")
    def get_total_paid(self, obj):
        return f"৳{obj._total_paid:,.2f}"

    @admin.display(description="Remaining")
    def get_remaining(self, obj):
        remaining = obj._total_due - obj._total_paid
        return f"৳{remaining:,.2f}"

    @admin.display(description="Is Paid", boolean=True)
    def get_is_paid(self, obj):
        return obj._total_due - obj._total_paid <= 0


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ("shop", "transaction_type", "amount", "date", "shop_user")
    list_filter = ("transaction_type", "date", "shop__user")
    search_fields = ("shop__name", "note", "shop__user__username")

    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related('shop__user')
        if not request.user.is_superuser:
            qs = qs.filter(shop__user=request.user)
        return qs

    @admin.display(description="User")
    def shop_user(self, obj):
        return obj.shop.user.username
