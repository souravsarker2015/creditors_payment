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


def _chapter(key, title, md, icon=""):
    n = words(md)
    return {"key": str(key), "title": title, "icon": icon, "md": md, "words": n, "minutes": minutes(n)}


# ── The books ────────────────────────────────────────────────────────────────
def notebook_notes(user, category):
    """A note category's notes (with what's inside it), as its chapters: in the order set in the Reader, then as written."""
    qs = Note.objects.filter(owner=user, is_archived=False, is_template=False)
    return list(exam.notes_in_category(qs, user, category.pk).order_by("book_order", "created_at", "pk"))


def note_chapters(notes):
    return [_chapter(n.pk, n.display_title, n.body, n.icon) for n in notes]


def exam_chapters(subject):
    """An exam subject's chapters, in the order the questions are in: each question a heading, its answer below."""
    out, by = [], {}
    for q in subject.notes.order_by("order", "pk"):
        if q.chapter not in by:
            by[q.chapter] = []
            out.append(q.chapter)
        first, _sep, rest = q.question.strip().partition("\n")
        by[q.chapter].append("### " + first.strip() + ("\n\n" + rest.strip() if rest.strip() else "") + "\n\n" + (q.answer.strip() or "*" + _("No answer written yet.") + "*"))
    return [_chapter(name, name or _("No chapter"), "\n\n".join(by[name])) for name in out]


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
    return {"today": round(seconds.get(today, 0) / 60, 1), "goal": goal, "streak": streak, "reached": reached(seconds.get(today, 0))}


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
