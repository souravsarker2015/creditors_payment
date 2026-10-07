"""The activity log, readable: field labels instead of column names, linked
records by name, numbers without trailing zeros, and the app's own worked-out
columns (kg in base units, totals…) left out."""
import re

from django.apps import apps
from django.db import models
from django.utils.text import capfirst
from django.utils.translation import gettext as _

SKIP = {"is_deleted", "deleted_at", "id"}
_ZEROS = re.compile(r"(\d+\.\d*?[1-9])0+(?!\d)|(\d+)\.0+(?!\d)")


def tidy(text):
    """“6.000000 kg” → “6 kg”, “60.500” → “60.5”."""
    return _ZEROS.sub(lambda m: m.group(1) or m.group(2), str(text))


def _model(label):
    try:
        return apps.get_model(label)
    except (LookupError, ValueError):
        return None


def _value(field, value, cache):
    if value in (None, ""):
        return "—"
    if field is None:
        return tidy(value)
    if isinstance(field, models.BooleanField):
        return _("Yes") if value in (True, "True") else _("No")
    if isinstance(field, models.ForeignKey):
        key = (field.related_model, value)
        if key not in cache:
            manager = getattr(field.related_model, "all_objects", field.related_model._base_manager)
            obj = manager.filter(pk=value).first()
            cache[key] = tidy(obj) if obj is not None else f"#{value}"
        return cache[key]
    if field.choices:
        return str(dict(field.flatchoices).get(value, value))
    return tidy(value)


def describe(entries):
    """Adds `.title` and `.change_list` [(label, before, after)] to each log entry."""
    cache = {}
    for a in entries:
        model = _model(a.model)
        rows = []
        for name, pair in (a.changes or {}).items():
            if name in SKIP or not isinstance(pair, (list, tuple)) or len(pair) != 2:
                continue
            field = None
            if model is not None:
                try:
                    field = model._meta.get_field(name)
                except Exception:
                    field = None
                if field is not None and not field.editable:
                    continue          # worked out by the app, not typed in
            label = capfirst(str(field.verbose_name)) if field is not None else name.replace("_", " ").capitalize()
            before, after = _value(field, pair[0], cache), _value(field, pair[1], cache)
            if before != after:     # "0" saved as "0.00" isn't a change anyone made
                rows.append((label, before, after))
        a.change_list = rows
        a.title = tidy(a.object_repr)
    return entries
