from django.apps import AppConfig


class BusinessSpeciesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.business.species"
    label = "business_species"
    verbose_name = "Business · Fish species"

    def ready(self):
        from apps.business.core.seeding import register

        from .seed import seed_species

        register("species", seed_species)

        from django.utils.translation import gettext_lazy as _

        from apps.business.core.crud import QuickAdd, register_quick_add

        register_quick_add("species", QuickAdd("apps.business.species.forms.SpeciesQuickForm", "enter_data", _("New fish species"), _("fish")))
