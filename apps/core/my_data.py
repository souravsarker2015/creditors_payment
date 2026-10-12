"""Download my data: every personal record of the signed-in person, one CSV
per kind, zipped — their own copy, readable in Excel — plus the same records
in a form that can be restored (backup/, see personal_backup.py). Farm records
have their own download (the farm owner's, under Farm setup)."""
import csv
import io
import os
import shutil
import uuid
import zipfile

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import models
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.text import capfirst
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

SKIP_FIELDS = {"user", "owner", "feed_token"}   # whose it is, and a private calendar address


def personal_models():
    """[(model, lookup)]: everything one person keeps here, minus sign-in
    secrets (see personal_backup.owned_models)."""
    from .personal_backup import owned_models

    return owned_models()


def _reader(f):
    """How one column is written: worked out once per column, not per cell."""
    if isinstance(f, models.ForeignKey):
        def read(obj):
            related = getattr(obj, f.name, None)
            return str(related) if related is not None else ""
        return read
    name = f.attname
    if isinstance(f, models.FileField):
        return lambda obj: getattr(obj, name).name or ""
    if f.choices:
        labels = {k: str(v) for k, v in f.flatchoices}
        return lambda obj: "" if getattr(obj, name) is None else labels.get(getattr(obj, name), getattr(obj, name))
    if isinstance(f, models.DateTimeField):
        tz = timezone.get_current_timezone()

        def read(obj):
            value = getattr(obj, name)
            if value is None:
                return ""
            return (value.astimezone(tz) if timezone.is_aware(value) else value).strftime("%Y-%m-%d %H:%M")
        return read
    if isinstance(f, models.BooleanField):
        return lambda obj: "" if getattr(obj, name) is None else ("Yes" if getattr(obj, name) else "No")
    return lambda obj: "" if getattr(obj, name) is None else getattr(obj, name)


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
            readers = [_reader(f) for f in cols]
            w.writerows([read(obj) for read in readers] for obj in rows)
            name = f"{model._meta.app_label}-{model._meta.model_name}.csv"
            z.writestr(name, buf.getvalue().encode("utf-8"))
            made.append((name, len(rows)))
        from .personal_backup import add_to_zip

        add_to_zip(z, user)
        index = "\n".join(f"{n}\t{c} rows" for n, c in made)
        z.writestr("README.txt", f"{user.get_full_name() or user.username}\nDownloaded {timezone.localtime():%d %b %Y, %H:%M}\n\n"
                                 "The .csv files open in Excel. To bring everything back - on this server or another one -\n"
                                 "upload this whole .zip file on the \"My data & backup\" page.\n\n"
                                 f"{index}\n")
    return out.getvalue(), made


@login_required
def my_data_view(request):
    from .personal_backup import filename

    data, _ = build_zip(request.user)
    response = HttpResponse(data, content_type="application/zip")
    response["Content-Disposition"] = f'attachment; filename="{filename(request.user)}"'
    response["Cache-Control"] = "private, no-store"
    return response


# ── Backup & restore my data (the page) ─────────────────────────────────────

PENDING = "my_backup_pending"


def _staged(request):
    """The uploaded backup waiting for "Restore", if it is this person's."""
    from . import backup as bk

    name = request.session.get(PENDING) or ""
    if not name or name != os.path.basename(name) or not name.startswith(f"u{request.user.pk}-"):
        return None
    path = bk.incoming_dir() / name
    return path if path.is_file() else None


def _drop_staged(request):
    path = _staged(request)
    if path:
        path.unlink(missing_ok=True)
    request.session.pop(PENDING, None)


@login_required
def my_data_page_view(request):
    from . import personal_backup as pb

    counts = pb.counts_for(request.user)
    return render(request, "backup/mine.html", {
        "areas": pb.summary(counts),
        "total": sum(counts.values()),
        "copies": pb.saved_copies(request.user),
        "has_pending": _staged(request) is not None,
    })


def _stage(request, source):
    from . import backup as bk
    from . import personal_backup as pb

    _drop_staged(request)
    staged = bk.incoming_dir() / f"u{request.user.pk}-{uuid.uuid4().hex}.zip"
    with open(staged, "wb") as out:
        if hasattr(source, "chunks"):
            for chunk in source.chunks():
                out.write(chunk)
        else:
            with open(source, "rb") as src:
                shutil.copyfileobj(src, out)
    try:
        pb.read(staged)
    except bk.BackupError as exc:
        staged.unlink(missing_ok=True)
        messages.error(request, str(exc))
        return redirect("my_data_page")
    request.session[PENDING] = staged.name
    return redirect("my_data_restore")


@login_required
@require_POST
def my_data_upload_view(request):
    upload = request.FILES.get("backup")
    if not upload:
        messages.error(request, _("Choose your backup file first."))
        return redirect("my_data_page")
    return _stage(request, upload)


@login_required
def my_data_copy_view(request, name):
    from . import personal_backup as pb

    path = pb.copy_path(request.user, name)
    if not path:
        raise Http404
    if request.method == "POST":
        return _stage(request, path)
    response = FileResponse(open(path, "rb"), as_attachment=True, filename=path.name, content_type="application/zip")
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
def my_data_restore_view(request):
    """GET: what's in the file, next to what's here now. POST: replace."""
    from datetime import datetime

    from . import backup as bk
    from . import personal_backup as pb

    path = _staged(request)
    if not path:
        messages.info(request, _("Choose your backup file to restore."))
        return redirect("my_data_page")
    try:
        backup = pb.read(path)
    except bk.BackupError as exc:
        _drop_staged(request)
        messages.error(request, str(exc))
        return redirect("my_data_page")
    if request.method == "POST":
        if request.POST.get("confirm") != "yes":
            messages.error(request, _("Tick the box to say your current records may be replaced."))
            return redirect("my_data_restore")
        try:
            result = pb.restore(request.user, backup)
        except bk.BackupError as exc:
            messages.error(request, str(exc))
            return redirect("my_data_restore")
        _drop_staged(request)
        messages.success(request, _("Restored %(total)s records from your backup.") % {"total": result["total"]})
        if result["copy"]:
            from django.utils.formats import date_format

            messages.info(request, _("Your records from before were saved. To undo, restore the copy from %(when)s below.")
                          % {"when": date_format(timezone.localtime(), "j M Y, H:i")})
        return redirect("my_data_page")
    counts = pb.counts_for(request.user)
    try:
        created = datetime.fromisoformat(backup.manifest.get("created_at", ""))
    except ValueError:
        created = None
    return render(request, "backup/mine_preview.html", {
        "manifest": backup.manifest,
        "created": created,
        "areas": pb.summary(counts, backup.manifest.get("counts") or {}),
        "total_now": sum(counts.values()),
        "total_backup": backup.manifest.get("total", 0),
        "photos": len(backup.media),
        "other_account": backup.manifest.get("username") != request.user.get_username(),
        "notes": backup.notes,
    })


@login_required
@require_POST
def my_data_cancel_view(request):
    _drop_staged(request)
    return redirect("my_data_page")
