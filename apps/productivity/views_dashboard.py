"""The Dashboard (dashboard.py has the figures): how the last 7, 30 or 90 days went, every part of the app at once —
and, opened at least 3 days after the last one, the progress email (emails.send_progress), asked for by the page
once it's shown so the page never waits for the mail server."""
from django.http import JsonResponse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from . import dashboard, emails
from .access import work_required
from .models import WorkSettings
from .views import render_work


@work_required
def dashboard_view(request):
    try:
        days = int(request.GET.get("days", 7))
    except ValueError:
        days = 7
    days = days if days in dashboard.PERIODS else 7
    s = WorkSettings.for_user(request.user)
    return render_work(request, "work/dashboard.html", {
        "r": dashboard.report(request.user, days=days), "periods": dashboard.PERIODS, "days": days,
        "email_on": s.progress_email, "email_to": request.user.email, "email_due": bool(request.user.email) and emails.progress_due(s),
        "email_last": s.progress_email_sent_at,
    })


@work_required
@require_POST
def email_api(request):
    """action=auto: the 3-day report, if it's due (the page asks on opening); action=now: this page's days, now."""
    if not request.user.email:
        return JsonResponse({"ok": False, "error": _("Add an email address to your account first.")}, status=400)
    if request.POST.get("action") == "now":
        try:
            days = int(request.POST.get("days", 3))
        except ValueError:
            days = 3
        result = emails.send_progress(request.user, days=days if days in (3, *dashboard.PERIODS) else 3, request=request, force=True)
    else:
        result = emails.send_progress(request.user, days=3, request=request)
    if result == "failed":
        return JsonResponse({"ok": False, "error": _("The email couldn't be sent just now. It will try again next time.")}, status=502)
    return JsonResponse({"ok": True, "sent": result == "sent", "to": request.user.email})
