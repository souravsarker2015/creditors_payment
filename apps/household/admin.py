from django.contrib import admin
from django.db.models import Sum, DecimalField, Value
from django.db.models.functions import Coalesce
from .models import HouseholdCategory, HouseholdMember, Purchase, Settlement


class PurchaseInline(admin.TabularInline):
    model = Purchase
    extra = 1
    fields = ("amount", "date", "category", "description")
    fk_name = "buyer"


class SettlementInline(admin.TabularInline):
    model = Settlement
    extra = 1
    fields = ("amount", "date", "note")


@admin.register(HouseholdCategory)
class HouseholdCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "get_total_spent", "created_at")
    list_filter = ("is_active", "user", "created_at")
    search_fields = ("name", "user__username")

    @admin.display(description="Total Spent")
    def get_total_spent(self, obj):
        total = obj.purchases.aggregate(total=Sum("amount"))["total"] or 0
        return f"৳{total:,.2f}"


@admin.register(HouseholdMember)
class HouseholdMemberAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "get_total_spent", "get_total_settled", "get_balance_due", "get_is_settled")
    list_filter = ("is_active", "user",)
    search_fields = ("name", "phone", "user__username")
    inlines = [PurchaseInline, SettlementInline]

    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related("user")
        if not request.user.is_superuser:
            qs = qs.filter(user=request.user)
        qs = qs.annotate(
            _total_spent=Coalesce(Sum("purchases__amount"), Value(0, output_field=DecimalField())),
            _total_settled=Coalesce(Sum("settlements__amount"), Value(0, output_field=DecimalField())),
        )
        return qs

    @admin.display(description="Total Spent", ordering="_total_spent")
    def get_total_spent(self, obj):
        return f"৳{obj._total_spent:,.2f}"

    @admin.display(description="Total Settled", ordering="_total_settled")
    def get_total_settled(self, obj):
        return f"৳{obj._total_settled:,.2f}"

    @admin.display(description="Balance Due")
    def get_balance_due(self, obj):
        return f"৳{obj._total_spent - obj._total_settled:,.2f}"

    @admin.display(description="Settled", boolean=True)
    def get_is_settled(self, obj):
        return obj._total_spent - obj._total_settled <= 0


@admin.register(Purchase)
class PurchaseAdmin(admin.ModelAdmin):
    list_display = ("date", "amount", "category", "buyer", "user")
    list_filter = ("date", "category", "buyer", "user")
    search_fields = ("description", "user__username", "buyer__name", "category__name")

    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related("user", "buyer", "category")
        if not request.user.is_superuser:
            qs = qs.filter(user=request.user)
        return qs


@admin.register(Settlement)
class SettlementAdmin(admin.ModelAdmin):
    list_display = ("date", "amount", "member", "get_user")
    list_filter = ("date", "member__user")
    search_fields = ("member__name", "note", "member__user__username")

    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related("member__user")
        if not request.user.is_superuser:
            qs = qs.filter(member__user=request.user)
        return qs

    @admin.display(description="User")
    def get_user(self, obj):
        return obj.member.user.username
