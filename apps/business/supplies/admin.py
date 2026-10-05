from django.contrib import admin

from .models import SupplyItem, SupplyPurchase


@admin.register(SupplyItem)
class SupplyItemAdmin(admin.ModelAdmin):
    list_display = ("name", "business", "kind", "unit", "low_stock", "is_deleted")
    list_filter = ("kind",)


@admin.register(SupplyPurchase)
class SupplyPurchaseAdmin(admin.ModelAdmin):
    list_display = ("item", "date", "quantity", "unit", "cost", "paid_now", "is_deleted")
