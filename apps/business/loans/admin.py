from django.contrib import admin

from .models import Lender, Loan, LoanRateChange, LoanTransaction


class LoanTransactionInline(admin.TabularInline):
    model = LoanTransaction
    extra = 0
    fields = ["kind", "date", "interest", "principal", "charges", "paid_via", "is_deleted"]
    readonly_fields = ["is_deleted"]


@admin.register(Loan)
class LoanAdmin(admin.ModelAdmin):
    list_display = ["title", "business", "principal", "rate", "rate_period", "every", "every_unit", "repayment", "taken_on", "closed_on", "is_deleted"]
    list_filter = ["business", "repayment", "is_deleted"]
    inlines = [LoanTransactionInline]

    def get_queryset(self, request):
        return Loan.all_objects.select_related("lender", "business")


@admin.register(Lender)
class LenderAdmin(admin.ModelAdmin):
    list_display = ["name", "kind", "business", "phone", "is_deleted"]
    list_filter = ["kind", "business", "is_deleted"]

    def get_queryset(self, request):
        return Lender.all_objects.all()


admin.site.register(LoanRateChange)
