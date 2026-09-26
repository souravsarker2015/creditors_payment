from django.apps import AppConfig


class BusinessMarketsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.business.markets"
    label = "business_markets"
    verbose_name = "Business · Markets"

    def ready(self):
        from apps.business.core.seeding import register

        from .seed import seed_deduction_types

        register("deduction types", seed_deduction_types)

        from django.utils.translation import gettext_lazy as _

        from apps.business.core.crud import QuickAdd, register_quick_add

        register_quick_add("market", QuickAdd("apps.business.markets.forms.MarketQuickForm", "enter_data", _("New market"), _("market")))
        register_quick_add("deduction_type", QuickAdd("apps.business.markets.forms.DeductionTypeQuickForm", "manage_settings", _("New deduction type"), _("deduction type")))
