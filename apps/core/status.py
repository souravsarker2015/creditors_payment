"""Shared Active/Inactive handling for records that can be archived
(creditors, debtors, shops, income sources, categories, members, ...).

Inactive records are hidden from list pages (by default) and from pickers
in forms, but their history still counts toward every total — marking a
record inactive never changes the numbers, it only declutters the UI.
"""

from django.contrib import messages
from django.db.models import Count, Q
from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _

STATUS_ACTIVE = "active"
STATUS_INACTIVE = "inactive"
STATUS_ALL = "all"
STATUS_CHOICES = (STATUS_ACTIVE, STATUS_INACTIVE, STATUS_ALL)


def apply_status_filter(request, qs):
    """Reads the `status` GET param and narrows `qs` accordingly.

    Returns (status, filtered_qs, counts) where counts holds the number of
    active / inactive / all records in `qs` *before* the status filter, so
    the tabs can show how many records each one would reveal.
    """
    status = request.GET.get("status", STATUS_ACTIVE).strip().lower()
    if status not in STATUS_CHOICES:
        status = STATUS_ACTIVE

    counts = qs.aggregate(
        active=Count("pk", filter=Q(is_active=True)),
        inactive=Count("pk", filter=Q(is_active=False)),
    )
    counts["all"] = counts["active"] + counts["inactive"]

    if status == STATUS_ACTIVE:
        qs = qs.filter(is_active=True)
    elif status == STATUS_INACTIVE:
        qs = qs.filter(is_active=False)
    return status, qs, counts


def active_or_current(qs, current_pk=None):
    """Active records, plus the currently selected one (so editing an old
    entry that points at an inactive record doesn't silently drop it)."""
    condition = Q(is_active=True)
    if current_pk:
        condition |= Q(pk=current_pk)
    return qs.filter(condition)


def toggle_active(request, obj, fallback_url):
    """Flips obj.is_active, flashes a message and redirects back to the
    page the request came from (via a `next` field), else `fallback_url`."""
    obj.is_active = not obj.is_active
    obj.save(update_fields=["is_active"])
    if obj.is_active:
        messages.success(request, _("'%(name)s' is active again.") % {"name": obj})
    else:
        messages.success(
            request,
            _("'%(name)s' marked inactive. It's hidden from lists and pickers, but its history still counts in every total.")
            % {"name": obj},
        )

    next_url = request.POST.get("next", "")
    if next_url and url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return redirect(next_url)
    return redirect(fallback_url)
