from django.contrib import admin

from .models import AuditLog, Business, Dashboard, Membership, Unit, UserDashboardAccess


@admin.register(Dashboard)
class DashboardAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "url_name", "order", "is_active", "grant_to_new_users")


@admin.register(UserDashboardAccess)
class UserDashboardAccessAdmin(admin.ModelAdmin):
    list_display = ("user", "dashboard", "is_default", "granted_by", "granted_at")
    list_filter = ("dashboard", "is_default")
    search_fields = ("user__username",)


class MembershipInline(admin.TabularInline):
    model = Membership
    extra = 0
    fk_name = "business"


@admin.register(Business)
class BusinessAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "phone", "created_at")
    inlines = [MembershipInline]


@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = ("name", "symbol", "unit_type", "factor", "is_base", "business", "is_deleted")
    list_filter = ("unit_type", "is_deleted")

    def get_queryset(self, request):
        return Unit.all_objects.all()


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("at", "business", "user", "action", "model", "object_repr")
    list_filter = ("action", "model")
    readonly_fields = [f.name for f in AuditLog._meta.fields]
