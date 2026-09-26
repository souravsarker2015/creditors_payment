from django.contrib import admin

from .models import DeductionType, Market, MarketDeduction


class MarketDeductionInline(admin.TabularInline):
    model = MarketDeduction
    extra = 0
    fields = ["deduction_type", "method", "value", "unit", "business"]


@admin.register(Market)
class MarketAdmin(admin.ModelAdmin):
    list_display = ["name", "business", "location", "is_deleted"]
    inlines = [MarketDeductionInline]


admin.site.register(DeductionType)
