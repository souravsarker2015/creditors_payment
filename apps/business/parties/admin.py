from django.contrib import admin

from .models import Party


@admin.register(Party)
class PartyAdmin(admin.ModelAdmin):
    list_display = ["name", "business", "phone", "is_supplier", "is_buyer", "opening_balance", "opening_type", "is_deleted"]
    list_filter = ["is_supplier", "is_buyer", "business"]
    search_fields = ["name", "phone"]
