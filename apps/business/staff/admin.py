from django.contrib import admin

from .models import Earning, Worker, WorkerPayment


@admin.register(Worker)
class WorkerAdmin(admin.ModelAdmin):
    list_display = ("name", "business", "job", "pay_type", "rate", "started_on", "left_on", "is_deleted")
    list_filter = ("pay_type", "is_deleted")
    search_fields = ("name", "phone")


@admin.register(Earning)
class EarningAdmin(admin.ModelAdmin):
    list_display = ("worker", "date", "kind", "amount", "cycle", "is_deleted")
    list_filter = ("kind",)


@admin.register(WorkerPayment)
class WorkerPaymentAdmin(admin.ModelAdmin):
    list_display = ("worker", "date", "kind", "amount", "account", "is_deleted")
    list_filter = ("kind",)
