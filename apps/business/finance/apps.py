from django.apps import AppConfig


class BusinessFinanceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.business.finance"
    label = "business_finance"
    verbose_name = "Business · Finance"

    def ready(self):
        from django.utils.translation import gettext_lazy as _

        from apps.business.core.crud import QuickAdd, register_quick_add
        from apps.business.core.seeding import register

        from .seed import seed_accounts, seed_categories

        register("categories", seed_categories)
        register("accounts", seed_accounts)
        register_quick_add("category", QuickAdd("apps.business.finance.forms.CategoryQuickForm", "enter_data", _("New category"), _("category")))
        register_quick_add("account", QuickAdd("apps.business.finance.forms.AccountQuickForm", "view_finance", _("New account"), _("account")))
