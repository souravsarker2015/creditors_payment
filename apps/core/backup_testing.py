"""For tests: at least one record in every table the backups carry, made from
the models themselves — so a table added by a new feature is filled (and so
checked by the backup tests) without anyone remembering to add it here.

    fill_every_table(user, business)  → {label: count} of rows that exist

Each model gets one row with every required field filled by its type (the
first choice, a short text, 1, today…); links go to rows made earlier for the
same person or business. A model the generic rule can't make (a check in its
save(), a special constraint) gets a RECIPE below.
"""
import datetime
import uuid
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.db import models, transaction
from django.utils import timezone

from . import backup as bk

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
       b"\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa7V\xbd\xfa\x00\x00\x00\x00IEND\xaeB`\x82")

# Values a model needs beyond "something of the right type": {label: {field: value}}.
RECIPES = {
    "plans.installmentplan": {"debtor": None, "shop": None},      # a plan is for exactly one ledger (its creditor)
}


def _value(field):
    if field.choices:
        return field.choices[0][0] if not isinstance(field.choices[0][1], (list, tuple)) else field.choices[0][1][0][0]
    if isinstance(field, models.EmailField):
        return "someone@example.com"
    if isinstance(field, models.URLField):
        return "https://example.com/"
    if isinstance(field, models.SlugField):
        return "slug-" + uuid.uuid4().hex[:8]
    if isinstance(field, (models.CharField, models.TextField)):
        return ("Sample " + field.name)[: field.max_length or 200]
    if isinstance(field, models.BooleanField):
        return False
    if isinstance(field, models.DecimalField):
        return Decimal("1")
    if isinstance(field, (models.IntegerField, models.FloatField)):     # every integer kind
        return 1
    if isinstance(field, models.DateTimeField):
        return timezone.now()
    if isinstance(field, models.DateField):
        return timezone.localdate()
    if isinstance(field, models.TimeField):
        return datetime.time(9, 0)
    if isinstance(field, models.DurationField):
        return datetime.timedelta(minutes=5)
    if isinstance(field, models.UUIDField):
        return uuid.uuid4()
    if isinstance(field, models.JSONField):
        return {}
    if isinstance(field, models.BinaryField):
        return b"x"
    return None


def _ordered(model_list):
    """Models after the ones their required links point at."""
    out, seen = [], set()

    def visit(m, path=()):
        if m in seen or m in path:
            return
        for f in m._meta.concrete_fields:
            if f.is_relation and f.related_model in model_list and f.related_model is not m and not f.null:
                visit(f.related_model, path + (m,))
        seen.add(m)
        out.append(m)

    for m in sorted(model_list, key=lambda m: m._meta.label_lower):
        visit(m)
    return out


def fill_every_table(user, business=None):
    """Make sure every backed-up table has a row (for `user`, or `business`). Returns the problems: [(label, error)]."""
    User = get_user_model()
    made, problems = {}, []           # model → the row its dependants link to
    for model in _ordered(bk.backup_models()):
        label = model._meta.label_lower
        if model in (User,) or model._base_manager.exists() and _mine(model, user, business):
            made[model] = model._base_manager.filter(**_lookup(model, user, business)).first() or model._base_manager.first()
            continue
        kwargs, files, skip = dict(RECIPES.get(label, {})), {}, False
        for f in model._meta.concrete_fields:
            if f.primary_key or f.name in kwargs or getattr(f, "auto_now", False) or getattr(f, "auto_now_add", False):
                continue
            if f.is_relation:
                target = f.related_model
                if target is User:
                    kwargs[f.name] = user
                elif business is not None and target is type(business):
                    kwargs[f.name] = business
                elif target in made and made[target] is not None:
                    kwargs[f.name] = made[target]
                elif not f.null:
                    first = target._base_manager.first()
                    if first is None:
                        skip = True
                        break
                    kwargs[f.name] = first
                continue
            if isinstance(f, models.FileField):
                files[f.name] = f"sample-{model._meta.model_name}.png"
                continue
            if isinstance(f, (models.CharField, models.TextField)) and not f.choices and (f.blank or f.null) and not f.has_default():
                kwargs[f.name] = _value(f)           # optional text is filled too, so it's really carried
            elif not (f.has_default() or f.null):
                kwargs[f.name] = _value(f)           # otherwise the model's own default, or empty
        if skip:
            problems.append((label, "no row to link to"))
            continue
        obj = model(**kwargs)
        try:
            with transaction.atomic():
                for name, filename in files.items():
                    getattr(obj, name).save(filename, ContentFile(PNG), save=False)
                obj.save()
        except Exception as exc:          # noqa: BLE001 — reported, the test says which table
            try:
                with transaction.atomic():
                    obj.save_base(raw=True)
            except Exception:              # noqa: BLE001
                problems.append((label, f"{type(exc).__name__}: {exc}"[:300]))
                continue
        made[model] = obj
    return problems


def _lookup(model, user, business):
    for name in ("user", "owner"):
        try:
            f = model._meta.get_field(name)
        except Exception:     # noqa: BLE001
            continue
        if f.is_relation and f.related_model is get_user_model():
            return {name: user}
    if business is not None:
        try:
            f = model._meta.get_field("business")
            if f.is_relation:
                return {"business": business}
        except Exception:     # noqa: BLE001
            pass
    return {}


def _mine(model, user, business):
    look = _lookup(model, user, business)
    return model._base_manager.filter(**look).exists() if look else True



def fingerprint(scope, skip_fields=None):
    """Every row of the given tables as comparable values, for "does it come back exactly?":
    {label: Counter(row)}. A link is written as which row it points to — its place among the
    rows of that table in `scope` — so a restore that gives records new ids still compares
    equal, and a link that now points at the wrong record doesn't. Uploaded files compare by
    their content. `scope`: [(model, queryset)]; `skip_fields`: {label: (field names)}."""
    import hashlib
    from collections import Counter

    from django.core.files.storage import default_storage

    skip_fields = skip_fields or {}
    User = get_user_model()
    place = {m: {pk: i for i, pk in enumerate(qs.order_by("pk").values_list("pk", flat=True))} for m, qs in scope}

    def content(f):
        if not f:
            return ""
        try:
            with default_storage.open(f.name, "rb") as fh:
                return hashlib.sha256(fh.read()).hexdigest()[:16]
        except OSError:
            return "MISSING FILE"

    out = {}
    for m, qs in scope:
        skip = set(skip_fields.get(m._meta.label_lower, ()))
        rows = Counter()
        for o in qs.order_by("pk"):
            row = []
            for f in m._meta.concrete_fields:
                if f.primary_key or f.name in skip:
                    continue
                if f.is_relation:
                    v, target = getattr(o, f.attname), f.related_model
                    if v is None:
                        row.append((f.name, None))
                    elif target is User and f.name in ("user", "owner"):
                        row.append((f.name, "the owner"))
                    elif target in place:
                        row.append((f.name, target._meta.label_lower, place[target].get(v, "outside")))
                    else:
                        row.append((f.name, "elsewhere", str(getattr(o, f.name))))
                elif isinstance(f, models.FileField):
                    row.append((f.name, content(getattr(o, f.name))))
                else:
                    row.append((f.name, getattr(o, f.attname)))
            for f in m._meta.many_to_many:
                ids = getattr(o, f.name).values_list("pk", flat=True)
                target = f.related_model
                row.append((f.name, tuple(sorted(place[target].get(i, "outside") for i in ids)) if target in place else tuple(sorted(map(str, ids)))))
            rows[repr(row)] += 1
        out[m._meta.label_lower] = rows
    return out


def differences(before, after):
    """What a restore changed, readably (empty: nothing)."""
    out = []
    for label in sorted(set(before) | set(after)):
        a, b = before.get(label), after.get(label)
        if a != b:
            gone, came = (a or {}) - (b or {}), (b or {}) - (a or {})
            out.append(f"{label}: {sum((a or {}).values())} rows before, {sum((b or {}).values())} after — "
                       f"{next(iter(gone), '')[:300]} ⇢ {next(iter(came), '')[:300]}")
    return out
