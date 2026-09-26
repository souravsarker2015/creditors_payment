from django.apps import AppConfig


class BusinessFinanceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.business.finance"
    label = "business_finance"
    verbose_name = "Business · Finance"

    def ready(self):
        from apps.business.core.seeding import register

        from .seed import seed_accounts, seed_categories

        register("categories", seed_categories)
        register("accounts", seed_accounts)
