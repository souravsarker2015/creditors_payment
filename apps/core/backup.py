"""Whole-system backup and restore: one .zip file with every record and every
uploaded photo, for moving FinTrack to another server or going back in time.

The file
    manifest.json   what is inside: counts per table, the app version
                    (migrations) it came from, and a SHA-256 for every file
    data.json       every row, in Django's JSON format, ids kept as they are
    media/...       uploaded files (pond photos, receipts)

JSON, not an .sql dump: an .sql file only loads into the same kind of database
it came from, while this loads into SQLite or PostgreSQL alike.

Restoring REPLACES everything with the backup — it never merges. All rows keep
their original ids, so the result is exactly the backed-up system: restoring
the same file twice gives the same data, never duplicates, and exporting right
after a restore gives the same data.json. It runs as one transaction: before
it commits, every link between records is checked and every table's count is
compared with the manifest. Any mismatch undoes the whole restore. The current
data is saved to a file on the server first, so a restore can itself be undone.
"""
import hashlib
import json
import re
from datetime import datetime
import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core import serializers
from django.core.files.base import File
from django.core.files.storage import default_storage
from django.core.management.color import no_style
from django.db import DatabaseError, IntegrityError, connection, models, transaction
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.operations.special import RunPython, RunSQL
from django.db.migrations.recorder import MigrationRecorder
from django.utils import timezone
from django.utils.translation import gettext as _

FORMAT = "fintrack-backup"
VERSION = 1
MAX_UNPACKED = 2 * 1024 ** 3        # refuse files that unpack to more than 2 GB


class BackupError(Exception):
    """A backup that can't be used. The message is shown to the admin as is."""


# ── What goes in ────────────────────────────────────────────────────────────

def backup_models():
    """Every table with people's data: the project's own models plus users and groups.
    Content types and permissions are rebuilt by `migrate` on every server, so
    they are referred to by name instead (see _refs)."""
    found = [m for m in apps.get_models() if m.__module__.startswith("apps.") and m._meta.managed and not m._meta.proxy]
    return sorted(found + [get_user_model(), Group], key=lambda m: m._meta.label_lower)


def cleared_models():
    """Tables that aren't backed up but point at users: admin history and
    sign-in sessions. They are emptied on restore (everyone signs in again)."""
    keep = set(backup_models()) | {ContentType, Permission}
    return [m for m in apps.get_models() if m not in keep and m._meta.managed and not m._meta.proxy]


def _tables(model_list):
    names = []
    for m in model_list:
        names.append(m._meta.db_table)
        names += [f.remote_field.through._meta.db_table for f in m._meta.local_many_to_many if f.remote_field.through._meta.auto_created]
    return names


def _file_fields(model):
    return [f.attname for f in model._meta.concrete_fields if isinstance(f, models.FileField)]


def _ref_fields(model):
    """Fields that point at a content type or permission: stored by name, mapped back on restore."""
    out = {}
    for f in model._meta.get_fields():
        if f.is_relation and f.concrete and f.related_model in (ContentType, Permission):
            out[f.name] = "contenttype" if f.related_model is ContentType else "permission"
    return out


def _applied_migrations():
    applied = {}
    for app, name in MigrationRecorder(connection).applied_migrations():
        applied.setdefault(app, []).append(name)
    return {app: sorted(names) for app, names in sorted(applied.items())}


def _sha256(path_or_bytes):
    h = hashlib.sha256()
    if isinstance(path_or_bytes, bytes):
        h.update(path_or_bytes)
    else:
        with open(path_or_bytes, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
    return h.hexdigest()


def current_counts():
    return {m._meta.label_lower: m._base_manager.count() for m in backup_models()}


# ── Export ──────────────────────────────────────────────────────────────────

# Django's JSON keeps times to the millisecond and writes ".000" when the
# leftover microseconds round to nothing — but the same time read back (now
# exactly on the second) is written without it. Dropping an empty ".000"
# makes a backup of restored data identical to the original.
_ZERO_MS = re.compile(r"(\d{2}:\d{2}:\d{2})\.000(?=Z|[+-]\d{2}:\d{2}|$)")


def _dump_rows():
    """Every row as a list of Django-serialized dicts, in a fixed order (table, then id),
    so two exports of the same data are identical."""
    rows, counts = [], {}
    for model in backup_models():
        objs = json.loads(serializers.serialize("json", model._base_manager.order_by("pk")))
        m2m = [f.name for f in model._meta.many_to_many]
        times = [f.name for f in model._meta.concrete_fields if f.get_internal_type() in ("DateTimeField", "TimeField")]
        for o in objs:
            for name in m2m:
                o["fields"][name] = sorted(o["fields"].get(name) or [])
            for name in times:
                value = o["fields"].get(name)
                if isinstance(value, str):
                    o["fields"][name] = _ZERO_MS.sub(r"\1", value)
        counts[model._meta.label_lower] = len(objs)
        rows += objs
    return rows, counts


def _refs():
    return {
        "contenttype": {str(ct.pk): [ct.app_label, ct.model] for ct in ContentType.objects.all()},
        "permission": {str(p.pk): [p.content_type.app_label, p.content_type.model, p.codename]
                       for p in Permission.objects.select_related("content_type")},
    }


def write_backup(target, user=None):
    """Write a backup .zip to `target` (a path or a writable binary file). Returns the manifest."""
    with transaction.atomic():               # one consistent moment, even while people keep working
        rows, counts = _dump_rows()
        refs = _refs()
        media = []
        for model in backup_models():
            names = _file_fields(model)
            if not names:
                continue
            for values in model._base_manager.order_by("pk").values_list(*names):
                media += [v for v in values if v]
    data = json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    manifest = {
        "format": FORMAT,
        "version": VERSION,
        "created_at": timezone.now().isoformat(timespec="seconds"),
        "created_by": getattr(user, "username", "") or "",
        "database": connection.vendor,
        "migrations": _applied_migrations(),
        "counts": counts,
        "total": sum(counts.values()),
        "refs": refs,
        "files": {"data.json": {"sha256": _sha256(data), "size": len(data)}},
    }
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        z.writestr("data.json", data)
        for name in sorted(set(media)):
            if not default_storage.exists(name):
                continue                      # a record whose file was already gone: nothing to copy
            with default_storage.open(name, "rb") as fh:
                blob = fh.read()
            arc = "media/" + name
            z.writestr(arc, blob)
            manifest["files"][arc] = {"sha256": _sha256(blob), "size": len(blob)}
        z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    return manifest


def backup_filename(prefix="fintrack-backup"):
    return f"{prefix}-{timezone.localtime():%Y-%m-%d-%H%M%S}.zip"


# ── Backups kept on the server ──────────────────────────────────────────────

def backup_dir():
    path = Path(getattr(settings, "BACKUP_DIR", Path(settings.BASE_DIR) / "backups"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_on_server(prefix="fintrack-backup", user=None):
    path = backup_dir() / backup_filename(prefix)
    tmp = path.with_suffix(".part")
    try:
        write_backup(tmp, user)
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)
    return path


def server_backups():
    out = []
    for p in sorted(backup_dir().glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True):
        st = p.stat()
        out.append({"name": p.name, "size": st.st_size, "when": datetime.fromtimestamp(st.st_mtime, tz=timezone.get_current_timezone()),
                    "automatic": p.name.startswith("before-restore")})
    return out


def server_backup_path(name):
    """The path of a backup kept on the server, or None (never anything outside the folder)."""
    if not name or name != os.path.basename(name) or not name.endswith(".zip"):
        return None
    path = backup_dir() / name
    return path if path.is_file() else None


def incoming_dir():
    path = backup_dir() / ".incoming"
    path.mkdir(parents=True, exist_ok=True)
    cutoff = timezone.now().timestamp() - 24 * 3600
    for old in path.glob("*.zip"):          # uploads nobody went on to restore
        if old.stat().st_mtime < cutoff:
            old.unlink(missing_ok=True)
    return path


# ── Reading and checking a backup ───────────────────────────────────────────

@dataclass
class Backup:
    path: Path
    manifest: dict
    rows: list
    media: list = field(default_factory=list)
    notes: list = field(default_factory=list)       # things worth knowing that don't block a restore

    @property
    def counts(self):
        return self.manifest["counts"]

    @property
    def admins(self):
        return sorted(r["fields"]["username"] for r in self.rows
                      if r["model"] == get_user_model()._meta.label_lower and r["fields"].get("is_superuser") and r["fields"].get("is_active"))


def _safe_member(name):
    p = PurePosixPath(name)
    return not p.is_absolute() and ".." not in p.parts and "\\" not in name


def read_backup(path):
    """Open a backup file and check everything before anything is changed. Raises BackupError."""
    path = Path(path)
    if not zipfile.is_zipfile(path):
        raise BackupError(_("This is not a FinTrack backup file. Choose the .zip file you downloaded from “Backup & restore”."))
    with zipfile.ZipFile(path) as z:
        infos = z.infolist()
        if sum(i.file_size for i in infos) > MAX_UNPACKED:
            raise BackupError(_("This file is too large to restore here (over 2 GB unpacked)."))
        names = {i.filename for i in infos if not i.is_dir()}
        if "manifest.json" not in names or "data.json" not in names:
            raise BackupError(_("This is not a FinTrack backup file. Choose the .zip file you downloaded from “Backup & restore”."))
        try:
            manifest = json.loads(z.read("manifest.json"))
        except ValueError:
            raise BackupError(_("The backup file is damaged (its contents list can't be read)."))
        if manifest.get("format") != FORMAT:
            raise BackupError(_("This is not a FinTrack backup file. Choose the .zip file you downloaded from “Backup & restore”."))
        if int(manifest.get("version", 0)) > VERSION:
            raise BackupError(_("This backup was made by a newer version of FinTrack. Update this server first."))
        listed = manifest.get("files") or {}
        if set(listed) != names - {"manifest.json"} or not all(_safe_member(n) for n in names):
            raise BackupError(_("The backup file is damaged or was changed: its files don't match its contents list."))
        for name, meta in listed.items():
            if _sha256(z.read(name)) != meta.get("sha256"):
                raise BackupError(_("The backup file is damaged or was changed after it was made (%(name)s doesn't match). Download a fresh copy.") % {"name": name})
        try:
            rows = json.loads(z.read("data.json"))
        except ValueError:
            raise BackupError(_("The backup file is damaged (its data can't be read)."))
    media = sorted(n[len("media/"):] for n in names if n.startswith("media/"))
    backup = Backup(path=path, manifest=manifest, rows=rows, media=media)
    _check_tables(backup)
    _check_version(backup)
    if not backup.admins:
        raise BackupError(_("This backup has no active admin account, so nobody could sign in after restoring it."))
    return backup


def _check_tables(backup):
    known = {m._meta.label_lower for m in backup_models()}
    counted = {}
    for r in backup.rows:
        if not isinstance(r, dict) or r.get("model") not in known or "pk" not in r or not isinstance(r.get("fields"), dict):
            raise BackupError(_("The backup has data this version of FinTrack doesn't know (%(model)s).") % {"model": str(r.get("model") if isinstance(r, dict) else r)[:60]})
        counted[r["model"]] = counted.get(r["model"], 0) + 1
    expected = {k: v for k, v in backup.counts.items() if v}
    if counted != expected:
        raise BackupError(_("The backup file is damaged: the number of records doesn't match its contents list."))


def _check_version(backup):
    """The backup must come from this version of FinTrack (same migrations), or an
    earlier one whose later changes only added things. Anything else could leave
    the data not matching the code, so it is refused with what to do instead."""
    loader = MigrationLoader(connection, ignore_no_migrations=True)
    here = {(a, n) for a, names in _applied_migrations().items() for n in names}
    there = {(a, n) for a, names in (backup.manifest.get("migrations") or {}).items() for n in names}
    if there - set(loader.graph.nodes):
        raise BackupError(_("This backup was made by a newer version of FinTrack. Update this server's code, run “python manage.py migrate”, then restore."))
    if there - here:
        raise BackupError(_("This server's database isn't up to date. Run “python manage.py migrate”, then restore."))
    later = sorted(here - there)
    if not later:
        return
    for key in later:
        node = loader.graph.nodes.get(key)
        if node and any(isinstance(op, (RunPython, RunSQL)) for op in node.operations):
            raise BackupError(_("This backup is from an older version of FinTrack, and the update since then changed existing data (%(name)s). Restore it on a server with the older version, then update that server.") % {"name": ".".join(key)})
    backup.notes.append(_("This backup was made with an older version of FinTrack. The updates since then only added new things, so it restores safely."))


# ── Restore ─────────────────────────────────────────────────────────────────

def _map_refs(backup):
    """Content types and permissions get different ids on every server: map the backup's ids by name."""
    refs = backup.manifest.get("refs") or {}
    ct_map, perm_map, missing = {}, {}, set()
    for old, (app, model) in (refs.get("contenttype") or {}).items():
        ct_map[int(old)] = ContentType.objects.get_or_create(app_label=app, model=model)[0].pk
    perms = {(p.content_type.app_label, p.content_type.model, p.codename): p.pk for p in Permission.objects.select_related("content_type")}
    for old, key in (refs.get("permission") or {}).items():
        new = perms.get(tuple(key))
        if new:
            perm_map[int(old)] = new
        else:
            missing.add(".".join(key))
    fields = {m._meta.label_lower: _ref_fields(m) for m in backup_models()}
    for r in backup.rows:
        for name, kind in fields.get(r["model"], {}).items():
            value = r["fields"].get(name)
            table = ct_map if kind == "contenttype" else perm_map
            if isinstance(value, list):
                r["fields"][name] = sorted(table[v] for v in value if v in table)
            elif value is not None:
                if value not in table:
                    raise BackupError(_("The backup refers to a kind of record this server doesn't have (%(name)s).") % {"name": name})
                r["fields"][name] = table[value]
    return missing


def _wipe(tables):
    qn = connection.ops.quote_name
    with connection.cursor() as cursor:
        for table in tables:
            cursor.execute(f"DELETE FROM {qn(table)}")


def restore_backup(backup, user=None, keep_copy=True):
    """Replace all data with the backup's. Returns {"counts": …, "safety_copy": path or None}.
    On any problem nothing is changed and BackupError is raised."""
    safety = save_on_server("before-restore", user) if keep_copy else None
    included = backup_models()
    tables = _tables(included)
    try:
        with transaction.atomic():
            missing_perms = _map_refs(backup)
            with connection.constraint_checks_disabled():
                _wipe(_tables(cleared_models()) + tables)
                for obj in serializers.deserialize("json", json.dumps(backup.rows), ignorenonexistent=False):
                    obj.save()
            connection.check_constraints(table_names=tables)
            with connection.cursor() as cursor:
                for sql in connection.ops.sequence_reset_sql(no_style(), included):
                    cursor.execute(sql)
            now = current_counts()
            expected = {m._meta.label_lower: backup.counts.get(m._meta.label_lower, 0) for m in included}
            if now != expected:
                wrong = sorted(k for k in expected if now.get(k) != expected[k])
                raise BackupError(_("The restore was stopped: the records loaded don't match the backup (%(tables)s). Nothing was changed.") % {"tables": ", ".join(wrong[:5])})
    except BackupError:
        raise
    except (IntegrityError, DatabaseError, serializers.base.DeserializationError, ValueError, LookupError) as exc:
        raise BackupError(_("The restore was stopped because the backup's records don't fit together (%(error)s). Nothing was changed.") % {"error": str(exc)[:200]})
    _restore_media(backup)
    return {"counts": backup.counts, "safety_copy": safety, "missing_permissions": sorted(missing_perms)}


def _restore_media(backup):
    """Put the uploaded files back at the same paths (after the data is safely in)."""
    if not backup.media:
        return
    with zipfile.ZipFile(backup.path) as z:
        for name in backup.media:
            if default_storage.exists(name):
                default_storage.delete(name)
            with z.open("media/" + name) as src, tempfile.TemporaryFile() as tmp:
                shutil.copyfileobj(src, tmp)
                tmp.seek(0)
                default_storage.save(name, File(tmp, name=os.path.basename(name)))


# ── Summaries for the page ──────────────────────────────────────────────────

def area_of(label):
    app = label.split(".")[0]
    if label in ("auth.user", "auth.group") or app in ("accounts", "core"):
        return "people"
    config = apps.get_app_config(app)
    return "business" if config.name.startswith("apps.business.") else "personal"


def summary(counts_now, counts_backup=None):
    """Rows for the page: per area (People, Personal, Business), each table's count now and in the backup."""
    groups = {"people": [], "personal": [], "business": []}
    for model in backup_models():
        label = model._meta.label_lower
        now = counts_now.get(label, 0)
        then = (counts_backup or {}).get(label, 0) if counts_backup is not None else None
        if not now and not then:
            continue
        groups[area_of(label)].append({"label": label, "name": str(model._meta.verbose_name_plural).capitalize(),
                                       "app": str(apps.get_app_config(model._meta.app_label).verbose_name).split("·")[-1].strip(), "now": now, "backup": then})
    titles = {"people": _("Users and settings"), "personal": _("Personal ledgers"), "business": _("Fish farm business")}
    out = []
    for key in ("people", "personal", "business"):
        rows = sorted(groups[key], key=lambda r: r["name"].lower())
        out.append({"key": key, "title": titles[key], "rows": rows,
                    "now": sum(r["now"] for r in rows),
                    "backup": sum(r["backup"] or 0 for r in rows) if counts_backup is not None else None})
    return out
