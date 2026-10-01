from django.conf import settings
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils.translation import gettext_lazy as _


class ThemeMode(models.TextChoices):
    LIGHT = "light", "Light"
    DARK = "dark", "Dark"


class AccentTheme(models.TextChoices):
    TEAL = "teal", "Ledger Teal"
    INDIGO = "indigo", "Indigo Classic"
    SLATE = "slate", "Slate Mono"


class BackgroundTheme(models.TextChoices):
    """Page and card tint. Each has a matching tinted dark variant in app.css."""

    PAPER = "paper", _("Warm Paper")
    WHITE = "white", _("Clean White")
    NOTEPAD = "notepad", _("Notepad Yellow")
    HONEYDEW = "honeydew", _("Honeydew Green")
    SKY = "sky", _("Sky Mist")
    BLUSH = "blush", _("Rose Blush")
    LAVENDER = "lavender", _("Lavender")


class ViewMode(models.TextChoices):
    """How the app is laid out on a phone. "auto" gives the app layout when
    FinTrack is opened from its home-screen icon, and the website layout in a
    browser tab."""

    AUTO = "auto", _("Automatic")
    APP = "app", _("App view")
    WEB = "web", _("Website view")


class Language(models.TextChoices):
    ENGLISH = "en", "English"
    BENGALI = "bn", "বাংলা"


class UserProfile(models.Model):
    """Per-user display preferences: theme mode, accent, background, language and phone layout.

    Created automatically for every user via the post_save signal below, so
    callers can always assume ``request.user.profile`` exists once the user
    is authenticated.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile"
    )
    theme_mode = models.CharField(
        max_length=10, choices=ThemeMode.choices, default=ThemeMode.LIGHT
    )
    accent = models.CharField(
        max_length=10, choices=AccentTheme.choices, default=AccentTheme.TEAL
    )
    background = models.CharField(
        max_length=10, choices=BackgroundTheme.choices, default=BackgroundTheme.PAPER
    )
    language = models.CharField(
        max_length=5, choices=Language.choices, default=Language.ENGLISH
    )
    view_mode = models.CharField(
        max_length=5, choices=ViewMode.choices, default=ViewMode.AUTO
    )

    def __str__(self):
        return f"Preferences for {self.user.username}"


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.get_or_create(user=instance)
