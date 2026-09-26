from django.contrib import admin

from .models import PartyPayment


@admin.register(PartyPayment)
class PartyPaymentAdmin(admin.ModelAdmin):
    list_display = ("date", "party", "direction", "amount", "discount", "business", "is_deleted")
    list_filter = ("direction", "is_deleted")
    search_fields = ("party__name", "reference")
    raw_id_fields = ("party", "sale", "feed_purchase", "stocking")
