from django.contrib import admin

from .models import FishSale, FishSaleLine, SaleDeduction


class LineInline(admin.TabularInline):
    model = FishSaleLine
    extra = 0
    fields = ["species", "quantity", "unit", "rate", "business"]


class DeductionInline(admin.TabularInline):
    model = SaleDeduction
    extra = 0
    fields = ["deduction_type", "method", "value", "unit", "business"]


@admin.register(FishSale)
class FishSaleAdmin(admin.ModelAdmin):
    list_display = ["date", "business", "buyer", "market", "gross", "net", "received_now", "is_deleted"]
    list_filter = ["business", "market"]
    inlines = [LineInline, DeductionInline]

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        form.instance.recalc()
