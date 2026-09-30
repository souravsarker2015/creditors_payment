from django.apps import AppConfig


class BusinessFeedConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.business.feed"
    label = "business_feed"
    verbose_name = "Business · Feed"

    def ready(self):
        from django.utils.translation import gettext_lazy as _

        from apps.business.core.crud import QuickAdd, register_quick_add

        register_quick_add("feed", QuickAdd("apps.business.feed.forms.FeedProductQuickForm", "enter_data", _("New feed"), _("feed")))
