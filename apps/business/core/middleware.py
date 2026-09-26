"""Keeps each person inside the dashboards they're allowed to use.

* Remembers the active dashboard in the session (/business/… = business,
  everything else = the existing personal app).
* Right after login, sends people whose default dashboard isn't the personal
  one to their default.
* Someone without personal access (e.g. farm staff) is sent to the business
  area instead of seeing the personal ledgers.
For everyone who has personal access — every existing user — nothing changes.
"""
from django.shortcuts import redirect, render

from .access import BUSINESS, PERSONAL, dashboard_url, default_dashboard, has_dashboard, request_dashboards
from .audit import reset_current_user, set_current_user

EXEMPT = ("/accounts/", "/admin/", "/static/", "/media/", "/i18n/", "/__debug__/",
          "/sw.js", "/manifest.webmanifest", "/offline/", "/favicon.ico")


class DashboardMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = set_current_user(getattr(request, "user", None))
        try:
            response = self.route(request)
            return response if response is not None else self.get_response(request)
        finally:
            reset_current_user(token)

    def route(self, request):
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated or request.path.startswith(EXEMPT):
            return None
        in_business = request.path.startswith("/business/")
        area = BUSINESS if in_business else PERSONAL
        if request.session.get("active_dashboard") != area:
            request.session["active_dashboard"] = area
        if in_business:
            request.session.pop("dashboard_after_login", None)
            return None  # business views check access themselves (403 page)

        just_logged_in = request.session.pop("dashboard_after_login", False)
        if not has_dashboard(user, PERSONAL):
            others = [d for d in request_dashboards(request) if d.code != PERSONAL]
            if others:
                return redirect(dashboard_url(others[0]))
            return render(request, "business/no_access.html", status=403)
        if just_logged_in and request.method == "GET":
            default = default_dashboard(user)
            if default and default.code != PERSONAL:
                return redirect(dashboard_url(default))
        return None
