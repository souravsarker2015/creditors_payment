from functools import wraps

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from .access import BUSINESS, active_membership, can, has_dashboard


def business_access_required(view=None, *, capability=None, need_business=True):
    """Guard for every business view.

    * no Business dashboard access  → friendly 403 page
    * no business yet               → the "set up your farm" page
    * role lacks `capability`       → friendly 403 page
    Sets request.membership and request.business for the view.
    """
    def decorator(fn):
        @login_required
        @wraps(fn)
        def wrapped(request, *args, **kwargs):
            if not has_dashboard(request.user, BUSINESS):
                return render(request, "business/forbidden.html", {"reason": "dashboard"}, status=403)
            membership = active_membership(request)
            request.membership = membership
            request.business = membership.business if membership else None
            if need_business and membership is None:
                return redirect("business:setup")
            if capability and not can(membership, capability):
                return render(request, "business/forbidden.html", {"reason": "role", "capability": capability}, status=403)
            return fn(request, *args, **kwargs)
        return wrapped
    return decorator(view) if view else decorator
