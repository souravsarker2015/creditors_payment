"""Interview prep pages (see prep.py): the dashboard, the question bank, a
question's page, practice sessions, timed mock exams, topics, and bringing
questions in and out."""
import csv
import json
from datetime import timedelta

from django.contrib import messages
from django.core.paginator import Paginator
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _, ngettext
from django.views.decorators.http import require_POST

from apps.trash.services import trash

from . import prep
from .access import work_required
from .forms import PrepGoalForm, PrepTopicForm, QuestionForm
from .models import Difficulty, PrepExam, PrepTopic, Question, QuestionKind, WorkSettings
from .prep_packs import PACKS
from .views import render_work

FILTER_KEYS = ("topic", "kind", "difficulty", "status", "starred", "q", "company", "tag")


def _filters(source):
    return {k: (source.get(k) or "").strip() for k in FILTER_KEYS}


def _texts():
    return {
        "check": _("Check"), "show": _("Show the answer"), "next": _("Next"), "right": _("Right!"), "wrong": _("Not quite"),
        "partly": _("Partly right"), "again": _("Again"), "hard": _("Hard"), "good": _("Good"), "easy": _("Easy"),
        "yourAnswer": _("Your answer"), "pick": _("Pick an answer first."), "pickAll": _("Pick every right answer."),
        "timeUp": _("Time's up — your answers have been handed in."), "leave": _("Leave the exam? Your answers are kept, and the clock keeps running."),
        "unanswered": _("%(n)s questions have no answer yet. Hand in anyway?"), "submit": _("Hand in the exam now?"),
        "saved": _("Saved"), "offline": _("Not saved — check your connection."), "covered": _("You covered %(n)s of %(total)s key points"),
        "starred": _("Starred"), "unstarred": _("Star removed"), "noteSaved": _("Note saved"),
        "runLoading": _("Getting ready — the first run takes a few seconds…"), "running": _("Running…"),
        "runTimeout": _("Stopped: it ran too long. Is there an endless loop?"), "runPass": _("All checks passed"),
        "runMatch": _("Same result as the model answer"), "runDiffer": _("A different result from the model answer's"),
        "runFail": _("A check failed"), "runError": _("There's an error"), "runDone": _("Ran in %(ms)s ms"),
    }


# ── The dashboard ─────────────────────────────────────────────────────────
@work_required
def prep_view(request):
    user, today = request.user, timezone.localdate()
    s = WorkSettings.for_user(user)
    goal_form = PrepGoalForm(instance=s, prefix="goal")
    topic_form = PrepTopicForm(owner=user, prefix="topic")
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "goal":
            goal_form = PrepGoalForm(request.POST, instance=s, prefix="goal")
            if goal_form.is_valid():
                goal_form.save()
                messages.success(request, _("Saved."))
                return redirect("work:prep")
        elif action == "topic":
            topic_form = PrepTopicForm(request.POST, owner=user, prefix="topic")
            if topic_form.is_valid():
                t = topic_form.save(commit=False)
                t.owner, t.order = user, PrepTopic.objects.filter(owner=user).count()
                t.save()
                messages.success(request, _("Topic added. Now add its questions."))
                return redirect(reverse("work:question_new") + f"?topic={t.pk}")
        elif action == "pack":
            keys = [k for k in request.POST.getlist("pack") if k in PACKS]
            n = sum(prep.install_pack(user, k) for k in keys)
            if n:
                messages.success(request, ngettext("%(n)s question added.", "%(n)s questions added.", n) % {"n": n})
            else:
                messages.info(request, _("Those questions are already in your bank."))
            return redirect("work:prep")
    o = prep.overview(user, today)
    have = {t.lower() for t in PrepTopic.objects.filter(owner=user).values_list("name", flat=True)}
    packs = [{"key": k, "name": p["name"], "about": p["about"], "color": p["color"], "n": len(p["questions"]), "added": p["name"].lower() in have}
             for k, p in PACKS.items()]
    days_left = (s.prep_exam_date - today).days if s.prep_exam_date else None
    return render_work(request, "work/prep/home.html", {
        "o": o, "ws": s, "goal_form": goal_form, "topic_form": topic_form, "packs": packs, "today": today, "days_left": days_left,
        "per_day": -(-o["new"] // days_left) if days_left and days_left > 0 and o["new"] else None,     # rounded up
        "exams": PrepExam.objects.filter(owner=user)[:8], "kinds": QuestionKind.choices, "difficulties": Difficulty.choices,
        "topics": PrepTopic.objects.filter(owner=user),
    })


# ── The question bank ─────────────────────────────────────────────────────
@work_required
def questions_view(request):
    user = request.user
    f = _filters(request.GET)
    qs = prep.filtered(user, f).prefetch_related("tags")
    page = Paginator(qs.order_by("topic__order", "topic__name", "difficulty", "pk"), 50).get_page(request.GET.get("page"))
    base = request.GET.copy()
    base.pop("page", None)
    from apps.accounts.views import _page_window

    return render_work(request, "work/prep/questions.html", {
        "page": page, "f": f, "filtered": any(f.values()), "topics": PrepTopic.objects.filter(owner=user),
        "kinds": QuestionKind.choices, "difficulties": Difficulty.choices, "total": qs.count(),
        "query": base.urlencode(), "base_query_string": base.urlencode(), "pagination_window": _page_window(page),
    })


@work_required
def question_view(request, pk):
    q = get_object_or_404(Question.objects.select_related("topic"), pk=pk, owner=request.user)
    return render_work(request, "work/prep/question.html", {
        "q": q, "history": q.history.all()[:20], "prep_text": _texts(),
        "data": {"questions": [prep.as_json(q)], "single": True, "practice": reverse("work:prep_practice")},
        "siblings": Question.objects.filter(owner=request.user, topic=q.topic).exclude(pk=q.pk).order_by("?")[:5],
    })


@work_required
def question_form_view(request, pk=None):
    user = request.user
    q = get_object_or_404(Question, pk=pk, owner=user) if pk else None
    if request.method == "POST" and request.POST.get("action") == "delete" and q:
        topic_id = q.topic_id
        trash(user, q, _("Question: %(title)s") % {"title": q.title[:80]}, reverse("work:questions"))
        messages.success(request, _("Question deleted. You can bring it back from Recently deleted."))
        return redirect(reverse("work:questions") + f"?topic={topic_id}")
    initial = {}
    if not q:
        last = Question.objects.filter(owner=user).order_by("-created_at").first()
        initial = {"topic": request.GET.get("topic") or (last.topic_id if last else None), "kind": request.GET.get("kind") or QuestionKind.SHORT,
                   "difficulty": Difficulty.MEDIUM}
    form = QuestionForm(request.POST or None, instance=q, owner=user, initial=initial)
    if request.method == "POST" and form.is_valid():
        saved = form.save()
        messages.success(request, _("Question saved."))
        if request.POST.get("then") == "another":
            return redirect(reverse("work:question_new") + f"?topic={saved.topic_id}&kind={saved.kind}")
        return redirect("work:question", pk=saved.pk)
    return render_work(request, "work/prep/question_form.html", {"form": form, "q": q, "has_topics": PrepTopic.objects.filter(owner=user).exists()})


@work_required
def topic_view(request, pk):
    t = get_object_or_404(PrepTopic, pk=pk, owner=request.user)
    form = PrepTopicForm(request.POST or None, instance=t, owner=request.user)
    if request.method == "POST":
        if request.POST.get("action") == "delete":
            n = t.questions.count()
            trash(request.user, t, _("Topic: %(name)s (%(n)s questions)") % {"name": t.name, "n": n}, reverse("work:prep"))
            messages.success(request, _("Topic deleted with its questions. You can bring it back from Recently deleted."))
            return redirect("work:prep")
        if form.is_valid():
            form.save()
            messages.success(request, _("Topic saved."))
            return redirect("work:prep")
    return render_work(request, "work/prep/topic.html", {"form": form, "t": t, "n": t.questions.count()})


# ── Practice ──────────────────────────────────────────────────────────────
@work_required
def practice_view(request):
    """?set=today (the schedule) — or any filter, a count and an order — or ids=1,2,3."""
    user = request.user
    g = request.GET
    if g.get("ids"):
        ids = [int(x) for x in g["ids"].split(",") if x.strip().isdigit()][:prep.SESSION_MAX]
        found = Question.objects.filter(owner=user, pk__in=ids).select_related("topic").in_bulk()
        items, title = [found[i] for i in ids if i in found], _("Practise these again")
    elif g.get("set") == "today":
        topic = PrepTopic.objects.filter(owner=user, pk=g.get("topic") or 0).first()
        items, title = prep.today_queue(user, topic=topic), _("Today's practice")
    else:
        f = _filters(g)
        items = prep.practice_queue(user, f, count=g.get("count") or 20, order=g.get("order") or "smart")
        topic = PrepTopic.objects.filter(owner=user, pk=f["topic"]).first() if f["topic"].isdigit() else None
        title = topic.name if topic else _("Practice")
    return render_work(request, "work/prep/practice.html", {
        "title": title, "session": {"questions": [prep.as_json(q) for q in items], "back": reverse("work:prep"), "practice": reverse("work:prep_practice")},
        "prep_text": _texts(),
        "count": len(items),
    })


@work_required
@require_POST
def prep_answer(request, pk):
    """One answer from a practice session or a question's page: choice=0,2 (marked here) or rating=1–4."""
    q = get_object_or_404(Question, pk=pk, owner=request.user)
    seconds = int(request.POST.get("seconds") or 0) if (request.POST.get("seconds") or "").isdigit() else 0
    text = (request.POST.get("text") or "")[:4000]
    if q.kind == QuestionKind.CHOICE and request.POST.get("choice") is not None:
        chosen = [int(x) for x in request.POST.get("choice", "").split(",") if x.strip().isdigit()]
        right = prep.chosen_right(q, chosen)
        rating = int(request.POST.get("rating") or 0) or (prep.GOOD if right else prep.AGAIN)
        prep.answer(q, rating if right else prep.AGAIN, score=1 if right else 0, seconds=seconds, response={"choice": chosen})
        return JsonResponse({"ok": True, "right": right, "status": q.status})
    try:
        rating = int(request.POST.get("rating") or 0)
        score = float(request.POST["score"]) if request.POST.get("score") not in (None, "") else None
    except ValueError:
        return JsonResponse({"ok": False, "error": "rating"}, status=400)
    if rating not in (1, 2, 3, 4):
        return JsonResponse({"ok": False, "error": "rating"}, status=400)
    prep.answer(q, rating, score=None if score is None else max(0.0, min(score, 1.0)), seconds=seconds, response={"text": text} if text else {})
    return JsonResponse({"ok": True, "status": q.status})


@work_required
@require_POST
def question_action(request, pk):
    q = get_object_or_404(Question, pk=pk, owner=request.user)
    action = request.POST.get("action")
    if action == "star":
        q.is_starred = not q.is_starred
        q.save(update_fields=["is_starred", "updated_at"])
        return JsonResponse({"ok": True, "starred": q.is_starred})
    if action == "notes":
        q.notes = (request.POST.get("notes") or "")[:20000]
        q.save(update_fields=["notes", "updated_at"])
        return JsonResponse({"ok": True})
    if action == "reset":                 # start over: like a new question
        q.interval, q.ease, q.reps, q.lapses, q.last_reviewed, q.last_rating, q.due = 0, 2.5, 0, 0, None, None, timezone.localdate()
        q.save(update_fields=["interval", "ease", "reps", "lapses", "last_reviewed", "last_rating", "due", "updated_at"])
        return JsonResponse({"ok": True, "status": q.status})
    return JsonResponse({"ok": False, "error": "action"}, status=400)


# ── Mock exams ────────────────────────────────────────────────────────────
@work_required
@require_POST
def exam_new_view(request):
    f = _filters(request.POST)
    exam = prep.new_exam(request.user, f, count=request.POST.get("count") or 20, minutes=request.POST.get("minutes") or 30,
                         title=request.POST.get("title", ""))
    if exam is None:
        messages.error(request, _("No questions match — change the topic or the filters."))
        return redirect("work:prep")
    return redirect("work:exam", pk=exam.pk)


@work_required
def exam_view(request, pk):
    exam = get_object_or_404(PrepExam, pk=pk, owner=request.user)
    now = timezone.now()
    if not exam.finished_at and now >= exam.ends_at + timedelta(minutes=1):
        prep.finish(exam, now=exam.ends_at)        # the time ran out while away: handed in as it was
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "submit" and not exam.finished_at:
            try:
                answers = json.loads(request.POST.get("answers") or "{}")
            except ValueError:
                answers = None
            prep.finish(exam, answers)
            return redirect("work:exam", pk=exam.pk)
        if action == "mark" and exam.finished_at:
            marks = {k[5:]: v for k, v in request.POST.items() if k.startswith("mark-")}
            prep.mark(exam, marks)
            if exam.graded_at:
                messages.success(request, _("Exam marked: %(score)s%%.") % {"score": f"{exam.score:g}"})
            return redirect(reverse("work:exam", args=[exam.pk]) + "#results")
        if action == "delete":
            exam.delete()
            messages.success(request, _("Exam deleted."))
            return redirect("work:prep")
    questions = prep.exam_questions(exam)
    if not exam.finished_at:
        return render_work(request, "work/prep/exam.html", {
            "exam": exam, "prep_text": _texts(),
            "data": {"id": exam.pk, "questions": [prep.as_json(q, for_exam=True) for q in questions], "answers": exam.answers,
                     "ends": exam.ends_at.isoformat(), "save": reverse("work:api_exam_save", args=[exam.pk]), "back": reverse("work:prep")},
        })
    report = prep.exam_report(exam)
    wrong = [x["q"].pk for x in report["items"] if x["mark"] is not None and x["mark"] < 1]
    took = int(((exam.finished_at or now) - exam.started_at).total_seconds())
    return render_work(request, "work/prep/exam_result.html", {
        "exam": exam, "report": report, "wrong": ",".join(str(i) for i in wrong), "took": min(took, exam.minutes * 60),
        "answered": sum(1 for x in report["items"] if x["a"].get("choice") or (x["a"].get("text") or "").strip()),
    })


@work_required
@require_POST
def exam_save(request, pk):
    exam = get_object_or_404(PrepExam, pk=pk, owner=request.user)
    try:
        answers = json.loads(request.POST.get("answers") or "{}")
    except ValueError:
        return JsonResponse({"ok": False, "error": "answers"}, status=400)
    if not prep.save_answers(exam, answers):
        return JsonResponse({"ok": False, "error": "closed", "url": reverse("work:exam", args=[exam.pk])}, status=409)
    return JsonResponse({"ok": True})


# ── In and out ────────────────────────────────────────────────────────────
@work_required
def prep_import_view(request):
    """Paste (or upload) questions as Markdown or JSON; see them, then add them."""
    user = request.user
    key = "work_prep_import"
    ctx = {"example": prep.EXAMPLE, "topics": PrepTopic.objects.filter(owner=user)}
    if request.method == "POST":
        if request.POST.get("action") == "add":
            items = request.session.pop(key, None)
            if not items:
                messages.error(request, _("The preview has expired. Paste the questions again."))
                return redirect("work:prep_import")
            topic = PrepTopic.objects.filter(owner=user, pk=request.POST.get("topic") or 0).first()
            n = prep.add_many(user, items, topic=topic)
            messages.success(request, ngettext("%(n)s question added.", "%(n)s questions added.", n) % {"n": n})
            return redirect("work:questions")
        text = request.POST.get("text", "")
        f = request.FILES.get("file")
        if f:
            if f.size > 5 * 1024 * 1024:
                messages.error(request, _("That file is too big (over 5 MB)."))
                return redirect("work:prep_import")
            text = f.read().decode("utf-8-sig", errors="replace")
        text = text.strip()
        try:
            items = prep.parse_any(text)
        except (ValueError, TypeError, csv.Error):
            items = []
            messages.error(request, _("That JSON couldn't be read."))
        if items:
            request.session[key] = items[:2000]
            ctx.update({"items": items[:2000], "text": text,
                        "kinds": dict(QuestionKind.choices), "levels": dict(Difficulty.choices)})
        elif text:
            messages.error(request, _("No questions found. Start each one with “## ” — see the example."))
            ctx["text"] = text
    return render_work(request, "work/prep/import.html", ctx)


@work_required
def prep_sheet_view(request):
    """The questions and their answers on one page, to read through or print before the exam."""
    f = _filters(request.GET)
    qs = prep.filtered(request.user, f).order_by("topic__order", "topic__name", "difficulty", "pk")[:500]
    topic = PrepTopic.objects.filter(owner=request.user, pk=f["topic"]).first() if f["topic"].isdigit() else None
    return render_work(request, "work/prep/sheet.html", {"questions": qs, "topic": topic, "f": f, "query": request.GET.urlencode()})


@work_required
def prep_export_view(request):
    user = request.user
    f = _filters(request.GET)
    qs = prep.filtered(user, f).order_by("topic__order", "topic__name", "pk")
    stamp = timezone.localdate().isoformat()
    if request.GET.get("format") == "md":
        lines, topic = [], None
        for q in qs:
            if q.topic.name != topic:
                topic = q.topic.name
                lines += [f"# {topic}", ""]
            words = [q.get_difficulty_display().lower() if q.difficulty in Difficulty.values else "medium", q.kind]
            if q.language:
                words.append(q.language)
            first, *rest = q.prompt.split("\n")
            lines.append(f"## {first} {{{', '.join(words)}}}")
            lines += rest
            lines += [f"- [{'x' if o.get('correct') else ' '}] {o.get('text', '')}" for o in q.options or []]
            for head, body in (("Starter", f"```{q.language}\n{q.starter}\n```" if q.starter else ""),
                               ("Tests", f"```{q.language}\n{q.tests}\n```" if q.tests else ""),
                               ("Hints", "\n".join(f"- {h}" for h in q.hint_list)), ("Answer", q.answer),
                               ("Key points", "\n".join(f"- {p}" for p in q.points_list)), ("Why", q.explanation), ("Notes", q.notes)):
                if body.strip():
                    lines += [f"### {head}", body.strip()]
            lines.append("")
        response = HttpResponse("\n".join(lines), content_type="text/markdown; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="interview-prep-{stamp}.md"'
        return response
    response = HttpResponse(json.dumps(prep.export(user, qs), ensure_ascii=False, indent=1), content_type="application/json; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="interview-prep-{stamp}.json"'
    return response

