from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from .models import DeletedItem
from .services import KEEP_DAYS, CannotRestore, forget, purge_old, restore


@login_required
def trash_list_view(request):
    purge_old(request.user)
    items = DeletedItem.objects.filter(user=request.user)
    return render(request, "trash/list.html", {"items": items, "keep_days": KEEP_DAYS})


def _back(request, fallback):
    nxt = request.POST.get("next") or ""
    if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return nxt
    return fallback


@login_required
@require_POST
def restore_view(request, pk):
    item = get_object_or_404(DeletedItem, pk=pk, user=request.user)
    label, back = item.label, item.back_url
    try:
        restore(item)
    except CannotRestore:
        messages.error(request, _("“%(what)s” can't be put back: something it belonged to has been removed for good.") % {"what": label})
        return redirect("trash_list")
    messages.success(request, _("Restored: %(what)s") % {"what": label})
    return redirect(_back(request, back or "trash_list"))


@login_required
@require_POST
def forget_view(request, pk):
    item = get_object_or_404(DeletedItem, pk=pk, user=request.user)
    forget([item])
    messages.success(request, _("Deleted for good."))
    return redirect("trash_list")


@login_required
@require_POST
def empty_view(request):
    forget(DeletedItem.objects.filter(user=request.user))
    messages.success(request, _("Recently deleted is empty."))
    return redirect("trash_list")
