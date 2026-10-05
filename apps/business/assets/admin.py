from django.contrib import admin

from .models import Equipment, Service


@admin.register(Equipment)
class EquipmentAdmin(admin.ModelAdmin):
    list_display = ("name", "business", "kind", "pond", "condition", "cost", "is_deleted")
    list_filter = ("kind", "condition")


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ("equipment", "date", "kind", "cost", "is_deleted")
