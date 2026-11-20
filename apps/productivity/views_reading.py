"""The Reader's pages (a note category, one note, an exam subject — as a book) and what it saves as you read
(static/js/reader.js). The books themselves: reading.py."""
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_POST

from . import reading
from .access import work_required
from .models import ExamSubject, Note, NoteCategory, WorkSettings
from .views import render_work
from apps.core.freshness import quiet


def _texts():
    return {
        "minRead": _("≈ %(n)s min read"), "minLeft": _("%(n)s min left"), "chapterOf": _("Chapter %(n)s of %(total)s"),
        "done": _("Chapter done"), "endOf": _("End of the chapter"), "allDone": _("You've read the whole book. Well done!"), "goalMet": _("Today's reading goal reached!"),
        "saved": _("Kept"), "listen": _("Listen"), "pause": _("Pause"), "noVoice": _("This browser can't read aloud."),
        "noBangla": _("No Bangla voice in this browser, so the Bangla parts are skipped. Open Aa to see how to get one."),
        "today": _("%(n)s / %(goal)s min today"), "todayNoGoal": _("%(n)s min today"), "copied": _("Copied"),
        "focusOn": _("Focus line on: ↑ ↓ move it"), "tapAnswer": _("Think of the answer, then tap to see it"),
        "remindSet": _("Reminder set for %(time)s each day"), "remindOff": _("No reminder"), "orderSaved": _("Order saved"), "undo": _("Undo"), "notSaved": _("Not saved."),
    }


def _page(request, *, title, kind, chapters, book_id, back, back_label, subject=None, start=None, extra=None):
    user = request.user
    progress = reading.progress(user, kind, chapters, subject=subject)
    if start is None:                 # where you were: the chapter last read, else the first not done
        latest = max(((p["at"], k) for k, p in progress.items() if k in {c["key"] for c in chapters}), default=None)
        start = latest[1] if latest else next((c["key"] for c in chapters if not progress.get(c["key"], {}).get("done")), chapters[0]["key"])
    data = {
        "kind": kind, "book": book_id, "title": title, "chapters": chapters, "progress": progress, "start": str(start),
        "stats": reading.day_stats(user), "api": reverse("work:api_reading"), "back": back,
        "review": reverse("work:exam_review", args=[subject.pk]) if subject else "",
        "canOrder": kind == "book",
        **(extra or {}),
    }
    return render_work(request, "work/read.html", {"title": title, "data": data, "texts": _texts(), "back": back, "back_label": back_label})


@work_required
def read_book(request, pk):
    """A note category as a book: its notes (and those of what's inside it) are the chapters."""
    cat = get_object_or_404(NoteCategory, pk=pk, owner=request.user)
    notes = reading.notebook_notes(request.user, cat)
    back = reverse("work:notes") + f"?category={cat.pk}"
    if not notes:
        messages.info(request, _("“%(name)s” has no notes yet — write one, then read it here as a book.") % {"name": cat.name})
        return redirect(back)
    chapters = reading.note_chapters(notes)
    asked = request.GET.get("ch", "")
    start = asked if asked in {c["key"] for c in chapters} else None
    return _page(request, title=cat.name, kind="book", chapters=chapters, book_id=cat.pk, back=back, back_label=_("Notes"), start=start,
                 extra={"edit": reverse("work:note", args=[0])[:-2]})


@work_required
def read_note(request, pk):
    """One note, read on its own (when it's in a category, that book is a tap away)."""
    note = get_object_or_404(Note, pk=pk, owner=request.user)
    cat = note.categories.order_by("pk").first()
    return _page(request, title=note.display_title, kind="note", chapters=reading.note_chapters([note]), book_id=None,
                 back=reverse("work:note", args=[note.pk]), back_label=_("Note"), start=str(note.pk),
                 extra={"edit": reverse("work:note", args=[0])[:-2],
                        "asBook": reverse("work:read_book", args=[cat.pk]) + f"?ch={note.pk}" if cat else "", "asBookName": cat.name if cat else ""})


@work_required
def read_exam(request, pk):
    """An exam subject as a book: its chapters, each question a heading and its answer below."""
    s = get_object_or_404(ExamSubject, pk=pk, owner=request.user)
    chapters = reading.exam_chapters(s)
    back = reverse("work:exam_subject", args=[s.pk])
    if not chapters:
        messages.info(request, _("Add a few questions first — then read them here like a book."))
        return redirect(back)
    asked = request.GET.get("ch")
    start = asked if asked is not None and asked in {c["key"] for c in chapters} else None
    return _page(request, title=s.name, kind="exam", chapters=chapters, book_id=s.pk, back=back, back_label=_("Exam notes"), subject=s, start=start)


@work_required
@require_POST
def reading_api(request):
    """What the Reader saves as you read: where you are in a chapter, the time read since the last report, a chapter
    finished or a line kept — or (action=order) the chapters of a note book put in a new order."""
    user, p = request.user, request.POST
    if p.get("action") == "goal":            # the daily goal (minutes) and/or the time of the reminder ("" : none)
        ws, fields = WorkSettings.for_user(user), []
        if "goal" in p:
            try:
                ws.reading_goal = max(0, min(240, int(p.get("goal", ""))))
            except ValueError:
                return JsonResponse({"ok": False}, status=400)
            fields.append("reading_goal")
        if "remind" in p:
            ws.reading_remind_at = reading.parse_time(p["remind"])
            if p["remind"].strip() and ws.reading_remind_at is None:
                return JsonResponse({"ok": False}, status=400)
            fields.append("reading_remind_at")
        if fields:
            ws.save(update_fields=fields)
        return JsonResponse({"ok": True, "stats": reading.day_stats(user)})
    if p.get("action") == "order":
        ids = [int(i) for i in p.get("ids", "").split(",") if i.strip().isdigit()]
        notes = {n.pk: n for n in Note.objects.filter(owner=user, pk__in=ids)}
        for place, pk in enumerate(ids):
            if pk in notes:
                notes[pk].book_order = place
        Note.objects.bulk_update(notes.values(), ["book_order"])
        return JsonResponse({"ok": True})
    kind = p.get("kind")
    try:
        position = float(p["position"]) if p.get("position", "") != "" else None
        add = int(p.get("seconds") or 0)
    except ValueError:
        return JsonResponse({"ok": False}, status=400)
    done = {"1": True, "0": False}.get(p.get("done", ""))
    takeaway = p.get("takeaway") if "takeaway" in p else None
    if done is None and takeaway is None:
        # only the clock and your place: no page needs rebuilding for it — or the Reader (and every other open
        # page) would reload each time you came back from another tab, after its save on the way out
        quiet(request)
    if kind == "exam":
        subject = get_object_or_404(ExamSubject, pk=p.get("book") or 0, owner=user)
        reading.log(user, subject=subject, chapter=p.get("chapter", ""), position=position, add_seconds=add, done=done, takeaway=takeaway)
    else:
        note = get_object_or_404(Note, pk=p.get("chapter") or 0, owner=user)
        book = NoteCategory.objects.filter(owner=user, pk=p.get("book") or 0).first() if kind == "book" else None
        reading.log(user, note=note, book=book, position=position, add_seconds=add, done=done, takeaway=takeaway)
    return JsonResponse({"ok": True, "stats": reading.day_stats(user)})


@work_required
@require_GET
def reading_nudge(request):
    """For the reminder (static/js/work.js, at the time set): nothing when today's goal is reached already, else
    how far today is and the book to go on with."""
    stats = reading.day_stats(request.user)
    if stats["reached"] and stats["goal"]:
        return JsonResponse({"ok": True, "due": False})
    book = reading.keep_going(request.user)
    return JsonResponse({"ok": True, "due": True, "today": stats["today"], "goal": stats["goal"], "streak": stats["streak"],
                         "title": book["title"] if book else "", "chapter": book["chapter"] if book else "",
                         "url": book["url"] if book else reverse("work:notes")})
