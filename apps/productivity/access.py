"""Who can open Productivity: admins always, and anyone an admin allows
(People & access, or Business settings → Access)."""
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.business.core.access import has_dashboard

CODE = "productivity"


def can_use(user):
    return user.is_authenticated and has_dashboard(user, CODE)


def work_required(view):
    @login_required
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not can_use(request.user):
            return render(request, "work/forbidden.html", status=403)
        return view(request, *args, **kwargs)
    return wrapped
