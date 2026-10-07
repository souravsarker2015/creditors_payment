"""Never show a list from before your last save.

Browsers keep copies of pages: the back/forward cache, the HTTP cache, and
the speculation rules' prefetched/prerendered pages (fetched as links come
into view, kept for minutes). After you add or change something, opening or
going back to a list could show one of those copies — the new entry missing
until a manual refresh.

So every change bumps a small "data version" cookie, and every page is
stamped with the version it was built from. A page whose stamp is older than
the cookie is a stale copy, and the browser reloads it (see
templates/partials/freshness.html). Chrome is also told to drop its
speculative copies right away (Clear-Site-Data, secure origins only).
"""
import time

COOKIE = "ftv"
SAFE = {"GET", "HEAD", "OPTIONS", "TRACE"}


def changed_data(request, response):
    """A successful change: a redirect after a form, or a non-page reply to a background save."""
    if request.method in SAFE:
        return False
    status = response.status_code
    if 300 <= status < 400:
        return True
    if 200 <= status < 300:
        # A form shown again (with errors) is HTML; a background save answers with JSON or nothing.
        return "text/html" not in (response.get("Content-Type") or "")
    return False


class DataVersionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.data_version = request.COOKIES.get(COOKIE, "")
        response = self.get_response(request)
        if changed_data(request, response):
            version = str(time.time_ns())
            response.set_cookie(COOKIE, version, max_age=365 * 24 * 3600, samesite="Lax", secure=request.is_secure())
            already = response.get("Clear-Site-Data")
            response["Clear-Site-Data"] = (already + ", " if already else "") + '"prefetchCache", "prerenderCache"'
        return response
