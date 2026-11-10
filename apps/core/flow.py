"""The "Record money" shortcut: Home → pick a person → their page opens with
the entry form ready (and the right kind already chosen).

A detail page reads ?record=<TYPE> to preselect the kind and open the form;
a create page carries the same parameter through, so adding a new person
lands straight on that form too.
"""
from urllib.parse import urlencode

from django.contrib import messages
from django.core.cache import cache
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.translation import gettext as _

from .templatetags.ui import money

PARAM = "record"


def record_initial(request, choices, initial=None):
    """`initial` for an entry form, with the kind from ?record= when it is one
    of `choices` (the model's transaction types)."""
    initial = dict(initial or {})
    kind = request.GET.get(PARAM)
    if kind and kind in {value for value, _label in choices}:
        initial["transaction_type"] = kind
    amount = _amount(request.GET.get("amount"))
    if amount is not None:
        initial["amount"] = amount
    return initial


def _amount(raw):
    """A positive amount from a link (?amount=1500.50), else None."""
    from decimal import Decimal, InvalidOperation

    try:
        value = Decimal((raw or "").strip())
    except InvalidOperation:
        return None
    if not value.is_finite() or value <= 0 or value >= Decimal("1e10"):
        return None
    return value.quantize(Decimal("0.01"))


def record_next(request, url_name, pk):
    """After adding a person from the picker, go to their page with the entry
    form open. None when the person wasn't added from the picker."""
    if PARAM not in request.GET:
        return None
    url = reverse(url_name, args=[pk])
    kind = request.GET.get(PARAM)
    if kind:
        url += "?" + urlencode({PARAM: kind})
    return redirect(url + "#record")


def warn_if_overpaid(request, name, remaining):
    """After a payment: one zero too many is easy to type and hard to see later. It's saved all the same
    (paying ahead is real), but said out loud."""
    if remaining < 0:
        messages.warning(request, _("That's %(extra)s more than the balance with %(name)s. If it was a typing slip, edit the entry.") % {
            "extra": money(-remaining), "name": name})


def once_an_hour(key):
    """True the first time in an hour. A page that sends mail on the way uses it: when mail is down, every
    visit would otherwise wait out the timeout, and two tabs opening together would send it twice."""
    return cache.add(f"once-an-hour:{key}", 1, 60 * 60)
