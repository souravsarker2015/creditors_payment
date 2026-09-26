from django.apps import AppConfig


class BusinessLoansConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.business.loans"
    label = "business_loans"
    verbose_name = "Business · Loans"
