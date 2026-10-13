"""Where you're signed in: one row per sign-in, so a person can see every
device that has their account open, sign any of them out, and get an email
when their account is opened on a device it has never been used on."""
import re
import secrets
from datetime import timedelta

from django.contrib.sessions.models import Session
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext as _

from .models import SignIn

SESSION_KEY = "_signin"           # session: the SignIn row of this sign-in
DEVICE_COOKIE = "ft_device"       # a random id, so a device is known the next time
DEVICE_YEARS = 2
TOUCH_EVERY = timedelta(minutes=5)
KEEP = timedelta(days=90)         # ended sign-ins stay in the history this long


def _ip(request):
    from .forms import client_ip

    return client_ip(request)


# ── What the device is, in words ────────────────────────────────────────────

_BROWSERS = [
    (r"EdgA?/|Edg/", "Edge"), (r"OPR/|Opera", "Opera"), (r"SamsungBrowser", "Samsung Internet"),
    (r"Firefox/|FxiOS", "Firefox"), (r"Chrome/|CriOS", "Chrome"), (r"Safari/", "Safari"),
]
_SYSTEMS = [
    (r"iPhone", "iPhone"), (r"iPad", "iPad"), (r"Android", "Android"), (r"CrOS", "ChromeOS"),
    (r"Windows", "Windows"), (r"Mac OS X|Macintosh", "Mac"), (r"Linux", "Linux"),
]


def describe(user_agent):
    """"Chrome on Android" from a browser's user agent; "Unknown device" when it's no help."""
    ua = user_agent or ""
    browser = next((name for pat, name in _BROWSERS if re.search(pat, ua)), "")
    system = next((name for pat, name in _SYSTEMS if re.search(pat, ua)), "")
    if browser and system:
        return _("%(browser)s on %(system)s") % {"browser": browser, "system": system}
    return browser or system or _("Unknown device")


def is_phone(user_agent):
    return bool(re.search(r"iPhone|Android.*Mobile|Mobile Safari", user_agent or ""))


# ── Recording ───────────────────────────────────────────────────────────────

def record(request, response, user, new_account=False):
    """Called right after someone signs in. Returns the SignIn row, and emails
    the owner when this device has never been used with their account before."""
    device = request.COOKIES.get(DEVICE_COOKIE, "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,32}", device):
        device = secrets.token_urlsafe(16)
    known = SignIn.objects.filter(user=user, device=device).exists()
    seen_before = SignIn.objects.filter(user=user).exists()
    now = timezone.now()
    row = SignIn.objects.create(
        user=user, session_key=request.session.session_key or "", device=device, ip=_ip(request),
        user_agent=request.META.get("HTTP_USER_AGENT", "")[:300], created_at=now, last_seen=now)
    request.session[SESSION_KEY] = row.pk
    response.set_cookie(DEVICE_COOKIE, device, max_age=DEVICE_YEARS * 365 * 24 * 3600, httponly=True,
                        samesite="Lax", secure=request.is_secure())
    if seen_before and not known and not new_account:
        _tell_owner(request, user, row)
    SignIn.objects.filter(user=user, last_seen__lt=now - KEEP).delete()
    return row


def _tell_owner(request, user, row):
    from .twofactor import notify, when_text

    notify(request, user, _("New sign-in to your FinTrack account"),
           _("Your FinTrack account was opened on a new device: %(device)s, from internet address %(ip)s, on %(when)s. "
             "You can see every device that is signed in, and sign any of them out, under Account & security → Where you're signed in.")
           % {"device": describe(row.user_agent), "ip": row.ip or "?", "when": when_text()})


def touch(request):
    """Keep "last active" fresh, and give sign-ins from before this feature a
    row of their own the first time they're seen."""
    session = request.session
    pk = session.get(SESSION_KEY)
    now = timezone.now()
    if pk:
        # A password change gives this sign-in a new session key; follow it.
        SignIn.objects.filter(Q(last_seen__lt=now - TOUCH_EVERY) | ~Q(session_key=session.session_key), pk=pk, user=request.user) \
            .update(last_seen=now, ip=_ip(request), session_key=session.session_key or "")
        return
    if not session.session_key:
        return
    row = SignIn.objects.create(
        user=request.user, session_key=session.session_key, device=request.COOKIES.get(DEVICE_COOKIE, "")[:32],
        ip=_ip(request), user_agent=request.META.get("HTTP_USER_AGENT", "")[:300], created_at=now, last_seen=now)
    session[SESSION_KEY] = row.pk


def ended(request):
    """Signing out here."""
    pk = request.session.get(SESSION_KEY)
    if pk:
        SignIn.objects.filter(pk=pk, ended_at__isnull=True).update(ended_at=timezone.now())


# ── The list on Account & security ──────────────────────────────────────────

def _live_keys(user, rows):
    """Sessions still signed in as this person: not expired, and from before
    no password change (Django ends those on their next visit)."""
    keys = [r.session_key for r in rows if r.session_key]
    auth_hash = user.get_session_auth_hash()
    return {s.session_key for s in Session.objects.filter(session_key__in=keys, expire_date__gt=timezone.now())
            if s.get_decoded().get("_auth_user_hash") == auth_hash}


def active(user, request=None):
    """The sign-ins still open, this one first. A sign-in whose session has
    gone (signed out, expired, or ended by a password change) isn't listed."""
    rows = list(SignIn.objects.filter(user=user, ended_at__isnull=True))
    live = _live_keys(user, rows)
    current = request.session.get(SESSION_KEY) if request is not None else None
    out = []
    for r in rows:
        if r.session_key not in live:
            continue
        r.is_current = r.pk == current
        r.active_now = r.is_current or r.last_seen >= timezone.now() - TOUCH_EVERY   # "last active" moves in TOUCH_EVERY steps
        r.label = describe(r.user_agent)
        r.phone = is_phone(r.user_agent)
        out.append(r)
    out.sort(key=lambda r: (not r.is_current, -r.last_seen.timestamp()))
    return out


def recent(user, limit=8):
    rows = list(SignIn.objects.filter(user=user).order_by("-created_at")[:limit])
    for r in rows:
        r.label = describe(r.user_agent)
    return rows


def sign_out(user, pk):
    """Ends one sign-in (on any device). Returns True when there was one."""
    row = SignIn.objects.filter(user=user, pk=pk).first()
    if row is None:
        return False
    Session.objects.filter(session_key=row.session_key).delete()
    if row.ended_at is None:
        row.ended_at = timezone.now()
        row.save(update_fields=["ended_at"])
    return True


def sign_out_others(user, request):
    """Ends every sign-in except this one. Returns how many there were."""
    rows = [r for r in active(user, request) if not r.is_current]
    for r in rows:
        sign_out(user, r.pk)
    # Sign-ins from before rows were kept have no row: find them by their session.
    current = request.session.session_key
    stray = [s.session_key for s in Session.objects.filter(expire_date__gt=timezone.now()).exclude(session_key=current)
             if s.get_decoded().get("_auth_user_id") == str(user.pk)]
    Session.objects.filter(session_key__in=stray).delete()
    SignIn.objects.filter(user=user, ended_at__isnull=True).exclude(pk=request.session.get(SESSION_KEY)).update(ended_at=timezone.now())
    return len(rows) + len(stray)
