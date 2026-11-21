"""A note's edit history: copies kept while you write, how long they're kept, and what changed between two of them.

    How long      each note keeps its copies 2, 4, 6 or 12 months (or any number, 1–120) — its own choice, or the
                  default in Work settings (2 months). History can be turned off for one note; its copies then run out
                  as usual, and only a copy of text written in two places at once is still kept (nothing is lost).
    How many      every copy of the last week; then the last copy of each day up to a month; then the last of each
                  week. A pinned copy ("Keep for good") never runs out or thins out.
    What changed  line by line, and word by word inside a changed line (diff()); a short summary — words added and
                  taken out, the headings it changed under — is worked out once per copy and kept with it.
"""
import calendar
import re
from datetime import timedelta
from difflib import SequenceMatcher

from django.core.cache import cache
from django.db.models import Sum
from django.db.models.functions import Length
from django.utils import timezone

ALL_DAYS = 7          # every copy of the last week
DAILY_DAYS = 30       # then one a day; older, one a week
MONTH_CHOICES = (2, 4, 6, 12)
MOST_SECTIONS = 6
HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
FENCE = re.compile(r"^\s{0,3}(```|~~~)")
LINES = re.compile(r"\r?\n")


# ── Settings ──────────────────────────────────────────────────────────────
def _ws(note):
    from .models import WorkSettings

    return WorkSettings.for_user(note.owner)


def months(note, ws=None):
    """How many months this note keeps its copies."""
    return note.history_months or (ws or _ws(note)).note_history_months


def months_ago(when, n):
    """The same moment `n` calendar months earlier (31 May − 3 months = 28/29 Feb)."""
    y, m = divmod(when.month - 1 - n, 12)
    year, month = when.year + y, m + 1
    return when.replace(year=year, month=month, day=min(when.day, calendar.monthrange(year, month)[1]))


def cutoff(note, now=None, ws=None):
    """Copies older than this run out (unless pinned)."""
    return months_ago(now or timezone.now(), months(note, ws))


# ── Keeping a copy ────────────────────────────────────────────────────────
def remember(note, force=False, reason=""):
    """Keep the note as it is now, before a new round of edits — at most every few minutes, unless `force`.
    Returns the copy, or None (nothing written yet, history off, too soon, or nothing changed)."""
    from .models import NoteVersion

    if not note.pk or not (note.title.strip() or note.body.strip()):
        return None
    if note.history_off and reason != NoteVersion.Reason.CONFLICT:
        return None
    ws = _ws(note)
    last = note.versions.only("created_at", "body", "title", "pinned", "label").first()
    now = timezone.now()
    if last and not force and now - last.created_at < timedelta(minutes=ws.note_history_minutes):
        return None
    if last and last.body == note.body and last.title == note.title:
        return None
    v = NoteVersion(note=note, title=note.title, body=note.body, created_at=now, reason=reason)
    if last:                                   # what changed since the last copy: worked out now, once
        v.added, v.removed, v.sections = summary(note.versions.only("title", "body").get(pk=last.pk), v)
    v.save()
    prune(note, now, ws)
    return v


def save_now(note, label=""):
    """"Keep this version": the note as it is now, kept for good under a name (even when it's the same as the last copy)."""
    from .models import NoteVersion

    label = label.strip()[:80]
    last = note.versions.first()
    if last and last.body == note.body and last.title == note.title:
        last.pinned, last.label = True, label or last.label
        last.save(update_fields=["pinned", "label"])
        return last
    return NoteVersion.objects.create(note=note, title=note.title, body=note.body, reason=NoteVersion.Reason.SAVED, pinned=True, label=label)


def prune(note, now=None, ws=None):
    """Delete the copies that ran out, and thin out the old ones. Returns how many went."""
    now = now or timezone.now()
    rows = list(note.versions.order_by("created_at", "pk").values_list("pk", "created_at", "pinned"))
    if not rows:
        return 0
    end = cutoff(note, now, ws)
    tz = timezone.get_current_timezone()
    gone, seen = set(), set()
    for pk, at, pinned in reversed(rows):                    # newest first: the last copy of a day / week is the one kept
        if pinned:
            continue
        if at < end:
            gone.add(pk)
            continue
        age = now - at
        if age <= timedelta(days=ALL_DAYS):
            continue
        local = timezone.localtime(at, tz)
        bucket = ("d", local.date()) if age <= timedelta(days=DAILY_DAYS) else ("w",) + tuple(local.isocalendar()[:2])
        if bucket in seen:
            gone.add(pk)
        seen.add(bucket)
    if not gone:
        return 0
    order = [pk for pk, _at, _p in rows]
    before = {pk: (order[i - 1] if i else None) for i, pk in enumerate(order)}
    left = [pk for pk in order if pk not in gone]
    after = {pk: (left[i - 1] if i else None) for i, pk in enumerate(left)}
    stale = [pk for pk in left if before[pk] != after[pk]]   # the copy before it went: what changed since then is worked out again
    note.versions.filter(pk__in=gone).delete()
    if stale:
        note.versions.filter(pk__in=stale).update(added=None, removed=None, sections={})
    return len(gone)


def sweep(user, force=False):
    """Once a day per person: delete the copies that ran out on every note (a note not written in for months too)."""
    from .models import Note, NoteVersion, WorkSettings

    key = f"note-history-sweep:{user.pk}:{timezone.localdate()}"
    if not force and cache.get(key):
        return 0
    cache.set(key, 1, 60 * 60 * 26)
    now, default = timezone.now(), WorkSettings.for_user(user).note_history_months
    gone = 0
    for m in set(Note.objects.filter(owner=user).values_list("history_months", flat=True)):
        own = Note.objects.filter(owner=user, history_months=m) if m else Note.objects.filter(owner=user, history_months__isnull=True)
        gone += NoteVersion.objects.filter(note__in=own, pinned=False, created_at__lt=months_ago(now, m or default)).delete()[0]
    return gone


def size(note):
    """(copies, bytes, oldest) of a note's history."""
    agg = note.versions.aggregate(b=Sum(Length("body")), t=Sum(Length("title")))
    oldest = note.versions.order_by("created_at").values_list("created_at", flat=True).first()
    return note.versions.count(), (agg["b"] or 0) + (agg["t"] or 0), oldest


# ── What changed ──────────────────────────────────────────────────────────
def _headings(lines):
    """For each line, the heading it's under ("" before the first one), code blocks skipped."""
    out, current, fenced = [], "", False
    for line in lines:
        if FENCE.match(line):
            fenced = not fenced
        elif not fenced:
            m = HEADING.match(line)
            if m:
                current = m.group(2).strip()
        out.append(current)
    return out


PUNCT = ".,;:!?()\\[\\]{}\"'“”‘’।|*_`~<>/\\-#+=%&@^$"
TOKEN = re.compile(rf"\s+|[{PUNCT}]+|[^\s{PUNCT}]+")


def _words(text):
    """Words, spaces and punctuation apart ("python." is "python" and "."); a Bangla word stays whole with its vowel signs."""
    return TOKEN.findall(text)


def _is_word(token):
    return bool(token.strip()) and not re.fullmatch(rf"[{PUNCT}]+", token)


def count_words(text):
    return sum(1 for t in _words(text) if _is_word(t))


def _inline(old, new):
    """Word-by-word changes inside one changed line: [[op, text]] with op "=", "-" or "+"; and the words taken out / added."""
    a, b = _words(old), _words(new)
    parts, minus, plus = [], 0, 0
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            parts.append(["=", "".join(a[i1:i2])])
            continue
        if i2 > i1:
            parts.append(["-", "".join(a[i1:i2])])
            minus += sum(1 for w in a[i1:i2] if _is_word(w))
        if j2 > j1:
            parts.append(["+", "".join(b[j1:j2])])
            plus += sum(1 for w in b[j1:j2] if _is_word(w))
    return parts, minus, plus


def _alike(old, new):
    if not old.strip() or not new.strip():
        return False
    a, b = [t for t in _words(old) if t.strip()], [t for t in _words(new) if t.strip()]
    return SequenceMatcher(None, a, b, autojunk=False).ratio() >= 0.4


def diff(old_title, old_body, new_title, new_body, context=2, rows=True, side="j"):
    """What changed from one text to another.

    {"title": [old, new] or None, "added": words, "removed": words, "sections": [headings, in order],
     "rows": [{"op": "same"|"add"|"del"|"mod"|"fold", "text" | "parts" | "lines", "at": heading}]}
    — unchanged stretches longer than a few lines fold into one {"op": "fold", "count", "lines" or "start"} row:
    "start" is the line it begins at in the newer text (side "j") or the older one (side "i")."""
    a, b = LINES.split(old_body), LINES.split(new_body)          # (the same lines as the page splits the text into)
    ha, hb = _headings(a), _headings(b)
    out, added, removed, sections = [], 0, 0, []

    def mark(heading):
        if heading not in sections:
            sections.append(heading)

    for tag, i1, i2, j1, j2 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            out += [{"op": "same", "text": b[j], "at": hb[j], "i": i1 + k, "j": j} for k, j in enumerate(range(j1, j2))]
            continue
        olds, news = a[i1:i2], b[j1:j2]
        k = 0
        while k < max(len(olds), len(news)):
            o = olds[k] if k < len(olds) else None
            n = news[k] if k < len(news) else None
            if o is not None and n is not None and _alike(o, n) and len(o) + len(n) < 20000:
                parts, minus, plus = _inline(o, n)
                out.append({"op": "mod", "parts": parts, "at": hb[j1 + k]})
                removed, added = removed + minus, added + plus
                mark(hb[j1 + k])
            else:
                if o is not None:
                    out.append({"op": "del", "text": o, "at": ha[i1 + k]})
                    removed += count_words(o)
                    mark(ha[i1 + k])
                if n is not None:
                    out.append({"op": "add", "text": n, "at": hb[j1 + k]})
                    added += count_words(n)
                    mark(hb[j1 + k])
            k += 1
    result = {"title": [old_title, new_title] if old_title != new_title else None, "added": added, "removed": removed,
              "sections": sections}
    if rows:
        result["rows"] = _fold(out, context, side)
    return result


FOLD_SENT = 60        # an unchanged stretch longer than this is sent as where it is, not its lines (fetched when opened)


def _fold(rows, context, side="j"):
    """Unchanged lines far from any change fold into one row (opened on a tap). A long one says only where it is in
    the copy's text (`side`: "j" — the newer text, "i" — the older), so a long note's answer stays small."""
    changed = [i for i, r in enumerate(rows) if r["op"] != "same"]
    near = set()
    for i in changed:
        near.update(range(max(0, i - context), min(len(rows), i + context + 1)))
    out, run = [], []

    def close():
        if not run:
            return
        if len(run) > FOLD_SENT:
            out.append({"op": "fold", "count": len(run), "start": run[0][side], "at": ""})
        else:
            out.append({"op": "fold", "lines": [r["text"] for r in run], "count": len(run), "at": ""})
        run.clear()

    for i, r in enumerate(rows):
        if r["op"] == "same" and i not in near:
            run.append(r)
            continue
        close()
        out.append({k: v for k, v in r.items() if k not in ("i", "j")})
    close()
    return out


def summary(old, new):
    """(added, removed, {"title": changed?, "under": [headings], "more": how many more headings}) from an older copy (or None) to a newer one."""
    if old is None:
        return 0, 0, {"title": False, "under": []}
    d = diff(old.title, old.body, new.title, new.body, rows=False)
    return d["added"], d["removed"], {"title": bool(d["title"]), "under": d["sections"][:MOST_SECTIONS], "more": max(0, len(d["sections"]) - MOST_SECTIONS)}


def fill_summaries(note, budget=25, seconds=1.0):
    """Work out (and keep) what changed in the copies that don't say yet — newest first, at most `budget` of them or
    about `seconds` (a long note's copies take a moment each); the rest follow the next time the history is opened."""
    import time

    order = list(note.versions.order_by("created_at", "pk").values_list("pk", "added"))
    todo = [i for i, (_pk, added) in enumerate(order) if added is None and i > 0][::-1][:budget]
    start = time.monotonic()
    for n, i in enumerate(todo):
        if n and time.monotonic() - start > seconds:
            return n                      # only the two texts needed, not every copy's (a long note's copies are large)
        pair = {v.pk: v for v in note.versions.filter(pk__in=[order[i - 1][0], order[i][0]]).only("pk", "title", "body")}
        older, v = pair[order[i - 1][0]], pair[order[i][0]]
        v.added, v.removed, v.sections = summary(older, v)
        v.save(update_fields=["added", "removed", "sections"])
    return len(todo)
