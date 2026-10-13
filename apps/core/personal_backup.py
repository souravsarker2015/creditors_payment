"""One person's backup: everything they keep in FinTrack (the personal ledgers,
goals, wallets, budgets, the work tracker, their settings and receipt photos)
in the same .zip as their Excel sheets, and the restore that puts it back.

The whole-system backup (backup.py) is for site admins and replaces everyone's
data. This one is for anybody, and only ever touches the signed-in person's
own records — on this server or another one, under the same or a different
username.

The file (made by my_data.build_zip)
    *.csv                   one sheet per kind of record, for Excel
    README.txt
    backup/manifest.json    what is inside, the app version, a SHA-256 per file
    backup/data.json        the records in Django's JSON format
    backup/media/...        their receipt photos

Restoring REPLACES the person's records with the backup's — it never merges,
so restoring the same file twice can't duplicate anything. Records get new
ids, and every link inside the backup is pointed at the new ones; a link to
anything outside it is dropped, so a backup can never reach someone else's
data. It runs as one transaction, and the records from before are saved on
the server first, so the restore can be undone.
"""
import hashlib
import json
import os
import zipfile
from collections import defaultdict
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

from django.apps import apps
from django.conf import settings
from django.core import serializers
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from . import backup as bk

FORMAT = "fintrack-my-backup"
VERSION = 1
PREFIX = "backup/"
# Sign-in secrets and the app's own bookkeeping are never written out.
SKIP_MODELS = {"accounts.twofactor", "accounts.signin", "core.offlinereceipt", "trash.deleteditem"}
OWNER_FIELDS = ("user", "owner")


# ── What belongs to one person ──────────────────────────────────────────────

def _personal_app(model):
    return model.__module__.startswith("apps.") and not model.__module__.startswith("apps.business.") \
        and model._meta.managed and not model._meta.proxy


def _owner_field(model):
    for name in OWNER_FIELDS:
        try:
            f = model._meta.get_field(name)
        except Exception:
            continue
        if f.many_to_one or f.one_to_one:
            if f.related_model._meta.label == settings.AUTH_USER_MODEL:
                return f
    return None


def owned_models():
    """[(model, lookup)] for everything one person owns — through a `user` or
    `owner` field, or by hanging off such a record (a creditor's payments, a
    task's checklist) — ordered so every record comes after those it points at."""
    lookups = {}
    for m in apps.get_models():
        if _personal_app(m) and m._meta.label_lower not in SKIP_MODELS:
            f = _owner_field(m)
            if f is not None:
                lookups[m] = f.name
    grew = True
    while grew:
        grew = False
        for m in apps.get_models():
            if m in lookups or not _personal_app(m) or m._meta.label_lower in SKIP_MODELS:
                continue
            parent = next((f for f in m._meta.concrete_fields
                           if f.many_to_one and f.related_model in lookups and not f.null), None)
            if parent is not None:
                lookups[m] = f"{parent.name}__{lookups[parent.related_model]}"
                grew = True
    order, seen = [], set()

    def visit(model, path=()):
        if model in seen or model in path:
            return
        for f in [*model._meta.concrete_fields, *model._meta.many_to_many]:
            if f.is_relation and f.related_model in lookups and f.related_model is not model:
                visit(f.related_model, path + (model,))
        seen.add(model)
        order.append(model)

    for m in sorted(lookups, key=lambda m: m._meta.label_lower):
        visit(m)
    return [(m, lookups[m]) for m in order]


def _rows(model, lookup, user):
    return model._base_manager.filter(**{lookup: user}).order_by("pk")


def counts_for(user):
    return {m._meta.label_lower: _rows(m, lookup, user).count() for m, lookup in owned_models()}


def _sha256(blob):
    return hashlib.sha256(blob).hexdigest()


# ── Writing ─────────────────────────────────────────────────────────────────

def add_to_zip(z, user):
    """Write the restorable part of a person's backup into an open ZipFile. Returns the manifest."""
    rows, counts, media = [], {}, []
    with transaction.atomic():
        for model, lookup in owned_models():
            objs = bk.serialize_rows(model, _rows(model, lookup, user))
            counts[model._meta.label_lower] = len(objs)
            rows += objs
            files = bk._file_fields(model)
            if files:
                for values in _rows(model, lookup, user).values_list(*files):
                    media += [v for v in values if v]
    data = json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    manifest = {
        "format": FORMAT,
        "version": VERSION,
        "created_at": timezone.now().isoformat(timespec="seconds"),
        "username": user.get_username(),
        "name": user.get_full_name(),
        "migrations": bk._applied_migrations(),
        "counts": counts,
        "total": sum(counts.values()),
        "files": {"data.json": {"sha256": _sha256(data), "size": len(data)}},
    }
    z.writestr(PREFIX + "data.json", data)
    for name in sorted(set(media)):
        if not default_storage.exists(name):
            continue
        with default_storage.open(name, "rb") as fh:
            blob = fh.read()
        z.writestr(PREFIX + "media/" + name, blob)
        manifest["files"]["media/" + name] = {"sha256": _sha256(blob), "size": len(blob)}
    z.writestr(PREFIX + "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    return manifest


def filename(user, when=None):
    from django.utils.text import slugify

    return f"{slugify(user.get_username()) or 'my'}-fintrack-{timezone.localtime(when):%Y-%m-%d-%H%M}.zip"


# ── Copies kept on the server (so a restore can be undone) ──────────────────

KEEP = 3


def own_dir(user):
    path = bk.backup_dir() / "people" / str(user.pk)
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_copy(user):
    from .my_data import build_zip

    data, _made = build_zip(user)
    path = own_dir(user) / f"before-restore-{timezone.localtime():%Y-%m-%d-%H%M%S}.zip"
    path.write_bytes(data)
    for old in sorted(own_dir(user).glob("before-restore-*.zip"))[:-KEEP]:
        old.unlink(missing_ok=True)
    return path


def saved_copies(user):
    from datetime import datetime

    out = []
    for p in sorted(own_dir(user).glob("*.zip"), reverse=True):
        out.append({"name": p.name, "size": p.stat().st_size,
                    "when": datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.get_current_timezone())})
    return out


def copy_path(user, name):
    if not name or name != os.path.basename(name) or not name.endswith(".zip"):
        return None
    path = own_dir(user) / name
    return path if path.is_file() else None


# ── Reading and checking ────────────────────────────────────────────────────

def read(path):
    """Open a personal backup and check it. Returns a namespace with manifest,
    rows, media and notes; raises backup.BackupError with a message for people."""
    path = Path(path)
    wrong = _("This isn't a FinTrack “My data” file. Choose the .zip you downloaded from “My data & backup”.")
    if not zipfile.is_zipfile(path):
        raise bk.BackupError(wrong)
    with zipfile.ZipFile(path) as z:
        infos = z.infolist()
        if sum(i.file_size for i in infos) > bk.MAX_UNPACKED:
            raise bk.BackupError(_("This file is too large to restore here (over 2 GB unpacked)."))
        names = {i.filename for i in infos if not i.is_dir()}
        if "manifest.json" in names and "data.json" in names:
            try:
                fmt = json.loads(z.read("manifest.json")).get("format")
            except ValueError:
                fmt = None
            if fmt == bk.FORMAT:
                raise bk.BackupError(_("This is a backup of the whole system. Only a site admin can restore it, on the “Backup & restore” page."))
        if PREFIX + "manifest.json" not in names:
            if "data.json" in names:
                raise bk.BackupError(_("This is a download from the work tracker. Restore it in Work → Settings → Your data."))
            if any(n.endswith(".csv") for n in names):
                raise bk.BackupError(_("This download was made before backups could be restored, so it only has Excel sheets. Download “My data” again to get a file you can restore."))
            raise bk.BackupError(wrong)
        try:
            manifest = json.loads(z.read(PREFIX + "manifest.json"))
        except ValueError:
            raise bk.BackupError(_("The backup file is damaged (its contents list can't be read)."))
        if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
            raise bk.BackupError(wrong)
        if int(manifest.get("version", 0) or 0) > VERSION:
            raise bk.BackupError(_("This backup was made by a newer version of FinTrack. Update this server first."))
        listed = manifest.get("files") or {}
        inside = {n[len(PREFIX):] for n in names if n.startswith(PREFIX)} - {"manifest.json"}
        if not isinstance(listed, dict) or set(listed) != inside or not all(bk._safe_member(n) for n in names):
            raise bk.BackupError(_("The backup file is damaged or was changed: its files don't match its contents list."))
        for name, meta in listed.items():
            if not isinstance(meta, dict) or _sha256(z.read(PREFIX + name)) != meta.get("sha256"):
                raise bk.BackupError(_("The backup file is damaged or was changed after it was made (%(name)s doesn't match). Download a fresh copy.") % {"name": name})
        try:
            rows = json.loads(z.read(PREFIX + "data.json"))
        except ValueError:
            raise bk.BackupError(_("The backup file is damaged (its data can't be read)."))
    if not isinstance(rows, list):
        raise bk.BackupError(_("The backup file is damaged (its data can't be read)."))
    known = {m._meta.label_lower for m, _l in owned_models()}
    counted = defaultdict(int)
    for r in rows:
        if not isinstance(r, dict) or r.get("model") not in known or "pk" not in r or not isinstance(r.get("fields"), dict):
            raise bk.BackupError(_("The backup has data this version of FinTrack doesn't know (%(model)s).")
                                 % {"model": str(r.get("model") if isinstance(r, dict) else r)[:60]})
        counted[r["model"]] += 1
    if dict(counted) != {k: v for k, v in (manifest.get("counts") or {}).items() if v}:
        raise bk.BackupError(_("The backup file is damaged: the number of records doesn't match its contents list."))
    backup = SimpleNamespace(path=path, manifest=manifest, rows=rows, notes=[],
                             media=sorted(n[len("media/"):] for n in listed if n.startswith("media/")))
    bk._check_version(backup)
    return backup


# ── Restoring ───────────────────────────────────────────────────────────────

def _clear(user):
    """Delete every record the person owns (children first), and the recycle bin,
    whose copies point at the old ids."""
    for model, lookup in reversed(owned_models()):
        model._base_manager.filter(**{lookup: user}).delete()
    apps.get_model("trash", "DeletedItem").objects.filter(user=user).delete()


def _insert(model, objs):
    """Save new rows as they are — "created" and "updated" times kept, not set
    to now — many per query where the database can say which ids it gave."""
    meta = model._meta
    for o in objs:
        o.pk = None
    if meta.auto_field is None or not connection.features.can_return_rows_from_bulk_insert:
        for o in objs:
            o.save_base(raw=True)
        return
    fields = [f for f in meta.local_concrete_fields if f is not meta.auto_field and not getattr(f, "generated", False)]
    returning = meta.db_returning_fields
    size = max(1, connection.ops.bulk_batch_size(fields, objs) or len(objs))
    for i in range(0, len(objs), size):
        part = objs[i:i + size]
        for o, values in zip(part, model._base_manager._insert(part, fields=fields, returning_fields=returning, raw=True)):
            for f, value in zip(returning, values):
                setattr(o, f.attname, value)
            o._state.adding, o._state.db = False, connection.alias


def _media_target(model, field_name, old_name, user):
    """A fresh path for a restored photo, made by the field's own rule (so it
    sits in this person's folder), keeping the extension."""
    field = model._meta.get_field(field_name)
    holder = SimpleNamespace(user_id=user.pk, owner_id=user.pk, pk=None)
    try:
        return field.generate_filename(holder, os.path.basename(old_name))
    except Exception:
        return f"receipts/{user.pk}/{os.path.basename(old_name)}"


def restore(user, backup, keep_copy=True):
    """Replace this person's records with the backup's. Returns
    {"counts": {label: n}, "total": n, "copy": path or None}. Raises BackupError."""
    copy = save_copy(user) if keep_copy else None
    user_model = apps.get_model(settings.AUTH_USER_MODEL)
    by_model = defaultdict(list)
    for r in backup.rows:
        by_model[r["model"]].append(r)
    new_files, old_files = [], set()
    for model, lookup in owned_models():
        for name in bk._file_fields(model):
            old_files.update(v for v in _rows(model, lookup, user).values_list(name, flat=True) if v)
    try:
        with transaction.atomic():
            _clear(user)
            ids = defaultdict(dict)        # label -> {old pk: new pk}
            later = []                     # (model, new pk, field, old target) links to rows not made yet
            with zipfile.ZipFile(backup.path) as z:
                for model, _lookup in owned_models():
                    label = model._meta.label_lower
                    files = set(bk._file_fields(model))
                    batch = []                 # (old pk, fields, m2m, waiting)
                    for row in by_model.get(label, []):
                        fields = dict(row["fields"])
                        m2m, waiting = {}, []
                        for f in model._meta.get_fields():
                            if not getattr(f, "concrete", False) or not f.is_relation or f.name not in fields:
                                continue
                            value = fields[f.name]
                            target = f.related_model
                            if f.many_to_many:
                                m2m[f] = [ids[target._meta.label_lower].get(v) for v in (fields.pop(f.name) or [])]
                            elif target is user_model:
                                fields[f.name] = user.pk
                            elif value is None:
                                continue
                            elif value in ids[target._meta.label_lower]:
                                fields[f.name] = ids[target._meta.label_lower][value]
                            elif f.null and target._meta.label_lower in by_model:
                                fields[f.name] = None      # points at a row made later: linked at the end
                                waiting.append((f.attname, target._meta.label_lower, value))
                            elif f.null:
                                fields[f.name] = None      # outside this backup: never someone else's record
                            else:
                                raise bk.BackupError(_("The backup's records don't fit together (%(model)s). Nothing was changed.") % {"model": label})
                        for name in files:
                            old = fields.get(name)
                            if not old:
                                continue
                            if old in backup.media:
                                new = default_storage.save(_media_target(model, name, old, user),
                                                           ContentFile(z.read(PREFIX + "media/" + old)))
                                new_files.append(new)
                                fields[name] = new
                            else:
                                fields[name] = ""
                        batch.append((row["pk"], fields, m2m, waiting))
                    if not batch:
                        continue
                    objs = serializers.deserialize("json", json.dumps([{"model": label, "fields": b[1]} for b in batch]),
                                                   ignorenonexistent=True)
                    made = [o.object for o in objs]
                    _insert(model, made)
                    links = defaultdict(list)
                    for (old_pk, _fields, m2m, waiting), obj in zip(batch, made):
                        new_pk = obj.pk
                        ids[label][old_pk] = new_pk
                        for f, values in m2m.items():
                            links[f] += [(new_pk, v) for v in dict.fromkeys(values) if v]
                        later += [(model, new_pk, attname, tl, old) for attname, tl, old in waiting]
                    for f, pairs in links.items():
                        through = f.remote_field.through
                        src, dst = f.m2m_field_name() + "_id", f.m2m_reverse_field_name() + "_id"
                        through._base_manager.bulk_create([through(**{src: a, dst: b}) for a, b in pairs], batch_size=500)
            for model, pk, attname, tl, old in later:
                new = ids[tl].get(old)
                if new:
                    model._base_manager.filter(pk=pk).update(**{attname: new})
            counts = counts_for(user)
            expected = {k: v for k, v in backup.manifest.get("counts", {}).items() if v}
            if {k: v for k, v in counts.items() if v} != expected:
                raise bk.BackupError(_("The restore was stopped: the records loaded don't match the backup. Nothing was changed."))
            apps.get_model("accounts", "UserProfile").objects.get_or_create(user=user)
    except bk.BackupError:
        _forget_files(new_files)
        raise
    except (IntegrityError, DatabaseError, serializers.base.DeserializationError, ValueError, LookupError, TypeError) as exc:
        _forget_files(new_files)
        raise bk.BackupError(_("The restore was stopped because the backup's records don't fit together (%(error)s). Nothing was changed.") % {"error": str(exc)[:200]})
    _forget_files(old_files - set(new_files))   # the photos of the records replaced (they're in the copy)
    user.__dict__.pop("_work_settings", None)
    for name in list(user._state.fields_cache):   # profile, settings…: read the restored ones
        user._state.fields_cache.pop(name, None)
    return {"counts": counts, "total": sum(counts.values()), "copy": copy}


def _forget_files(names):
    for name in names:
        try:
            default_storage.delete(name)
        except Exception:
            pass


# ── For the page ────────────────────────────────────────────────────────────

AREAS = (
    ("money", gettext_lazy("Money")),
    ("work", gettext_lazy("Work tracker")),
    ("settings", gettext_lazy("Settings")),
)


def area_of(label):
    app = label.split(".")[0]
    if app == "productivity":
        return "work"
    if app in ("accounts", "core") or label.endswith("settings"):
        return "settings"
    return "money"


def summary(now, then=None):
    """Rows per area: each kind's count now, and in the backup when comparing."""
    from django.utils.text import capfirst

    names = {m._meta.label_lower: (capfirst(str(m._meta.verbose_name_plural)),
                                   str(apps.get_app_config(m._meta.app_label).verbose_name).split("·")[-1].strip())
             for m, _l in owned_models()}
    groups = defaultdict(list)
    for label, (name, app) in names.items():
        a, b = now.get(label, 0), (then or {}).get(label, 0)
        if a or b:
            groups[area_of(label)].append({"label": label, "name": name, "app": app, "now": a,
                                           "backup": b if then is not None else None})
    out = []
    for key, title in AREAS:
        rows = sorted(groups[key], key=lambda r: (r["app"].lower(), r["name"].lower()))
        out.append({"key": key, "title": str(title), "rows": rows, "now": sum(r["now"] for r in rows),
                    "backup": sum(r["backup"] or 0 for r in rows) if then is not None else None})
    return out
