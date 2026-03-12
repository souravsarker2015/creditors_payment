"""
Django development settings for creditors_payment project.

Extends base settings with development-friendly defaults.
"""

from .base import *  # noqa: F401,F403

# ──────────────────────────────────────────────
# Core
# ──────────────────────────────────────────────
DEBUG = True
ALLOWED_HOSTS = ["*"]

# ──────────────────────────────────────────────
# Database — SQLite for local development
# ──────────────────────────────────────────────
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",  # noqa: F405
    }
}

# ──────────────────────────────────────────────
# django-debug-toolbar
# ──────────────────────────────────────────────
try:
    import debug_toolbar  # noqa: F401

    INSTALLED_APPS += ["debug_toolbar"]  # noqa: F405
    MIDDLEWARE.insert(0, "debug_toolbar.middleware.DebugToolbarMiddleware")  # noqa: F405
    INTERNAL_IPS = ["127.0.0.1"]
except ImportError:
    pass

# ──────────────────────────────────────────────
# django-extensions
# ──────────────────────────────────────────────
try:
    import django_extensions  # noqa: F401

    INSTALLED_APPS += ["django_extensions"]  # noqa: F405
except ImportError:
    pass

# ──────────────────────────────────────────────
# Email — console backend for development
# ──────────────────────────────────────────────
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
