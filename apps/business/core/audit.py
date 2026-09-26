"""Who is making the current change, for created_by/updated_by and the audit
log. Set per request by DashboardMiddleware; empty in shells and migrations."""
from contextvars import ContextVar

_user = ContextVar("business_current_user", default=None)


def current_user():
    return _user.get()


def set_current_user(user):
    return _user.set(user)


def reset_current_user(token):
    _user.reset(token)


_paused = ContextVar("business_audit_paused", default=False)


class audit_paused:
    """`with audit_paused():` — for starter data, which isn't anyone's action."""

    def __enter__(self):
        self._token = _paused.set(True)

    def __exit__(self, *exc):
        _paused.reset(self._token)


def is_paused():
    return _paused.get()
