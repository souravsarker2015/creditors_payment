"""Download everything: one CSV per kind of farm record, zipped.

For the farm's owner — the records are theirs to keep, open in Excel or move
elsewhere. Deleted records are left out; linked records are written by name
(“Rui”, “East pond”) with their number beside them, so the sheets read on
their own and can still be matched up.
"""
import csv
import io
import zipfile
from datetime import date

from django.apps import apps
from django.db import models
from django.http import HttpResponse
from django.utils import timezone
from django.utils.text import capfirst, slugify

from .models import BusinessBaseModel

SKIP_FIELDS = {"business", "is_deleted", "deleted_at", "created_by", "updated_by"}


def farm_models():
    """Every kind of business record, in app order."""
    out = []
    for model in apps.get_models():
        if issubclass(model, BusinessBaseModel) and not model._meta.abstract:
            out.append(model)
    return out


def _columns(model):
    cols = []
    for f in model._meta.concrete_fields:
        if f.name in SKIP_FIELDS:
            continue
        cols.append(f)
    return cols


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
        return timezone.localtime(value).strftime("%Y-%m-%d %H:%M")
    if isinstance(f, models.BooleanField):
        return "Yes" if value else "No"
    return value


def _sheet(model, business):
    cols = _columns(model)
    header = []
    for f in cols:
        label = capfirst(str(f.verbose_name)) if f.name != "id" else "ID"
        header.append(label)
        if isinstance(f, models.ForeignKey):
            header.append(f"{label} (ID)")
    buf = io.StringIO()
    buf.write("﻿")          # so Excel opens Bangla text correctly
    writer = csv.writer(buf)
    writer.writerow(header)
    related = [f.name for f in cols if isinstance(f, models.ForeignKey)]
    qs = model.objects.filter(business=business).select_related(*related).order_by("pk")
    rows = 0
    for obj in qs.iterator(chunk_size=500) if not related else qs:
        line = []
        for f in cols:
            line.append(_cell(obj, f))
            if isinstance(f, models.ForeignKey):
                line.append(getattr(obj, f.attname) or "")
        writer.writerow(line)
        rows += 1
    return buf.getvalue(), rows


def build_zip(business):
    """(zip bytes, [(file name, rows)])."""
    out = io.BytesIO()
    made = []
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for model in farm_models():
            text, rows = _sheet(model, business)
            if not rows:
                continue
            name = f"{model._meta.app_label.replace('business_', '')}-{model._meta.model_name}.csv"
            z.writestr(name, text.encode("utf-8"))
            made.append((name, rows))
        index = "\n".join(f"{name}\t{rows} rows" for name, rows in made)
        z.writestr("README.txt", f"{business.name}\nDownloaded {date.today():%d %b %Y}\n\n{index}\n")
    return out.getvalue(), made


def zip_response(business):
    data, _ = build_zip(business)
    response = HttpResponse(data, content_type="application/zip")
    name = slugify(business.name) or "farm"
    response["Content-Disposition"] = f'attachment; filename="{name}-records-{date.today():%Y%m%d}.zip"'
    response["Cache-Control"] = "private, no-store"
    return response
