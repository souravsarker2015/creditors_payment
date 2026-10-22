from django.apps import AppConfig


class ProductivityConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.productivity"
    label = "productivity"
    verbose_name = "Productivity"

    def ready(self):
        from . import activity  # noqa: F401 — records what changes on a task
