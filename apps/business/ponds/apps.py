from django.apps import AppConfig


class BusinessPondsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.business.ponds"
    label = "business_ponds"
    verbose_name = "Business · Ponds"

    def ready(self):
        from django.utils.translation import gettext_lazy as _

        from apps.business.core.crud import QuickAdd, register_quick_add

        register_quick_add("pond", QuickAdd("apps.business.ponds.forms.PondQuickForm", "manage_settings", _("New pond"), _("pond")))
