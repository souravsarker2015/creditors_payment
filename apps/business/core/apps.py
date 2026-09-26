from django.apps import AppConfig


class BusinessCoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.business.core"
    label = "business_core"
    verbose_name = "Business · Core"

    def ready(self):
        from . import signals  # noqa: F401  (access grants, login redirect, audit trail)
