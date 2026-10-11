"""Two-step sign-in: the second step after the password, trusted devices,
recovery codes and the security emails that go with them."""
import logging
import time

from django.conf import settings
from django.contrib.auth import get_user_model, login
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone, translation
from django.utils.translation import gettext as _

from . import totp
from .models import TwoFactor, UserProfile

logger = logging.getLogger(__name__)

PENDING = "2fa_pending"          # session: a password was right, the code is still to come
PENDING_MAX_AGE = 10 * 60        # seconds to type the code
MAX_TRIES = 5                    # wrong codes before starting again from the password
TRUST_COOKIE = "ft_2fa_trust"
TRUST_DAYS = 30
BACKEND = "apps.accounts.backends.UsernameOrEmailBackend"


def get_two_factor(user):
    try:
        return user.two_factor
    except TwoFactor.DoesNotExist:
        return None


def enabled_for(user):
    """The person's TwoFactor when two-step sign-in is on for them, else None."""
    tf = get_two_factor(user) if user.pk else None
    return tf if tf is not None and tf.enabled else None


def check_code(tf, code, allow_recovery=True):
    """'totp' or 'recovery' when the code is right (and uses it up), else None."""
    step = totp.verify(tf.secret, code, tf.last_step)
    if step is not None:
        tf.last_step = step
        tf.last_used_at = timezone.now()
        tf.save(update_fields=["last_step", "last_used_at"])
        return "totp"
    if allow_recovery:
        digest = totp.hash_code(code)
        if digest in tf.recovery_codes:
            tf.recovery_codes = [h for h in tf.recovery_codes if h != digest]
            tf.last_used_at = timezone.now()
            tf.save(update_fields=["recovery_codes", "last_used_at"])
            return "recovery"
    return None


# ── Trusted devices: no code on this browser for 30 days ──────────────────
def _trust_value(user, tf):
    return f"{user.pk}:{tf.generation}"


def is_trusted(request, user, tf):
    value = request.get_signed_cookie(TRUST_COOKIE, default=None, salt="2fa-trust", max_age=TRUST_DAYS * 86400)
    return value == _trust_value(user, tf)


def trust_device(response, request, user, tf):
    response.set_signed_cookie(TRUST_COOKIE, _trust_value(user, tf), salt="2fa-trust", max_age=TRUST_DAYS * 86400,
                               httponly=True, secure=request.is_secure(), samesite="Lax")


# ── The two steps ─────────────────────────────────────────────────────────
def start_pending(request, user, remember, next_url):
    request.session[PENDING] = {"uid": user.pk, "remember": bool(remember), "next": next_url or "", "at": time.time(), "tries": 0}


def pending_user(request):
    data = request.session.get(PENDING)
    if not data or time.time() - data.get("at", 0) > PENDING_MAX_AGE:
        request.session.pop(PENDING, None)
        return None, None
    user = get_user_model().objects.filter(pk=data["uid"], is_active=True).first()
    return user, data


def finish_login(request, user, remember, response_factory):
    """Signs the person in for real and returns the response to send."""
    request.session.pop(PENDING, None)
    login(request, user, backend=BACKEND)
    # Remember me: keep the sign-in for SESSION_COOKIE_AGE (30 days); otherwise until the browser closes.
    request.session.set_expiry(None if remember else 0)
    profile, _created = UserProfile.objects.get_or_create(user=user)
    translation.activate(profile.language)
    response = response_factory()
    response.set_cookie(settings.LANGUAGE_COOKIE_NAME, profile.language)
    return response


# ── Security emails ───────────────────────────────────────────────────────
def when_text():
    from django.utils.formats import date_format

    return date_format(timezone.localtime(), "j M Y, g:i A")


def notify(request, user, subject, message):
    """A short security email ("your password was changed"…). Never blocks
    what it reports: a mail outage is only logged."""
    if not user.email:
        return
    ctx = {"user": user, "message": message,
           "reset_url": request.build_absolute_uri(reverse("password_reset")),
           "account_url": request.build_absolute_uri(reverse("account_settings"))}
    try:
        send_mail(subject, render_to_string("accounts/email/security_notice.txt", ctx, request=request), None, [user.email])
    except Exception:  # noqa: BLE001
        logger.exception("Couldn't send a security email to user %s", user.pk)
