from datetime import timedelta

from django.apps import apps
from django.core import serializers
from django.db import IntegrityError, connections, router, transaction
from django.db.models import QuerySet
from django.db.models.deletion import Collector
from django.utils import timezone

from .models import DeletedItem

KEEP_DAYS = 30


class CannotRestore(Exception):
    pass


FILE_FIELDS = ("receipt",)


def drop_files(items):
    """Remove the photos kept only for these deleted items (deleting for good means the receipt too)."""
    import json

    from django.core.files.storage import default_storage

    for item in items:
        for row in json.loads(item.data or "[]"):
            for name in FILE_FIELDS:
                path = (row.get("fields") or {}).get(name)
                if path and default_storage.exists(path):
                    default_storage.delete(path)


def forget(items):
    items = list(items)
    drop_files(items)
    DeletedItem.objects.filter(pk__in=[i.pk for i in items]).delete()


def purge_old(user=None):
    old = DeletedItem.objects.filter(deleted_at__lt=timezone.now() - timedelta(days=KEEP_DAYS))
    if user is not None:
        old = old.filter(user=user)
    forget(old)


def _instances(collector):
    """Everything the delete will remove, the rows others depend on first."""
    collector.sort()                       # deletion order: dependants first
    out = []
    for _model, objs in reversed(list(collector.data.items())):
        out.extend(objs)
    for qs in collector.fast_deletes:      # leaf rows removed in bulk
        out.extend(qs)
    return out


def _relinks(collector):
    """Rows that will be set to empty (SET_NULL) because they pointed at a deleted one."""
    out = []
    for (field, value), groups in collector.field_updates.items():
        if value is not None:
            continue
        pks = []
        for g in groups:
            pks.extend(g.values_list("pk", flat=True) if isinstance(g, QuerySet) else [o.pk for o in g])
        model = field.model
        pairs = [[pk, v] for pk, v in model._base_manager.filter(pk__in=pks).values_list("pk", field.attname)]
        if pairs:
            out.append([model._meta.label_lower, field.attname, pairs])
    return out


def trash(user, obj, label, back_url=""):
    """Delete `obj` (and what cascades with it), keeping a copy to restore."""
    with transaction.atomic():
        collector = Collector(using=router.db_for_write(type(obj), instance=obj))
        collector.collect([obj])
        rows = _instances(collector)
        item = DeletedItem.objects.create(
            user=user, label=label[:200], kind=str(type(obj)._meta.verbose_name).capitalize()[:80],
            data=serializers.serialize("json", rows), relinks=_relinks(collector), count=len(rows), back_url=back_url[:300])
        obj.delete()
    purge_old(user)
    return item


def restore(item):
    """Put everything back with its old ids. Raises CannotRestore if that's no longer possible."""
    db = router.db_for_write(DeletedItem)
    try:
        with transaction.atomic(using=db):
            tables, restored = set(), []
            for d in serializers.deserialize("json", item.data):
                model = type(d.object)
                if model._base_manager.filter(pk=d.object.pk).exists():
                    raise CannotRestore("already there")
                d.save()
                restored.append(d.object)
                tables.add(model._meta.db_table)
            # Something it belonged to may be gone for good (e.g. a deleted category).
            connections[db].check_constraints(table_names=sorted(tables))
            for label, attname, pairs in item.relinks:
                model = apps.get_model(label)
                for pk, value in pairs:
                    model._base_manager.filter(pk=pk, **{f"{attname}__isnull": True}).update(**{attname: value})
            for obj in restored:          # e.g. a goal entry re-checks whether its goal is reached
                hook = getattr(obj, "after_restore", None)
                if callable(hook):
                    hook()
            item.delete()
    except (IntegrityError, serializers.base.DeserializationError) as exc:
        raise CannotRestore(str(exc)) from exc
