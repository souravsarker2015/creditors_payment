"""Backup & restore pages (site admins only). The work is done in backup.py."""
import os
import shutil
from datetime import datetime
import tempfile
import uuid
from functools import wraps

from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from . import backup as bk

SESSION_KEY = "backup_pending"


def site_admin_required(view):
    """Only a site admin (superuser) may export or replace everyone's data."""
    @wraps(view)
    @login_required
    def wrapped(request, *args, **kwargs):
        if not request.user.is_superuser:
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapped


@site_admin_required
def backup_home_view(request):
    counts = bk.current_counts()
    return render(request, "backup/home.html", {
        "areas": bk.summary(counts),
        "total": sum(counts.values()),
        "server_backups": bk.server_backups(),
        "backup_dir": bk.backup_dir(),
    })


@site_admin_required
@require_POST
def backup_download_view(request):
    """Build the backup into a temporary file and send it (it is never kept on the server)."""
    tmp = tempfile.TemporaryFile()
    bk.write_backup(tmp, request.user)
    tmp.seek(0)
    return FileResponse(tmp, as_attachment=True, filename=bk.backup_filename(), content_type="application/zip")


@site_admin_required
@require_POST
def backup_save_view(request):
    path = bk.save_on_server(user=request.user)
    messages.success(request, _("Backup saved on this server: %(name)s") % {"name": path.name})
    return redirect("backup_home")


@site_admin_required
def backup_file_view(request, name):
    path = bk.server_backup_path(name)
    if not path:
        raise Http404
    return FileResponse(open(path, "rb"), as_attachment=True, filename=path.name, content_type="application/zip")


@site_admin_required
@require_POST
def backup_delete_view(request, name):
    path = bk.server_backup_path(name)
    if path:
        path.unlink()
        messages.success(request, _("Deleted %(name)s.") % {"name": name})
    return redirect("backup_home")


def _stage(request, source):
    """Copy a backup into the waiting area, check it, and remember it for the confirm step."""
    staged = bk.incoming_dir() / f"{uuid.uuid4().hex}.zip"
    with open(staged, "wb") as out:
        if hasattr(source, "chunks"):
            for chunk in source.chunks():
                out.write(chunk)
        else:
            with open(source, "rb") as src:
                shutil.copyfileobj(src, out)
    try:
        bk.read_backup(staged)
    except bk.BackupError as exc:
        staged.unlink(missing_ok=True)
        messages.error(request, str(exc))
        return redirect("backup_home")
    old = request.session.get(SESSION_KEY)
    if old:
        (bk.incoming_dir() / old).unlink(missing_ok=True)
    request.session[SESSION_KEY] = staged.name
    return redirect("backup_preview")


@site_admin_required
@require_POST
def backup_upload_view(request):
    upload = request.FILES.get("backup")
    if not upload:
        messages.error(request, _("Choose a backup file first."))
        return redirect("backup_home")
    return _stage(request, upload)


@site_admin_required
@require_POST
def backup_use_server_copy_view(request, name):
    path = bk.server_backup_path(name)
    if not path:
        raise Http404
    return _stage(request, path)


def _pending(request):
    name = request.session.get(SESSION_KEY) or ""
    path = bk.incoming_dir() / name if name and name == os.path.basename(name) else None
    return path if path and path.is_file() else None


@site_admin_required
def backup_preview_view(request):
    path = _pending(request)
    if not path:
        messages.info(request, _("Choose a backup file to restore."))
        return redirect("backup_home")
    try:
        backup = bk.read_backup(path)
    except bk.BackupError as exc:
        messages.error(request, str(exc))
        return redirect("backup_home")
    counts = bk.current_counts()
    try:
        created = datetime.fromisoformat(backup.manifest.get("created_at", ""))
    except ValueError:
        created = None
    return render(request, "backup/preview.html", {
        "manifest": backup.manifest,
        "created": created,
        "areas": bk.summary(counts, backup.counts),
        "total_now": sum(counts.values()),
        "total_backup": backup.manifest.get("total", 0),
        "files": len(backup.media),
        "admins": backup.admins,
        "me_in_backup": request.user.username in backup.admins,
        "notes": backup.notes,
        "error": request.session.pop("backup_error", None),
    })


@site_admin_required
@require_POST
def backup_restore_view(request):
    path = _pending(request)
    if not path:
        return redirect("backup_home")
    if request.POST.get("confirm") != "yes" or not request.user.check_password(request.POST.get("password", "")):
        request.session["backup_error"] = _("Type your own password and tick the box to restore.")
        return redirect("backup_preview")
    try:
        result = bk.restore_backup(bk.read_backup(path), request.user)
    except bk.BackupError as exc:
        request.session["backup_error"] = str(exc)
        return redirect("backup_preview")
    path.unlink(missing_ok=True)
    cache.clear()
    # Every sign-in was part of the old data: sign in again with an account from the backup.
    logout(request)
    total = sum(result["counts"].values())
    messages.success(request, _("Restored %(total)s records from the backup. Sign in with an account from the backup.") % {"total": total})
    if result["safety_copy"]:
        messages.info(request, _("The data from before the restore was saved on the server as %(name)s.") % {"name": result["safety_copy"].name})
    return redirect(reverse("login"))


@site_admin_required
@require_POST
def backup_cancel_view(request):
    path = _pending(request)
    if path:
        path.unlink(missing_ok=True)
    request.session.pop(SESSION_KEY, None)
    return redirect("backup_home")
