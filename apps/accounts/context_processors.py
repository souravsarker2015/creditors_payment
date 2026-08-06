from .models import UserProfile, ThemeMode, AccentTheme


def user_preferences(request):
    """Expose the current user's theme/accent preference to every template.

    Falls back to the light/teal defaults for anonymous users (language for
    anonymous users is already handled by Django's own i18n machinery via
    ``LANGUAGE_CODE`` in the request).
    """
    if request.user.is_authenticated:
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        return {
            "user_theme_mode": profile.theme_mode,
            "user_accent": profile.accent,
        }
    return {
        "user_theme_mode": ThemeMode.LIGHT,
        "user_accent": AccentTheme.TEAL,
    }
