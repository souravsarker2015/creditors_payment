"""What a note pulls in from elsewhere, drawn live where it's read (static/js/work.js):

- a ```tasks block: the tasks a filter finds, ticked off right there — Notion's
  linked database, Obsidian's Tasks plugin. One filter a line ("project: Payments
  API") or several on one ("due:week #api !high"); other words are searched for;
- ![[Another note]] or ![[Another note#A heading]]: that note, or that one
  section of it, shown inside this one (and kept up to date with it);
- unlinked mentions: other notes that name this one in plain text, without a
  [[link]] — turned into links in one click, as in Obsidian."""
import re
from urllib.parse import urlencode

from django.db.models import F
from django.urls import reverse
from django.utils.formats import date_format
from django.utils.translation import gettext as _

from . import services
from .models import Goal, Note, Priority, Project, Sprint, Status, Task, TaskKind

# ── ```tasks blocks ───────────────────────────────────────────────────────
KEYS = ("project", "tag", "priority", "due", "status", "kind", "sprint", "goal", "blocked", "done", "search", "sort", "limit")
PRIORITY_WORDS = {"urgent": Priority.URGENT, "high": Priority.HIGH, "medium": Priority.MEDIUM, "low": Priority.LOW}
DUE = ("today", "week", "overdue", "none")
SORTS = ("due", "priority", "updated", "created")
YES, NO = ("yes", "true", "1", "on"), ("no", "false", "0", "off")
LIMIT, MAX_LIMIT = 20, 50
WHOLE_LINE = re.compile(r"^([A-Za-z]+)\s*:\s+(.+)$")          # "project: Payments API" — the rest of the line
TOKEN = re.compile(r"([A-Za-z]+):(\S+)|#(\S+)|@(\S+)|!(\w+)|(\S+)")


def parse_query(text):
    """A ```tasks block's text → ({key: value}, [words to search for], [mistakes])."""
    found, words, errors = {}, [], []

    def put(key, value):
        key = key.lower()
        if key not in KEYS:
            errors.append(_("“%(key)s” isn't a filter. These are: %(keys)s.") % {"key": key, "keys": ", ".join(KEYS)})
        else:
            found[key] = value.strip()

    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        whole = WHOLE_LINE.match(line)
        if whole:
            put(whole.group(1), whole.group(2))
            continue
        for m in TOKEN.finditer(line):
            key, value, tag, project, priority, word = m.groups()
            if key:
                put(key, value)
            elif tag:
                put("tag", tag)
            elif project:
                put("project", project)
            elif priority:
                put("priority", priority)
            else:
                words.append(word)
    return found, words, errors


def _choice(value, choices):
    """A value given as its code ("doing") or its name ("In progress"), any case."""
    v = value.strip().lower()
    return next((code for code, label in choices if v in (str(code).lower(), str(label).lower())), None)


def run_query(user, text, today):
    """The tasks a ```tasks block asks for: {"items", "total", "more", "chips", "errors", "link"}."""
    found, words, errors = parse_query(text)
    f = dict.fromkeys(services.TASK_FILTERS, "")
    chips = []
    search = " ".join(filter(None, [found.get("search", "")] + words))
    if search:
        f["q"] = search
        chips.append(f"“{search}”")
    if "project" in found:
        v = found["project"]
        if v.lower() in ("none", "no"):
            f["project"] = "none"
            chips.append(_("No project"))
        else:
            mine = Project.objects.filter(owner=user)
            p = mine.filter(name__iexact=v).first() or mine.filter(name__iexact=v.replace("-", " ")).first() or mine.filter(name__icontains=v).first()
            if p:
                f["project"] = str(p.pk)
                chips.append(p.name)
            else:
                errors.append(_("No project called “%(name)s”.") % {"name": v})
    if "tag" in found:
        f["tag"] = found["tag"].lstrip("#").lower()
        chips.append("#" + f["tag"])
    if "priority" in found:
        v = found["priority"].lower()
        n = PRIORITY_WORDS.get(v, int(v) if v.isdigit() and int(v) <= Priority.URGENT else None)
        if n is None:
            n = _choice(v, Priority.choices)
        if n is None:
            errors.append(_("Priority is one of: urgent, high, medium, low."))
        else:
            f["priority"] = str(int(n))
            chips.append(_("%(priority)s or more") % {"priority": Priority(int(n)).label})
    if "due" in found:
        v = found["due"].lower().replace("this ", "")
        if v in DUE:
            f["due"] = v
            chips.append({"today": _("Due today"), "week": _("Due this week"), "overdue": _("Overdue"), "none": _("No due date")}[v])
        else:
            errors.append(_("Due is one of: today, week, overdue, none."))
    only_done = False
    if "status" in found:
        v = _choice(found["status"], Status.choices)
        if v is None:
            errors.append(_("Status is one of: %(names)s.") % {"names": ", ".join(Status.values)})
        else:
            f["status"], only_done = v, v == Status.DONE
            chips.append(Status(v).label)
    if "kind" in found:
        v = _choice(found["kind"], TaskKind.choices)
        if v is None:
            errors.append(_("Kind is one of: %(names)s.") % {"names": ", ".join(TaskKind.values)})
        else:
            f["kind"] = v
            chips.append(TaskKind(v).label)
    if "sprint" in found:
        v = found["sprint"]
        if v.lower() in ("current", "now", "this"):
            f["sprint"] = "current"
            chips.append(_("This sprint"))
        elif v.lower() in ("none", "no"):
            f["sprint"] = "none"
            chips.append(_("No sprint"))
        else:
            s = Sprint.objects.filter(owner=user, name__iexact=v).first() or Sprint.objects.filter(owner=user, name__icontains=v).first()
            if s:
                f["sprint"] = str(s.pk)
                chips.append(s.name)
            else:
                errors.append(_("No sprint called “%(name)s”.") % {"name": v})
    if "goal" in found:
        g = Goal.objects.filter(owner=user, title__icontains=found["goal"]).order_by("status", "-pk").first()
        if g:
            f["goal"] = str(g.pk)
            chips.append(g.title)
        else:
            errors.append(_("No goal called “%(name)s”.") % {"name": found["goal"]})
    if "blocked" in found:
        v = found["blocked"].lower()
        f["blocked"] = "yes" if v in YES else "no" if v in NO else ""
        if f["blocked"]:
            chips.append(_("Blocked") if f["blocked"] == "yes" else _("Not blocked"))
    with_done = only_done or found.get("done", "").lower() in YES
    if found.get("done", "").lower() in YES and not only_done:
        chips.append(_("With done ones"))
    try:
        limit = max(1, min(MAX_LIMIT, int(found.get("limit") or LIMIT)))
    except ValueError:
        limit = LIMIT
        errors.append(_("Limit is a number, up to %(max)s.") % {"max": MAX_LIMIT})

    qs = services.filter_tasks(user, Task.objects.filter(owner=user).select_related("project"), f, today)
    if only_done:
        qs = qs.filter(status=Status.DONE)
    elif not with_done:
        qs = qs.exclude(status=Status.DONE)
    sort = found.get("sort", "").lower()
    if sort not in SORTS:
        sort = "done" if only_done else "due"
    qs = qs.order_by(*{
        "due": (F("due_date").asc(nulls_last=True), "-priority", "order"),
        "priority": ("-priority", F("due_date").asc(nulls_last=True), "order"),
        "updated": ("-updated_at",), "created": ("-created_at",), "done": (F("completed_at").desc(nulls_last=True),),
    }[sort])
    total = qs.count()
    params = {k: v for k, v in f.items() if v}
    if with_done:
        params["done"] = "1"
    return {
        "items": [_item(t, today) for t in qs[:limit]], "total": total, "more": max(0, total - limit),
        "chips": chips, "errors": errors, "link": reverse("work:tasks") + ("?" + urlencode(params) if params else ""),
    }


def _item(t, today):
    return {
        "id": t.pk, "title": t.title, "url": reverse("work:task", args=[t.pk]), "done": t.is_done,
        "status": t.status, "statusLabel": t.get_status_display(), "priority": t.priority, "kind": t.kind,
        "due": date_format(t.due_date, "j M") if t.due_date else "", "late": t.is_overdue(today),
        "project": t.project.name if t.project else "", "color": t.project.color if t.project else "",
    }


# ── ![[Embeds]] ───────────────────────────────────────────────────────────
HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t#]*$")


def _plain_heading(text):
    return re.sub(r"[*_`=]", "", text).strip().lower()


def section(body, heading):
    """One heading of a note and what's under it (up to the next heading as big or bigger), or None."""
    lines, code, start, level = body.split("\n"), False, None, 0
    want = _plain_heading(heading)
    for i, line in enumerate(lines):
        if services.FENCE.match(line):
            code = not code
            continue
        m = not code and HEADING.match(line)
        if not m:
            continue
        if start is None:
            if _plain_heading(m.group(2)) == want:
                start, level = i, len(m.group(1))
        elif len(m.group(1)) <= level:
            return "\n".join(lines[start:i]).strip("\n")
    return None if start is None else "\n".join(lines[start:]).strip("\n")


def _note_titled(user, title):
    return Note.objects.filter(owner=user, title__iexact=title.strip()).order_by("is_archived", "-updated_at").first() if title.strip() else None


def embed(user, ref, current=None):
    """![[ref]] → ({"id", "title", "heading", "url", "body"}, None), or (None, why not)."""
    ref = (ref or "").strip()[:300]
    note, heading = _note_titled(user, ref), ""
    if note is None and "#" in ref:              # (a title may have a # in it: "C# notes")
        title, heading = ref.rsplit("#", 1)
        note = _note_titled(user, title)
    if note is None:
        return None, _("No note called “%(title)s” yet.") % {"title": ref.split("#")[0].strip()}
    if current and note.pk == current:
        return None, _("A note can't be shown inside itself.")
    body = note.body
    if heading.strip():
        body = section(note.body, heading)
        if body is None:
            return None, _("“%(title)s” has no heading “%(heading)s”.") % {"title": note.display_title, "heading": heading.strip()}
    return {"id": note.pk, "title": note.display_title, "heading": heading.strip(), "url": reverse("work:note", args=[note.pk]), "body": body}, None


# ── Unlinked mentions ─────────────────────────────────────────────────────
MIN_TITLE = 3
CODE = re.compile(r"(```[\s\S]*?(?:```|$)|~~~[\s\S]*?(?:~~~|$)|`[^`\n]+`)")
# What's left alone: code, links (and [[links]]), HTML tags and web addresses
PROTECTED = re.compile(r"(```[\s\S]*?(?:```|$)|~~~[\s\S]*?(?:~~~|$)|`[^`\n]+`|!?\[\[[^\]\n]*\]\]|!?\[[^\]\n]*\]\([^)\n]*\)|<[^>\n]+>|https?://\S+)")
WORD = r"\wऀ-෿"                     # (Bangla's vowel signs aren't \w)


def _mention(title):
    return re.compile(rf"(?<![{WORD}])" + re.escape(title) + rf"(?![{WORD}])", re.I)


def _can_mention(note):
    title = note.title.strip()
    return len(title) >= MIN_TITLE and "[" not in title and "]" not in title


def unlinked_mentions(note, limit=20):
    """Other notes that name this one in plain text: [{"note", "count", "before", "match", "after"}]."""
    if not _can_mention(note):
        return []
    title, out = note.title.strip(), []
    rx = _mention(title)
    others = (Note.objects.filter(owner=note.owner, is_archived=False, is_template=False, body__icontains=title).exclude(pk=note.pk)
              .order_by("-updated_at").only("pk", "title", "body", "updated_at")[:200])
    for other in others:
        parts, count, first = PROTECTED.split(other.body), 0, None
        for i in range(0, len(parts), 2):
            for m in rx.finditer(parts[i]):
                count += 1
                if first is None:
                    first = (parts[i], m)
        if not count:
            continue
        text, m = first
        before = " ".join(text[max(0, m.start() - 60):m.start()].split())
        after = " ".join(text[m.end():m.end() + 60].split())
        out.append({"note": other, "count": count, "match": m.group(0),
                    "before": ("…" if m.start() > 60 else "") + before + (" " if text[m.start() - 1:m.start()].isspace() else ""),
                    "after": (" " if text[m.end():m.end() + 1].isspace() else "") + after + ("…" if len(text) - m.end() > 60 else "")})
        if len(out) >= limit:
            break
    return out


def link_mentions(body, title):
    """Each plain mention of `title` → [[as it was written]]. Returns (body, how many)."""
    rx, n = _mention(title.strip()), 0
    parts = PROTECTED.split(body)
    for i in range(0, len(parts), 2):
        parts[i], k = rx.subn(lambda m: f"[[{m.group(0)}]]", parts[i])
        n += k
    return "".join(parts), n


def relink(note, old):
    """After a rename: [[Old]], [[Old#Heading]], [[Old|other words]] and ![[Old]] in the person's other notes follow
    the new title (as Obsidian does) → how many notes changed. Left alone when another note goes by the old title."""
    old, new = old.strip(), note.title.strip()
    if not old or not new or old.lower() == new.lower() or Note.objects.filter(owner=note.owner, title__iexact=old).exclude(pk=note.pk).exists():
        return 0
    link = re.compile(r"(\[\[)" + re.escape(old) + r"(\s*(?:[#|][^\]\n]*)?\]\])", re.I)
    changed = 0
    for other in Note.objects.filter(owner=note.owner, body__icontains=f"[[{old}").exclude(pk=note.pk):
        parts = CODE.split(other.body)
        parts[::2] = [link.sub(lambda m: m.group(1) + new + m.group(2), part) for part in parts[::2]]
        body = "".join(parts)
        if body != other.body:
            services.remember_note(other, force=True)
            other.body = body
            other.save(update_fields=["body", "updated_at"])
            changed += 1
    return changed


def link_from(note, source=None):
    """Link this note wherever it's mentioned (or only in `source`). Returns how many notes changed."""
    if not _can_mention(note):
        return 0
    changed = 0
    for m in unlinked_mentions(note, limit=200):
        if source is not None and m["note"].pk != source:
            continue
        other = Note.objects.get(pk=m["note"].pk)
        body, n = link_mentions(other.body, note.title)
        if n:
            services.remember_note(other, force=True)          # in its History, to take it back
            other.body = body
            other.save(update_fields=["body", "updated_at"])
            changed += 1
    return changed


def links_context(note):
    """The links at the foot of a note: the notes that link here, and those that only name it."""
    return {"note": note, "backlinks": services.backlinks(note), "mentions": unlinked_mentions(note)}
