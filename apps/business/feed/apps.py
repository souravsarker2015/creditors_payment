from django.apps import AppConfig


class BusinessFeedConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.business.feed"
    label = "business_feed"
    verbose_name = "Business · Feed"
