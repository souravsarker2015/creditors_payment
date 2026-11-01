"""
The live site on PythonAnywhere: the same SQLite database as development, with what a public site needs.

Set in the WSGI file:  os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings.live"
Set in .env:           DJANGO_SECRET_KEY=<a long random value of its own>
See "Going live on PythonAnywhere" in README.md.
"""

import os

from .base import *  # noqa: F401,F403
from .logs import LOGGING  # noqa: F401

DEBUG = False
SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]  # no fallback: the one in base.py is public
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "paymenttracker.pythonanywhere.com").split(",")
CSRF_TRUSTED_ORIGINS = [f"https://{host}" for host in ALLOWED_HOSTS]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",  # noqa: F405
    }
}

SECURE_CONTENT_TYPE_NOSNIFF = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
X_FRAME_OPTIONS = "DENY"
SECURE_SSL_REDIRECT = os.environ.get("DJANGO_SECURE_SSL_REDIRECT", "True") == "True"
SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_HSTS_SECONDS", "3600"))  # an hour to begin with: raise it once all's well
