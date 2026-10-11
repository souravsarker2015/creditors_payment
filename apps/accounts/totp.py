"""Time-based one-time passwords (RFC 6238), as used by Google Authenticator,
Microsoft Authenticator, Authy, 1Password, Bitwarden…: 6 digits that change
every 30 seconds, from a secret shared once through a QR code."""
import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote, urlencode

STEP = 30       # seconds a code lasts
DIGITS = 6
WINDOW = 1      # also accept the code just before and just after (phone clocks drift)


def new_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _key(secret):
    secret = secret.replace(" ", "").upper()
    return base64.b32decode(secret + "=" * (-len(secret) % 8))


def code_at(secret, step):
    digest = hmac.new(_key(secret), struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(number % 10 ** DIGITS).zfill(DIGITS)


def current_step(now=None):
    return int((now if now is not None else time.time()) // STEP)


def verify(secret, code, last_step=0, now=None):
    """The time step the code belongs to, or None. A step at or before
    `last_step` (already used) is refused, so a code can't be used twice."""
    code = "".join(ch for ch in str(code or "") if ch.isdigit())
    if len(code) != DIGITS:
        return None
    step = current_step(now)
    for candidate in range(step - WINDOW, step + WINDOW + 1):
        if candidate > last_step and hmac.compare_digest(code_at(secret, candidate), code):
            return candidate
    return None


def provisioning_uri(secret, account, issuer="FinTrack"):
    """otpauth:// link the authenticator app reads from the QR code."""
    label = quote(issuer) + ":" + quote(account)
    return f"otpauth://totp/{label}?" + urlencode({"secret": secret, "issuer": issuer, "digits": DIGITS, "period": STEP})


# ── Recovery codes: for when the phone is lost ────────────────────────────
ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"   # no 0/o, 1/l/i


def new_recovery_codes(n=10):
    return ["".join(secrets.choice(ALPHABET) for _ in range(5)) + "-" + "".join(secrets.choice(ALPHABET) for _ in range(5)) for _ in range(n)]


def hash_code(code):
    clean = "".join(ch for ch in str(code).lower() if ch.isalnum())
    return hashlib.sha256(("fintrack-recovery:" + clean).encode()).hexdigest()
