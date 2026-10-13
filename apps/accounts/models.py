from django.conf import settings
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
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
    phone = models.CharField(_("Phone"), max_length=20, blank=True, default="")
    # Morning email of money that's late or due soon (apps/overview/reminders.py).
    money_reminders = models.BooleanField(_("Morning money reminders"), default=False)
    reminders_sent_on = models.DateField(null=True, blank=True, editable=False)

    def __str__(self):
        return f"Preferences for {self.user.username}"


class TwoFactorPolicy(models.TextChoices):
    OPTIONAL = "optional", _("Optional — each person decides")
    ADMINS = "admins", _("Required for admins")
    EVERYONE = "everyone", _("Required for everyone")


class SecuritySettings(models.Model):
    """Site-wide security choices, set by an admin. There is only one row."""

    two_factor = models.CharField(_("Two-step sign-in"), max_length=10, choices=TwoFactorPolicy.choices, default=TwoFactorPolicy.OPTIONAL)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta:
        verbose_name = _("Security settings")
        verbose_name_plural = _("Security settings")

    def __str__(self):
        return "Security settings"

    @classmethod
    def load(cls):
        obj, _created = cls.objects.get_or_create(pk=1)
        return obj

    def requires_two_factor(self, user):
        if self.two_factor == TwoFactorPolicy.EVERYONE:
            return True
        return self.two_factor == TwoFactorPolicy.ADMINS and user.is_superuser


class TwoFactor(models.Model):
    """Two-step sign-in with an authenticator app (see totp.py)."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="two_factor")
    secret = models.CharField(max_length=64)
    enabled = models.BooleanField(default=False)
    enabled_at = models.DateTimeField(null=True, blank=True)
    last_step = models.BigIntegerField(default=0, help_text="The last code's time step; a code can't be used twice.")
    recovery_codes = models.JSONField(default=list, blank=True, help_text="Hashes of the unused recovery codes.")
    generation = models.PositiveIntegerField(default=1, help_text="Raised to forget every trusted device.")
    last_used_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Two-step sign-in for {self.user}"

    @property
    def recovery_left(self):
        return len(self.recovery_codes)


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_user_profile(sender, instance, created, raw=False, **kwargs):
    # raw: a user loaded from a backup brings its own profile along.
    if created and not raw:
        UserProfile.objects.get_or_create(user=instance)


class SignIn(models.Model):
    """One sign-in on one device, for "Where you're signed in" and the
    new-device email. Lives as long as its session does; kept a while after
    as history (see signins.py)."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="sign_ins")
    session_key = models.CharField(max_length=40, db_index=True)
    device = models.CharField(max_length=32, blank=True, default="", help_text="A random id kept in a cookie on the device.")
    ip = models.CharField(max_length=64, blank=True, default="")
    user_agent = models.CharField(max_length=300, blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now)
    last_seen = models.DateTimeField(default=timezone.now)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-last_seen"]

    def __str__(self):
        return f"{self.user} on {self.user_agent[:40]}"
