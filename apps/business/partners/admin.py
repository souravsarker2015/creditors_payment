from django.contrib import admin

from .models import Partner, PartnerEntry


@admin.register(Partner)
class PartnerAdmin(admin.ModelAdmin):
    list_display = ("name", "business", "share_pct", "joined_on", "opening_capital", "is_deleted")


@admin.register(PartnerEntry)
class PartnerEntryAdmin(admin.ModelAdmin):
    list_display = ("partner", "date", "kind", "amount", "account", "is_deleted")
    list_filter = ("kind",)
