"""After a restore that gives records new ids (My data, and the work
tracker's "add from a backup"), the places that name a record by its id
*inside* text or JSON are pointed at the new ids too — links between records
(foreign keys) are already handled by the restores themselves.

    links in text      a picture in a note or an answer is ![…](/work/images/12/),
                       a note can link /work/tasks/40/ … — the pages in LINKS
    ids kept in JSON   a mock exam's question list, a task template's project…
                       — a model says so with a `backup_ids(new_id)` method that
                       changes its own fields and returns their names

`new_id(label, old_pk)` gives the new id of a restored record, or None when it
wasn't in the backup. A link to a record that wasn't restored is left as it
is: pages only ever show their owner's records.

The whole-system backup keeps every id as it is, so it needs none of this.
"""
import re

from django.db import models
from django.urls import NoReverseMatch, reverse

# Pages whose address carries a record's id: (url name, the record's model).
# A feature whose records can be linked from text adds its page here.
LINKS = (
    ("work:note_image", "productivity.noteimage"),
    ("work:task", "productivity.task"),
    ("work:note", "productivity.note"),
    ("work:project", "productivity.project"),
    ("work:goal", "productivity.goal"),
    ("work:diagram", "productivity.diagram"),
    ("work:deck", "productivity.deck"),
    ("work:sprint", "productivity.sprint"),
    ("work:question", "productivity.question"),
    ("work:prep_topic", "productivity.preptopic"),
    ("work:exam_subject", "productivity.examsubject"),
)
MARK = 987654321


def _patterns():
    out = []
    for name, label in LINKS:
        try:
            url = reverse(name, args=[MARK])
        except NoReverseMatch:
            continue
        before, after = url.split(str(MARK))
        out.append((re.compile(re.escape(before) + r"(\d+)" + re.escape(after)), before, after, label))
    return out


def _text_fields(model):
    return [f for f in model._meta.concrete_fields if isinstance(f, (models.TextField, models.CharField)) and not f.choices
            and not f.is_relation and not isinstance(f, (models.EmailField, models.SlugField))]


def relink(objs, new_id):
    """Point ids inside the text and JSON of these just-restored records at the new ids; saves what changed."""
    patterns = _patterns()
    for obj in objs:
        changed = set()
        for f in _text_fields(type(obj)):
            value = getattr(obj, f.attname)
            if not value or "/" not in value:
                continue
            new = value
            for rx, before, after, label in patterns:
                new = rx.sub(lambda m, label=label, before=before, after=after: before + str(new_id(label, int(m.group(1))) or m.group(1)) + after, new)
            if new != value:
                setattr(obj, f.attname, new)
                changed.add(f.attname)
        hook = getattr(obj, "backup_ids", None)
        if hook is not None:
            changed.update(hook(new_id) or ())
        if changed:
            type(obj)._base_manager.filter(pk=obj.pk).update(**{name: getattr(obj, name) for name in changed})


def new_ids(json_ids, label, new_id, keep_unknown=False):
    """A list of old ids as new ids (ones not restored are dropped, or kept with keep_unknown)."""
    out = []
    for old in json_ids or []:
        try:
            new = new_id(label, int(old))
        except (TypeError, ValueError):
            new = None
        if new is not None:
            out.append(new)
        elif keep_unknown:
            out.append(old)
    return out
