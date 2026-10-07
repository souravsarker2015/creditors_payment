"""The "Record money" shortcut: Home → pick a person → their page opens with
the entry form ready (and the right kind already chosen).

A detail page reads ?record=<TYPE> to preselect the kind and open the form;
a create page carries the same parameter through, so adding a new person
lands straight on that form too.
"""
from urllib.parse import urlencode

from django.shortcuts import redirect
from django.urls import reverse

PARAM = "record"


def record_initial(request, choices, initial=None):
    """`initial` for an entry form, with the kind from ?record= when it is one
    of `choices` (the model's transaction types)."""
    initial = dict(initial or {})
    kind = request.GET.get(PARAM)
    if kind and kind in {value for value, _label in choices}:
        initial["transaction_type"] = kind
    return initial


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
