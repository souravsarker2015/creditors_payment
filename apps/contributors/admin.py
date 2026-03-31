from django.contrib import admin
from django.db.models import Sum
from .models import Contributor, Contribution


class ContributionInline(admin.TabularInline):
    model = Contribution
    extra = 1
    fields = ("amount", "date", "note")


@admin.register(Contributor)
class ContributorAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "phone", "get_total_contributed", "created_at")
    list_filter = ("user", "created_at")
    search_fields = ("name", "phone", "user__username")
    inlines = [ContributionInline]

    @admin.display(description="Total Contributed")
    def get_total_contributed(self, obj):
        total = obj.contributions.aggregate(total=Sum("amount"))["total"] or 0
        return f"৳{total:,.2f}"


@admin.register(Contribution)
class ContributionAdmin(admin.ModelAdmin):
    list_display = ("contributor", "amount", "date", "get_user")
    list_filter = ("date", "contributor__user")
    search_fields = ("contributor__name", "note", "contributor__user__username")

    @admin.display(description="User")
    def get_user(self, obj):
        return obj.contributor.user.username
