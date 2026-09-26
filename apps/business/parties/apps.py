from django.apps import AppConfig


class BusinessPartiesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.business.parties"
    label = "business_parties"
    verbose_name = "Business · Suppliers & buyers"

    def ready(self):
        from django.utils.translation import gettext_lazy as _

        from apps.business.core.crud import QuickAdd, register_quick_add

        register_quick_add("supplier", QuickAdd("apps.business.parties.forms.SupplierQuickForm", "enter_data", _("New supplier"), _("supplier")))
        register_quick_add("buyer", QuickAdd("apps.business.parties.forms.BuyerQuickForm", "enter_data", _("New buyer"), _("buyer")))
