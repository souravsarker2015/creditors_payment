"""Exam notes pages (see exam.py): the subjects, a subject's questions and
answers (added, pasted, edited and deleted in place), flipping through them,
and the text download."""
import json

from django.contrib import messages
from django.db.models import Count, Max, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _, ngettext
from django.views.decorators.http import require_POST

from apps.trash.services import trash

from . import exam
from .access import work_required
from .forms import ExamSubjectForm
from .models import Color, ExamNote, ExamSubject
from .views import render_work

WHICH = ("unknown", "all", "starred", "missed")


def _texts():
    return {
        "notSaved": _("Not saved — check your connection."), "writeFirst": _("Write the question first."), "added": _("Added"),
        "deleted": _("Question deleted"), "noAnswer": _("No answer written yet."),
        "pasteFirst": _("Paste some questions first."), "resetAsk": _("Mark every question as not known yet?"),
        "leftOne": _("1 question left"), "left": _("%(n)s questions left"),
        "countOne": ngettext("%(counter)s question", "%(counter)s questions", 1), "count": ngettext("%(counter)s question", "%(counter)s questions", 2),
        "copied": _("Copied — paste it into ChatGPT or Claude."), "moved": _("Moved to %(name)s"), "noChapter": _("No chapter"),
        "renameAsk": _("New name for this chapter (empty: no chapter):"), "saved": _("Saved"),
        "found": _("%(n)s new questions found"), "picked": _("%(n)s picked"),
        "showMore": _("Show all"), "showLess": _("Show less"), "flipThese": _("Flip through these"),
        "important": _("Important"), "others": _("Others"),
        "bulkDeleteAsk": _("Delete the picked questions? You can bring them back from Recently deleted."),
        "deletedMany": _("%(n)s questions deleted"), "undo": _("Undo"), "chapterAsk": _("Chapter for the picked questions (empty: no chapter):"),
        "leave": _("You have changes that aren't saved yet. Leave anyway?"), "draftBack": _("Your unsaved question is back."),
        "perDay": _("about %(n)s a day to learn them all before the exam"), "allKnown": _("You know them all — keep them fresh with a quick review."),
    }


def _ai_prompt(subject):
    return _("Make revision notes for my exam on %(subject)s: the 20 most important questions, each with a clear, complete answer.\n\n"
             "Write them in Markdown, exactly like this:\n\n"
             "# Chapter name\n"
             "## The question?\n"
             "The answer — short paragraphs, lists, tables, code or formulas where they help.\n\n"
             "Use # only for chapters and ## only for questions. Write formulas as $…$.") % {"subject": subject.name}


def _subjects(user):
    return ExamSubject.objects.filter(owner=user).annotate(
        n=Count("notes"), known=Count("notes", filter=Q(notes__is_known=True)), missed=Count("notes", filter=Q(notes__misses__gt=0)),
        revised=Max("notes__reviewed_at"))


def _notes(s):
    return [exam.as_json(n, i) for i, n in enumerate(exam.ordered(s.notes.all()), 1)]


def _chapters(notes):
    return list(dict.fromkeys(n["chapter"] for n in notes if n["chapter"]))


@work_required
def exam_home_view(request):
    """Every subject, soonest exam first, and a search through all the questions."""
    form = ExamSubjectForm(request.POST or None, owner=request.user)
    if request.method == "POST" and form.is_valid():
        s = form.save(commit=False)
        s.owner = request.user
        s.save()
        return redirect("work:exam_subject", pk=s.pk)
    subjects = sorted(_subjects(request.user), key=lambda s: (s.exam_date is None or s.days_left < 0, s.exam_date or s.created_at.date(), s.name.lower()))
    q = (request.GET.get("q") or "").strip()
    found = []
    if q:
        found = list(ExamNote.objects.filter(owner=request.user).filter(Q(question__icontains=q) | Q(answer__icontains=q) | Q(chapter__icontains=q))
                     .select_related("subject")[:100])
        for n in found:
            n.snippet = exam.plain(n.answer)
    return render_work(request, "work/exam/home.html", {"subjects": subjects, "form": form, "q": q, "found": found,
                                                        "total": sum(s.n for s in subjects)})


@work_required
def exam_subject_view(request, pk):
    """A subject's questions, numbered in order, chapter by chapter. Edit the subject here too."""
    s = get_object_or_404(ExamSubject, pk=pk, owner=request.user)
    form = ExamSubjectForm(request.POST or None, instance=s, owner=request.user)
    if request.method == "POST":
        if request.POST.get("action") == "delete":
            n = s.notes.count()
            trash(request.user, s, _("Subject: %(name)s (%(n)s questions)") % {"name": s.name, "n": n}, reverse("work:exam"))
            messages.success(request, _("Subject deleted with its questions. You can bring it back from Recently deleted."))
            return redirect("work:exam")
        if form.is_valid():
            form.save()
            messages.success(request, _("Subject saved."))
            return redirect("work:exam_subject", pk=s.pk)
    return render_work(request, "work/exam/subject.html", {
        "s": s, "form": form, "n": s.notes.count(), "prompt": _ai_prompt(s), "colors": Color.choices,
        "data": _board_data(request, s), "exam_text": _texts(),
    })


def _board_data(request, s):
    """What the board and the overview start with; the questions themselves come a page at a time (notes_api)."""
    return {"api": reverse("work:api_exam_subject", args=[s.pk]), "noteBase": reverse("work:api_exam_note", args=[0])[:-2],
            "notes": reverse("work:api_exam_notes", args=[s.pk]), "review": reverse("work:exam_review", args=[s.pk]),
            "overview": reverse("work:exam_overview", args=[s.pk]), "back": reverse("work:exam_subject", args=[s.pk]),
            "subject": s.pk, "daysLeft": s.days_left, **exam.counts(s),
            "subjects": [{"id": x.pk, "name": x.name} for x in ExamSubject.objects.filter(owner=request.user)]}


@work_required
def notes_api(request, pk):
    """A page of a subject's questions (30), filtered and searched on the server:
    ?show=all|unknown|missed|starred &chapter= &q= &sort=order|new &pinned=1 &page=N."""
    s = get_object_or_404(ExamSubject, pk=pk, owner=request.user)
    show = request.GET.get("show") if request.GET.get("show") in exam.SHOWS else "all"
    chapter = request.GET["chapter"] if "chapter" in request.GET else None
    qs = exam.filtered(s, show, chapter, request.GET.get("q", ""))
    if request.GET.get("sort") == "new":
        qs = qs.order_by("-created_at", "-pk")
    else:
        qs = exam.in_order(qs)
        if request.GET.get("pinned") == "1":            # the board: important ones first, as Keep's pinned notes
            qs = qs.order_by("-is_starred", "chapter_first", "chapter_pk", "order", "pk")
    try:
        page = max(1, int(request.GET.get("page") or 1))
    except ValueError:
        page = 1
    rows = list(qs[(page - 1) * exam.PAGE: page * exam.PAGE + 1])
    more = len(rows) > exam.PAGE
    number = exam.numbers(s)
    out = {"ok": True, "notes": [exam.as_json(n, number.get(n.pk)) for n in rows[:exam.PAGE]], "next": page + 1 if more else None}
    if page == 1:
        out["total"] = qs.count()
        out.update(exam.counts(s))
    return JsonResponse(out)


@work_required
def exam_overview_view(request, pk):
    """Every question and answer of a subject on one page, chapter by chapter —
    to read through quickly before the exam or interview (on a phone too)."""
    s = get_object_or_404(ExamSubject, pk=pk, owner=request.user)
    return render_work(request, "work/exam/overview.html", {"s": s, "n": s.notes.count(), "exam_text": _texts(), "data": _board_data(request, s)})


@work_required
def exam_review_view(request, pk):
    """Flip through the questions one at a time: think of the answer, show it, say whether you knew it."""
    s = get_object_or_404(ExamSubject, pk=pk, owner=request.user)
    notes = _notes(s)
    which = request.GET.get("which") if request.GET.get("which") in WHICH else "unknown"
    if which == "unknown" and notes and all(n["known"] for n in notes):
        which = "all"
    chapters = _chapters(notes)
    chapter = request.GET.get("chapter", "")
    return render_work(request, "work/exam/review.html", {
        "s": s, "n": len(notes), "exam_text": _texts(),
        "data": {"notes": notes, "noteBase": reverse("work:api_exam_note", args=[0])[:-2], "which": which, "chapters": chapters,
                 "chapter": chapter if chapter in chapters else "", "shuffle": request.GET.get("shuffle") == "1",
                 "back": reverse("work:exam_subject", args=[s.pk])},
    })


@work_required
def exam_export_view(request, pk):
    s = get_object_or_404(ExamSubject, pk=pk, owner=request.user)
    resp = HttpResponse(exam.as_text(s, s.notes.all()), content_type="text/plain; charset=utf-8")
    name = "".join(c if c.isalnum() or c in "-_" else "-" for c in s.name).strip("-")[:60] or "exam-notes"
    resp["Content-Disposition"] = f'attachment; filename="{name}.txt"'
    return resp


# ── In-page changes (Work.api) ───────────────────────────────────────────
def _chapter_of(request):
    return (request.POST.get("chapter") or "").strip()[:exam.MAX_CHAPTER]


@work_required
@require_POST
def subject_api(request, pk):
    s = get_object_or_404(ExamSubject, pk=pk, owner=request.user)
    action = request.POST.get("action")
    if action == "add":
        question = (request.POST.get("question") or "").strip()[:exam.MAX_QUESTION]
        if not question:
            return JsonResponse({"ok": False, "error": _("Write the question first.")}, status=400)
        n = ExamNote.objects.create(owner=request.user, subject=s, question=question, chapter=_chapter_of(request), order=exam.next_order(s),
                                    color=request.POST.get("color") if request.POST.get("color") in Color.values else "",
                                    is_starred=request.POST.get("starred") == "1",
                                    answer=(request.POST.get("answer") or "").rstrip()[:exam.MAX_ANSWER])
        return JsonResponse({"ok": True, "note": exam.as_json(n, exam.numbers(s).get(n.pk)), **exam.counts(s)})
    if action == "add_many":
        found = exam.parse(request.POST.get("text"), chapter=_chapter_of(request))
        if not found:
            return JsonResponse({"ok": False, "error": _("No questions found. Put each question on a ## heading, or start it with Q: — or leave an empty line between them.")}, status=400)
        seen = {exam.same(q) for q in s.notes.values_list("question", flat=True)}
        for n in found:                      # already in the subject, or twice in the paste
            key = exam.same(n["question"])
            n["dupe"] = key in seen
            seen.add(key)
        fresh = [n for n in found if not n["dupe"]]
        if request.POST.get("preview"):
            return JsonResponse({"ok": True, "found": [dict(n, answer=n["answer"][:600]) for n in found], "new": len(fresh)})
        if "pick" in request.POST:            # the ones ticked in the preview (numbers in the found list)
            picked = {int(i) for i in request.POST["pick"].split(",") if i.strip().isdigit()}
            fresh = [n for i, n in enumerate(found) if i in picked]
        start = exam.next_order(s)
        made = ExamNote.objects.bulk_create([ExamNote(owner=request.user, subject=s, question=n["question"], answer=n["answer"], chapter=n["chapter"],
                                                      order=start + i) for i, n in enumerate(fresh)])
        made = list(s.notes.order_by("-pk")[:len(made)])[::-1] if made else []     # bulk_create gives no ids on every database
        message = ngettext("%(n)s question added.", "%(n)s questions added.", len(made)) % {"n": len(made)}
        skipped = sum(1 for n in found if n["dupe"])
        if skipped and "pick" not in request.POST:
            message += " " + ngettext("%(n)s was already there.", "%(n)s were already there.", skipped) % {"n": skipped}
        number = exam.numbers(s)
        return JsonResponse({"ok": True, "notes": [exam.as_json(n, number.get(n.pk)) for n in made], "message": message, **exam.counts(s)})
    if action == "move":                     # a card dropped before another (or last): it takes that one's chapter
        note = get_object_or_404(ExamNote, pk=request.POST.get("id"), subject=s)
        before = request.POST.get("before")
        exam.move(note, int(before) if (before or "").isdigit() else None)
        return JsonResponse({"ok": True, "chapter": ExamNote.objects.get(pk=note.pk).chapter, **exam.counts(s)})
    if action == "chapter_move":             # a whole chapter one place up or down
        names = [c["name"] for c in exam.chapter_list(s)]
        name, step = request.POST.get("chapter", ""), 1 if request.POST.get("step") == "1" else -1
        if name in names and 0 <= names.index(name) + step < len(names):
            i = names.index(name)
            names[i], names[i + step] = names[i + step], names[i]
            by = {}
            for pk, chapter in exam.in_order(s.notes.all()).values_list("pk", "chapter"):
                by.setdefault(chapter, []).append(pk)
            rows = {n.pk: n for n in s.notes.all()}
            for place, pk in enumerate((pk for n in names for pk in by.get(n, [])), 1):
                rows[pk].order = place
            ExamNote.objects.bulk_update(rows.values(), ["order"])
        return JsonResponse({"ok": True, **exam.counts(s)})
    if action == "order":                    # after a drag: [[id, chapter], …] top to bottom
        try:
            rows = [(int(i), str(c or "")[:exam.MAX_CHAPTER]) for i, c in json.loads(request.POST.get("rows") or "[]")]
        except (TypeError, ValueError):
            return JsonResponse({"ok": False, "error": "rows"}, status=400)
        notes = {n.pk: n for n in s.notes.filter(pk__in=[i for i, _c in rows])}
        for place, (i, chapter) in enumerate(rows, 1):
            if i in notes:
                notes[i].order, notes[i].chapter = place, chapter.strip()
        ExamNote.objects.bulk_update(notes.values(), ["order", "chapter"])
        return JsonResponse({"ok": True})
    if action == "bulk":                     # picked questions: delete, mark, chapter, move
        picked = list(s.notes.filter(pk__in=[int(i) for i in (request.POST.get("ids") or "").split(",") if i.strip().isdigit()]))
        op = request.POST.get("op")
        if op == "delete":
            undo = [reverse("trash_restore", args=[trash(request.user, n, _("Exam question: %(title)s") % {"title": n.question[:80]},
                                                          reverse("work:exam_subject", args=[s.pk])).pk]) for n in picked]
            return JsonResponse({"ok": True, "undo": undo})
        if op in ("known", "unknown"):
            s.notes.filter(pk__in=[n.pk for n in picked]).update(is_known=op == "known", updated_at=timezone.now())
        elif op == "chapter":
            s.notes.filter(pk__in=[n.pk for n in picked]).update(chapter=_chapter_of(request), updated_at=timezone.now())
        elif op == "move":
            to = get_object_or_404(ExamSubject, pk=request.POST.get("subject"), owner=request.user)
            start = exam.next_order(to)
            for i, n in enumerate(picked):
                n.subject, n.order = to, start + i
            ExamNote.objects.bulk_update(picked, ["subject", "order"])
            return JsonResponse({"ok": True, "message": ngettext("%(n)s question moved to %(name)s.", "%(n)s questions moved to %(name)s.", len(picked))
                                 % {"n": len(picked), "name": to.name}})
        else:
            return JsonResponse({"ok": False, "error": "op"}, status=400)
        return JsonResponse({"ok": True})
    if action == "rename_chapter":
        s.notes.filter(chapter=request.POST.get("old", "")).update(chapter=_chapter_of(request), updated_at=timezone.now())
        return JsonResponse({"ok": True})
    if action == "reset":
        s.notes.update(is_known=False)
        return JsonResponse({"ok": True})
    return JsonResponse({"ok": False, "error": "action"}, status=400)


@work_required
@require_POST
def note_api(request, pk):
    n = get_object_or_404(ExamNote, pk=pk, owner=request.user)
    action = request.POST.get("action")
    if action == "update":
        question = (request.POST.get("question", n.question) or "").strip()
        if not question:
            return JsonResponse({"ok": False, "error": _("Write the question first.")}, status=400)
        n.question, n.answer = question[:exam.MAX_QUESTION], (request.POST.get("answer", n.answer) or "").rstrip()[:exam.MAX_ANSWER]
        if "chapter" in request.POST:
            n.chapter = _chapter_of(request)
        if request.POST.get("color", None) is not None and request.POST["color"] in ("", *Color.values):
            n.color = request.POST["color"]
        if request.POST.get("subject") and str(request.POST["subject"]) != str(n.subject_id):
            n.subject = get_object_or_404(ExamSubject, pk=request.POST["subject"], owner=request.user)
            n.order = exam.next_order(n.subject)
        n.save()
        return JsonResponse({"ok": True, "note": exam.as_json(n)})
    if action == "color":
        n.color = request.POST.get("color") if request.POST.get("color") in Color.values else ""
        n.save(update_fields=["color", "updated_at"])
        return JsonResponse({"ok": True, "color": n.color})
    if action in ("star", "known"):
        field = "is_starred" if action == "star" else "is_known"
        value = request.POST.get("value")
        setattr(n, field, value in ("1", "true") if value is not None else not getattr(n, field))
        n.save(update_fields=[field, "updated_at"])
        return JsonResponse({"ok": True, "value": getattr(n, field)})
    if action == "unreview":                 # "Undo" in a review: back to how it was before that answer
        n.is_known = request.POST.get("known") == "1"
        if (request.POST.get("misses") or "").isdigit():
            n.misses = int(request.POST["misses"])
        n.save(update_fields=["is_known", "misses", "updated_at"])
        return JsonResponse({"ok": True})
    if action == "review":                   # an answer in a review: knew it, or not yet
        n.is_known = request.POST.get("knew") == "1"
        n.misses += 0 if n.is_known else 1
        n.reviewed_at = timezone.now()
        n.save(update_fields=["is_known", "misses", "reviewed_at", "updated_at"])
        return JsonResponse({"ok": True, "misses": n.misses})
    if action == "delete":
        item = trash(request.user, n, _("Exam question: %(title)s") % {"title": n.question[:80]}, reverse("work:exam_subject", args=[n.subject_id]))
        return JsonResponse({"ok": True, "undo": reverse("trash_restore", args=[item.pk])})
    return JsonResponse({"ok": False, "error": "action"}, status=400)
