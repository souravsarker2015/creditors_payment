"""The Reader: notes and exam notes read as a book, a chapter at a time — as Kindle, Apple Books and Medium do it,
for people who'd rather not read much:

- a note category is a book, its notes the chapters (in an order of your own); an exam subject is a book too, its
  chapters the questions' chapters (each question a heading, its answer below);
- each chapter says how long it takes ("≈ 4 min"), how far you are, and is ticked off when you reach its end;
- where you stopped is kept, to the line, and "Continue reading" (Notes, Exam notes, Today) takes you back there;
- minutes read a day count towards a small goal (10 minutes) with the days in a row you reached it;
- one line to remember can be written at a chapter's end (recalling it is what makes it stay).
"""
import re
from datetime import timedelta

from django.db.models import F, Sum
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.translation import gettext as _

from . import exam
from .models import ExamNote, Note, NoteCategory, ReadingDay, ReadingProgress, WorkSettings

WPM = 200                 # words a minute, read with care (Medium counts 265 for skimming)
MAX_STEP = 120            # seconds one report may add (a tab left open doesn't count for hours)


def words(text):
    """Words in Markdown: code, links' addresses and marks don't count."""
    text = re.sub(r"```.*?(```|$)", " ", text or "", flags=re.S)
    text = re.sub(r"\]\([^)]*\)|[#*_>`=|\-]+|\{[a-z]+\}", " ", text)
    return len(text.split())


def minutes(n_words):
    return max(1, round(n_words / WPM))


HEAD = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
FENCE = re.compile(r"^\s{0,3}(```|~~~)")


def plain_heading(text):
    """A heading's words, without its marks: **bold**, `code`, [links](…), ==highlights==."""
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    return re.sub(r"[*_`=~]+|\{[a-z]+\}", "", text).strip()


def sections(md):
    """A chapter's sections: its headings of the top level used (a lone title heading on the first line aside),
    each with how long it takes. [{title, level, n (which heading of that level it is), words, minutes}]."""
    heads, fenced, lines = [], False, (md or "").split("\n")
    for i, line in enumerate(lines):
        if FENCE.match(line):
            fenced = not fenced
            continue
        m = None if fenced else HEAD.match(line)
        if m:
            heads.append((i, len(m.group(1)), plain_heading(m.group(2))))
    if not heads:
        return []
    levels = sorted({lv for _i, lv, _t in heads})
    top = levels[0]
    tops = [h for h in heads if h[1] == top]
    first_text = next((i for i, line in enumerate(lines) if line.strip()), 0)
    if len(tops) == 1 and tops[0][0] == first_text and len(levels) > 1:       # "# Title" and then its parts
        top = levels[1]
    out, seen = [], {}
    marks = [h for h in heads if h[1] == top]
    for k, (i, lv, title) in enumerate(heads):
        seen[lv] = seen.get(lv, -1) + 1
        if lv != top:
            continue
        nxt = next((h[0] for h in marks if h[0] > i), len(lines))
        n = words("\n".join(lines[i:nxt]))
        out.append({"title": title or "…", "level": lv, "n": seen[lv], "words": n, "minutes": minutes(n)})
    return out


def _chapter(key, title, md, icon=""):
    n = words(md)
    return {"key": str(key), "title": title, "icon": icon, "md": md, "words": n, "minutes": minutes(n), "sections": sections(md)}


# ── The books ────────────────────────────────────────────────────────────────
def parts(user, category):
    """The categories inside a book, in the order of its tree (each under the one it's in): {id: "SQL › Joins"}."""
    kids = {}
    for c in NoteCategory.objects.filter(owner=user).order_by("name", "pk"):
        kids.setdefault(c.parent_id, []).append(c)
    out, rank = {}, {}

    def walk(parent, path):
        for c in kids.get(parent, []):
            name = (path + " › " if path else "") + c.name
            out[c.pk], rank[c.pk] = name, len(rank)
            walk(c.pk, name)
    walk(category.pk, "")
    return out, rank


def notebook_notes(user, category):
    """A note category's notes (with what's inside it), as its chapters: in the order set in the Reader — and until
    then, the ones right in it first, then those of each category inside it, together (the part each is in: .part)."""
    qs = Note.objects.filter(owner=user, is_archived=False, is_template=False)
    notes = list(exam.notes_in_category(qs, user, category.pk).prefetch_related("categories"))
    names, rank = parts(user, category)
    for n in notes:
        mine = [c.pk for c in n.categories.all()]
        inside = sorted((c for c in mine if c in names), key=rank.get)
        n.part = "" if category.pk in mine or not inside else names[inside[-1]]       # (in the book itself: no part)
        n.part_rank = -1 if not n.part else rank[inside[-1]]
    return sorted(notes, key=lambda n: (n.book_order, n.part_rank, n.created_at, n.pk))


def note_chapters(notes):
    return [dict(_chapter(n.pk, n.display_title, n.body, n.icon), part=getattr(n, "part", "")) for n in notes]


def exam_chapters(subject):
    """An exam subject's chapters, in the order the questions are in: each section a ## heading, each question a ###
    heading with its answer below."""
    out, by = [], {}
    for q in exam.ordered(list(subject.notes.all())):
        if q.chapter not in by:
            by[q.chapter] = []
            out.append(q.chapter)
        part = by[q.chapter]
        if q.section and (not part or part[-1][0] != q.section):
            part.append((q.section, "## " + q.section))
        elif not q.section and part and part[-1][0]:                    # (after a section, the ones with none: under the chapter again)
            part.append(("", "## " + (q.chapter or _("No chapter"))))
        first, _sep, rest = q.question.strip().partition("\n")
        part.append((q.section, "### " + first.strip() + ("\n\n" + rest.strip() if rest.strip() else "") + "\n\n" + (q.answer.strip() or "*" + _("No answer written yet.") + "*")))
    return [_chapter(name, name or _("No chapter"), "\n\n".join(md for _s, md in by[name])) for name in out]


def progress(user, kind, chapters, subject=None):
    """{chapter key: {position, done, seconds, takeaway}} for these chapters."""
    if kind == "exam":
        rows = ReadingProgress.objects.filter(owner=user, subject=subject)
        key = lambda r: r.chapter  # noqa: E731
    else:
        rows = ReadingProgress.objects.filter(owner=user, note_id__in=[int(c["key"]) for c in chapters])
        key = lambda r: str(r.note_id)  # noqa: E731
    return {key(r): {"position": r.position, "done": r.done, "seconds": r.seconds, "takeaway": r.takeaway, "at": r.updated_at.isoformat()} for r in rows}


# ── Reading time, the daily goal, the streak ────────────────────────────────
def day_stats(user, today=None):
    today = today or timezone.localdate()
    goal = WorkSettings.for_user(user).reading_goal
    seconds = dict(ReadingDay.objects.filter(owner=user, day__gte=today - timedelta(days=400)).values_list("day", "seconds"))
    reached = (lambda s: s >= goal * 60) if goal else (lambda s: s > 0)
    streak, day = 0, today if reached(seconds.get(today, 0)) else today - timedelta(days=1)      # today still counts until it's over
    while reached(seconds.get(day, 0)):
        streak += 1
        day -= timedelta(days=1)
    ws = WorkSettings.for_user(user)
    week = [{"day": date_format(today - timedelta(days=back), "D"), "min": round(seconds.get(today - timedelta(days=back), 0) / 60),
             "met": reached(seconds.get(today - timedelta(days=back), 0)), "today": back == 0} for back in range(6, -1, -1)]
    return {"today": round(seconds.get(today, 0) / 60, 1), "goal": goal, "streak": streak, "reached": reached(seconds.get(today, 0)),
            "week": week, "weekMin": sum(x["min"] for x in week), "remind": ws.reading_remind_at.strftime("%H:%M") if ws.reading_remind_at else ""}


def parse_time(text):
    """"07:30" → a time; anything else (or nothing) → None."""
    from datetime import time

    m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*$", text or "")
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        return None
    return time(int(m.group(1)), int(m.group(2)))


def log(user, *, note=None, subject=None, chapter="", book=None, position=None, add_seconds=0, done=None, takeaway=None):
    """One report from the Reader: where it is in a chapter, time read since the last one, a chapter finished, a line kept."""
    add = max(0, min(int(add_seconds or 0), MAX_STEP))
    # (no transaction around these: each statement is its own, so SQLite never has to upgrade a read lock)
    if note is not None:
        row, _new = ReadingProgress.objects.get_or_create(owner=user, note=note, defaults={"book": book})
    else:
        row, _new = ReadingProgress.objects.get_or_create(owner=user, subject=subject, chapter=chapter[:120])
    if book is not None:
        row.book = book
    if position is not None:
        row.position = max(0.0, min(1.0, float(position)))
    if done is not None and done != row.done:
        row.done = done
        row.done_at = timezone.now() if done else None
    if takeaway is not None:
        row.takeaway = takeaway.strip()[:300]
    row.save()
    if add:
        ReadingProgress.objects.filter(pk=row.pk).update(seconds=F("seconds") + add)
        today = timezone.localdate()
        day, _new = ReadingDay.objects.get_or_create(owner=user, day=today)
        ReadingDay.objects.filter(pk=day.pk).update(seconds=F("seconds") + add)
    return row


# ── Continue reading ─────────────────────────────────────────────────────────
def book_url(row):
    if row.subject_id:
        return reverse("work:read_exam", args=[row.subject_id])
    if row.book_id:
        return reverse("work:read_book", args=[row.book_id]) + f"?ch={row.note_id}"
    return reverse("work:read_note", args=[row.note_id])


def keep_going(user, kind=None):
    """The book read last that isn't finished: its name, the chapter, how far, and the way back to the very line."""
    rows = ReadingProgress.objects.filter(owner=user).select_related("note", "subject", "book")
    if kind == "exam":
        rows = rows.filter(subject__isnull=False)
    elif kind == "notes":
        rows = rows.filter(note__isnull=False)
    for row in rows[:12]:
        if row.subject_id:
            chapters = exam_chapters(row.subject)
            title, name = row.subject.name, row.chapter or _("No chapter")
            keys = [c["key"] for c in chapters]
            done = set(ReadingProgress.objects.filter(owner=user, subject=row.subject, done=True).values_list("chapter", flat=True))
            at = next((c for c in chapters if c["key"] == row.chapter), None)
        elif row.book_id:
            notes = notebook_notes(user, row.book)
            chapters = note_chapters(notes)
            title, name = row.book.name, row.note.display_title
            keys = [c["key"] for c in chapters]
            done = {str(k) for k in ReadingProgress.objects.filter(owner=user, note_id__in=[n.pk for n in notes], done=True).values_list("note_id", flat=True)}
            at = next((c for c in chapters if c["key"] == str(row.note_id)), None)
        else:
            if row.note.is_archived:
                continue
            chapters = note_chapters([row.note])
            title, name, keys, at = row.note.display_title, row.note.display_title, [str(row.note_id)], chapters[0]
            done = {str(row.note_id)} if row.done else set()
        if not keys or len(done & set(keys)) == len(keys):
            continue                               # finished: nothing to go on with
        left = max(1, round((at["minutes"] if at else 1) * (1 - (0 if row.done else row.position))))
        return {"title": title, "chapter": name, "url": book_url(row), "done": len(done & set(keys)), "total": len(keys),
                "pct": round(100 * len(done & set(keys)) / len(keys)), "left": left, "subject": bool(row.subject_id)}
    return None


def reading_minutes_total(user):
    return round((ReadingDay.objects.filter(owner=user).aggregate(s=Sum("seconds"))["s"] or 0) / 60)


def exam_question_count(subject, chapter):
    return ExamNote.objects.filter(subject=subject, chapter=chapter).count()


def notebook_or_none(user, pk):
    return NoteCategory.objects.filter(owner=user, pk=pk).first()
