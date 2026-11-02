"""What a site admin needs to know about how the public site itself is running, on every page until it's put right."""
from django.conf import settings
from django.utils.translation import gettext as _

LOCAL = ("localhost", "127.0.0.1", "[::1]", "testserver")
PUBLIC_KEY = "django-insecure-change-me-before-production"     # the fallback in base.py, there for anyone to read


def site_warnings(request):
    user = getattr(request, "user", None)
    if user is None or not user.is_superuser or request.get_host().rsplit(":", 1)[0] in LOCAL:
        return {}
    warnings = []
    if settings.DEBUG:
        warnings.append(_("This public site is in debug mode: an error page shows your code and settings to anyone. See “Going live” in the README."))
    if settings.SECRET_KEY == PUBLIC_KEY:
        warnings.append(_("This public site uses the secret key from the code, so sign-ins can be forged. Set DJANGO_SECRET_KEY on the server."))
    return {"site_warnings": warnings}
