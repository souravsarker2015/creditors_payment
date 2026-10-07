"""Download my data: every personal record of the signed-in person, one CSV
per kind, zipped — their own copy, readable in Excel. Farm records have their
own download (the farm owner's, under Farm setup)."""
import csv
import io
import zipfile
from datetime import date

from django.apps import apps
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import models
from django.http import HttpResponse
from django.utils import timezone
from django.utils.text import capfirst, slugify

SKIP_FIELDS = {"user"}


SKIP_MODELS = {"trash.DeletedItem"}   # the recycle bin's own copies


def _own(model):
    if not model.__module__.startswith("apps.") or model.__module__.startswith("apps.business.") or model._meta.label in SKIP_MODELS:
        return False
    try:
        f = model._meta.get_field("user")
    except Exception:
        return False
    return isinstance(f, models.ForeignKey) and f.related_model._meta.label == settings.AUTH_USER_MODEL


def personal_models():
    """[(model, lookup)]: models that belong to one person through a `user`
    field, and their entries that hang off one of those (a creditor's
    payments, a goal's deposits…)."""
    owners = [m for m in apps.get_models() if _own(m)]
    out = [(m, "user") for m in owners]
    for model in apps.get_models():
        if model in owners or not model.__module__.startswith("apps.") or model.__module__.startswith("apps.business."):
            continue
        if model._meta.label in SKIP_MODELS:
            continue
        parent = next((f for f in model._meta.concrete_fields
                       if isinstance(f, models.ForeignKey) and f.related_model in owners and not f.null), None)
        if parent is not None:
            out.append((model, f"{parent.name}__user"))
    return out


def _cell(obj, f):
    if isinstance(f, models.ForeignKey):
        related = getattr(obj, f.name, None)
        return str(related) if related is not None else ""
    value = getattr(obj, f.attname)
    if value is None:
        return ""
    if isinstance(f, models.FileField):
        return value.name if value else ""
    if f.choices:
        return getattr(obj, f"get_{f.name}_display")()
    if isinstance(f, models.DateTimeField):
        return timezone.localtime(value).strftime("%Y-%m-%d %H:%M") if timezone.is_aware(value) else value.strftime("%Y-%m-%d %H:%M")
    if isinstance(f, models.BooleanField):
        return "Yes" if value else "No"
    return value


def build_zip(user):
    out = io.BytesIO()
    made = []
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for model, lookup in personal_models():
            manager = getattr(model, "all_objects", model._default_manager)
            cols = [f for f in model._meta.concrete_fields if f.name not in SKIP_FIELDS]
            related = [f.name for f in cols if isinstance(f, models.ForeignKey)]
            rows = list(manager.filter(**{lookup: user}).select_related(*related).order_by("pk"))
            if not rows:
                continue
            buf = io.StringIO()
            buf.write("﻿")
            w = csv.writer(buf)
            w.writerow([capfirst(str(f.verbose_name)) if f.name != "id" else "ID" for f in cols])
            for obj in rows:
                w.writerow([_cell(obj, f) for f in cols])
            name = f"{model._meta.app_label}-{model._meta.model_name}.csv"
            z.writestr(name, buf.getvalue().encode("utf-8"))
            made.append((name, len(rows)))
        index = "\n".join(f"{n}\t{c} rows" for n, c in made)
        z.writestr("README.txt", f"{user.get_full_name() or user.username}\nDownloaded {date.today():%d %b %Y}\n\n{index}\n")
    return out.getvalue(), made


@login_required
def my_data_view(request):
    data, _ = build_zip(request.user)
    response = HttpResponse(data, content_type="application/zip")
    name = slugify(request.user.username) or "my"
    response["Content-Disposition"] = f'attachment; filename="{name}-fintrack-{date.today():%Y%m%d}.zip"'
    response["Cache-Control"] = "private, no-store"
    return response
