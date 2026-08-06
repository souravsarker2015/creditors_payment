from django.conf import settings
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver


class ThemeMode(models.TextChoices):
    LIGHT = "light", "Light"
    DARK = "dark", "Dark"


class AccentTheme(models.TextChoices):
    TEAL = "teal", "Ledger Teal"
    INDIGO = "indigo", "Indigo Classic"
    SLATE = "slate", "Slate Mono"


class Language(models.TextChoices):
    ENGLISH = "en", "English"
    BENGALI = "bn", "বাংলা"


class UserProfile(models.Model):
    """Per-user display preferences: theme mode, accent palette, and language.

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
    language = models.CharField(
        max_length=5, choices=Language.choices, default=Language.ENGLISH
    )

    def __str__(self):
        return f"Preferences for {self.user.username}"


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.get_or_create(user=instance)
