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
from .models import Difficulty, Level, PrepExam, PrepSection, PrepTopic, Question, QuestionKind, WorkSettings
from .prep_packs import PACKS
from .views import render_work

FILTER_KEYS = ("topic", "section", "kind", "difficulty", "level", "status", "starred", "q", "company", "tag")


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
        "deleted": _("Question deleted"), "added": _("Question added"), "writeFirst": _("Write the question first."), "notSaved": _("Not saved — check your connection."),
        "dropSection": _("Delete this section? Its questions stay, outside any section."),
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
        "topics": PrepTopic.objects.filter(owner=user), "levels": Level.choices,
    })


# ── The question bank ─────────────────────────────────────────────────────
SORTS = {"": prep.SEQUENCE, "hard": ("-difficulty", "topic__name", "pk"), "weak": ("-lapses", "due", "pk"), "new": ("-created_at",)}


@work_required
def questions_view(request):
    user = request.user
    if request.method == "POST":
        return _bulk(request)
    f = _filters(request.GET)
    if f["q"] and prep.NUMBER.match(f["q"]):          # "PY-2.3": straight to that question
        topic = PrepTopic.objects.filter(owner=user, pk=f["topic"]).first() if f["topic"].isdigit() else None
        hit = prep.find_number(user, f["q"], topic)
        if hit:
            return redirect("work:question", pk=hit.pk)
    sort = request.GET.get("sort", "") if request.GET.get("sort", "") in SORTS else ""
    qs = prep.filtered(user, f).prefetch_related("tags")
    page = Paginator(qs.order_by(*SORTS[sort]), 50).get_page(request.GET.get("page"))
    page.object_list = prep.numbered(user, page.object_list)
    base = request.GET.copy()
    base.pop("page", None)
    from apps.accounts.views import _page_window

    return render_work(request, "work/prep/questions.html", {
        "page": page, "f": f, "filtered": any(f.values()), "topics": PrepTopic.objects.filter(owner=user), "sort": sort,
        "sections": PrepSection.objects.filter(owner=user, topic_id=f["topic"]) if f["topic"].isdigit() else [],
        "all_sections": PrepSection.objects.filter(owner=user).select_related("topic").order_by("topic__order", "topic__name", "order", "pk"),
        "levels": Level.choices[1:], "kinds": QuestionKind.choices, "difficulties": Difficulty.choices, "total": qs.count(),
        "query": base.urlencode(), "base_query_string": base.urlencode(), "pagination_window": _page_window(page),
    })


def _bulk(request):
    """Picked questions in the bank: move them, set their level or difficulty, or delete them."""
    user = request.user
    ids = [int(x) for x in request.POST.getlist("ids") if x.isdigit()]
    qs = Question.objects.filter(owner=user, pk__in=ids)
    action, n = request.POST.get("action"), qs.count()
    back = request.POST.get("next") or reverse("work:questions")
    if not back.startswith("/"):
        back = reverse("work:questions")
    if not n:
        messages.info(request, _("Pick some questions first."))
        return redirect(back)
    if action == "move":
        target = request.POST.get("to", "")             # "t12" a topic, "s34" a section
        section = PrepSection.objects.filter(owner=user, pk=target[1:] or 0).select_related("topic").first() if target.startswith("s") else None
        topic = section.topic if section else PrepTopic.objects.filter(owner=user, pk=target[1:] or 0).first() if target.startswith("t") else None
        if topic is None:
            messages.error(request, _("Pick where to move them."))
            return redirect(back)
        for q in qs.order_by(*prep.SEQUENCE):
            prep.move(q, topic, section)
        messages.success(request, ngettext("%(n)s question moved.", "%(n)s questions moved.", n) % {"n": n})
    elif action == "level" and request.POST.get("level", "") in Level.values:
        qs.update(level=request.POST["level"], updated_at=timezone.now())
        messages.success(request, ngettext("%(n)s question changed.", "%(n)s questions changed.", n) % {"n": n})
    elif action == "difficulty" and request.POST.get("difficulty", "").isdigit() and int(request.POST["difficulty"]) in Difficulty.values:
        qs.update(difficulty=int(request.POST["difficulty"]), updated_at=timezone.now())
        messages.success(request, ngettext("%(n)s question changed.", "%(n)s questions changed.", n) % {"n": n})
    elif action == "delete":
        for q in qs:
            trash(user, q, _("Question: %(title)s") % {"title": q.title[:80]}, reverse("work:questions"))
        messages.success(request, ngettext("%(n)s question deleted. You can bring it back from Recently deleted.",
                                           "%(n)s questions deleted. You can bring them back from Recently deleted.", n) % {"n": n})
    return redirect(back)


def _question_row(q, number=""):
    """What the contents page needs for one question."""
    return {"id": q.pk, "number": number, "title": q.title, "prompt": q.prompt, "answer": q.answer, "key_points": q.key_points,
            "kind": q.kind, "kindLabel": q.get_kind_display(), "difficulty": q.difficulty, "difficultyLabel": q.get_difficulty_display(),
            "level": q.level, "levelLabel": q.get_level_display() if q.level else "", "status": q.status, "statusLabel": str(q.status_label),
            "section": q.section_id or 0, "url": reverse("work:question", args=[q.pk]), "edit": reverse("work:question_edit", args=[q.pk])}


@work_required
def question_view(request, pk):
    q = get_object_or_404(Question.objects.select_related("topic", "section"), pk=pk, owner=request.user)
    q.number = prep.numbering(request.user, [q.topic_id]).get(q.pk, "")
    before, after = prep.neighbours(q)
    return render_work(request, "work/prep/question.html", {
        "q": q, "history": q.history.all()[:20], "prep_text": _texts(), "before": before, "after": after,
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
                   "section": request.GET.get("section") or None, "level": request.GET.get("level") or "",
                   "difficulty": Difficulty.MEDIUM}
    form = QuestionForm(request.POST or None, instance=q, owner=user, initial=initial)
    if request.method == "POST" and form.is_valid():
        saved = form.save()
        messages.success(request, _("Question saved."))
        if request.POST.get("then") == "another":
            return redirect(reverse("work:question_new") + f"?topic={saved.topic_id}&kind={saved.kind}&section={saved.section_id or ''}&level={saved.level}")
        return redirect("work:question", pk=saved.pk)
    return render_work(request, "work/prep/question_form.html", {"form": form, "q": q, "has_topics": PrepTopic.objects.filter(owner=user).exists()})


@work_required
def topic_view(request, pk):
    """A topic's contents: its sections and their numbered questions, in order — added to, edited,
    reordered and deleted right there. The topic's own details are edited here too."""
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
            return redirect("work:prep_topic", pk=t.pk)
    return render_work(request, "work/prep/topic.html", {
        "form": form, "t": t, "n": t.questions.count(), "contents": _contents(t), "prep_text": _texts(),
        "kinds": QuestionKind.choices, "difficulties": Difficulty.choices, "levels": Level.choices,
        "ready": next((r for r in prep.topic_rows(request.user) if r["t"].pk == t.pk), None),
    })


def _contents(t):
    labels = prep.numbering(t.owner, [t.pk])
    groups = {0: []}
    for q in t.questions.select_related("section").order_by(*prep.SEQUENCE):
        groups.setdefault(q.section_id or 0, []).append(_question_row(q, labels.get(q.pk, "")))
    return {"id": t.pk, "code": t.code, "api": reverse("work:api_prep_topic", args=[t.pk]), "new": reverse("work:question_new") + f"?topic={t.pk}",
            "sections": [{"id": 0, "name": "", "questions": groups[0]}] +
                        [{"id": s.pk, "name": s.name, "questions": groups.get(s.pk, [])} for s in t.sections.all()]}


@work_required
def contents_view(request):
    """Every topic's contents on one page — the index of the whole bank."""
    user = request.user
    labels = prep.numbering(user)
    topics = list(PrepTopic.objects.filter(owner=user).prefetch_related("sections"))
    groups = {}
    for q in Question.objects.filter(owner=user).only("pk", "prompt", "topic_id", "section_id", "difficulty", "level", "last_reviewed",
                                                       "last_rating", "interval").order_by(*prep.SEQUENCE):
        q.number = labels.get(q.pk, "")
        groups.setdefault((q.topic_id, q.section_id or 0), []).append(q)
    book = [{"t": t, "parts": [(None, groups.get((t.pk, 0), []))] + [(s, groups.get((t.pk, s.pk), [])) for s in t.sections.all()]} for t in topics]
    return render_work(request, "work/prep/contents.html", {"book": book, "total": len(labels)})


@work_required
@require_POST
def topic_api(request, pk):
    """The contents page's changes: order, sections, and questions added in place."""
    t = get_object_or_404(PrepTopic, pk=pk, owner=request.user)
    action, post = request.POST.get("action"), request.POST
    if action == "order":
        try:
            data = json.loads(post.get("order") or "{}")
            prep.reorder(t, [int(x) for x in data.get("sections", [])], {str(k): [int(x) for x in v] for k, v in data.get("questions", {}).items()})
        except (ValueError, TypeError, AttributeError):
            return JsonResponse({"ok": False, "error": "order"}, status=400)
    elif action == "section_add":
        name = (post.get("name") or "").strip()[:120]
        if not name:
            return JsonResponse({"ok": False, "error": _("Give the section a name.")}, status=400)
        s = PrepSection.objects.create(owner=request.user, topic=t, name=name, order=t.sections.count() + 1)
        return JsonResponse({"ok": True, "section": {"id": s.pk, "name": s.name, "questions": []}})
    elif action in ("section_rename", "section_delete"):
        s = get_object_or_404(PrepSection, pk=post.get("section") or 0, topic=t)
        if action == "section_delete":           # its questions stay, at the end of the questions outside any section
            for q in s.questions.order_by(*prep.SEQUENCE):
                prep.move(q, t, None)
            s.delete()
        else:
            s.name = (post.get("name") or "").strip()[:120] or s.name
            s.save(update_fields=["name"])
    elif action == "question_add":
        prompt = (post.get("prompt") or "").strip()
        if not prompt:
            return JsonResponse({"ok": False, "error": _("Write the question first.")}, status=400)
        section = PrepSection.objects.filter(topic=t, pk=post.get("section") or 0).first()
        q = Question.objects.create(owner=request.user, topic=t, section=section, order=prep.next_position(t, section), prompt=prompt[:20000],
                                    answer=(post.get("answer") or "")[:50000], key_points=(post.get("key_points") or "")[:5000],
                                    kind=post.get("kind") if post.get("kind") in QuestionKind.values else QuestionKind.SHORT,
                                    difficulty=int(post["difficulty"]) if (post.get("difficulty") or "").isdigit() and int(post["difficulty"]) in Difficulty.values else Difficulty.MEDIUM,
                                    level=post.get("level") if post.get("level") in Level.values else "")
        return JsonResponse({"ok": True, "question": _question_row(q)})
    else:
        return JsonResponse({"ok": False, "error": "action"}, status=400)
    return JsonResponse({"ok": True, "contents": _contents(t)})


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
        items = prep.practice_queue(user, f, count=g.get("count") or (prep.SESSION_MAX if g.get("order") == "sequence" else 20), order=g.get("order") or "smart")
        topic = PrepTopic.objects.filter(owner=user, pk=f["topic"]).first() if f["topic"].isdigit() else None
        title = topic.name if topic else _("Practice")
        if g.get("order") == "sequence":
            title = _("%(topic)s, in order") % {"topic": title}
    items = prep.numbered(user, items)
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
    if action == "update":                # edited in place on the contents page
        for key, limit in (("prompt", 20000), ("answer", 50000), ("key_points", 5000)):
            if key in request.POST:
                setattr(q, key, request.POST[key][:limit])
        if not q.prompt.strip():
            return JsonResponse({"ok": False, "error": _("Write the question first.")}, status=400)
        if request.POST.get("kind") in QuestionKind.values and not (request.POST["kind"] == QuestionKind.CHOICE and not q.options):
            q.kind = request.POST["kind"]
        if (request.POST.get("difficulty") or "").isdigit() and int(request.POST["difficulty"]) in Difficulty.values:
            q.difficulty = int(request.POST["difficulty"])
        if "level" in request.POST and request.POST["level"] in Level.values:
            q.level = request.POST["level"]
        q.save()
        if "section" in request.POST:
            prep.move(q, q.topic, PrepSection.objects.filter(topic=q.topic, pk=request.POST["section"] or 0).first())
        return JsonResponse({"ok": True, "question": _question_row(q)})
    if action == "delete":
        item = trash(request.user, q, _("Question: %(title)s") % {"title": q.title[:80]}, reverse("work:questions"))
        return JsonResponse({"ok": True, "undo": reverse("trash_restore", args=[item.pk])})
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
    if not questions and not exam.finished_at:      # every question was deleted since: nothing to sit
        messages.warning(request, _("“%(title)s” has no questions left — they were deleted — so it can't be taken. You can delete it from the list.") % {"title": exam.title})
        return redirect("work:prep")
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
    qs = prep.numbered(request.user, prep.filtered(request.user, f).order_by(*prep.SEQUENCE)[:500])
    topic = PrepTopic.objects.filter(owner=request.user, pk=f["topic"]).first() if f["topic"].isdigit() else None
    return render_work(request, "work/prep/sheet.html", {"questions": qs, "topic": topic, "f": f, "query": request.GET.urlencode()})


@work_required
def prep_export_view(request):
    user = request.user
    f = _filters(request.GET)
    qs = prep.filtered(user, f).order_by(*prep.SEQUENCE)
    stamp = timezone.localdate().isoformat()
    if request.GET.get("format") == "md":
        lines, head = [], None
        for q in qs.order_by(*prep.SEQUENCE):
            here = q.topic.name + (f" / {q.section.name}" if q.section_id else "")
            if here != head:
                head = here
                lines += [f"# {here}", ""]
            words = [{1: "easy", 2: "medium", 3: "hard"}.get(q.difficulty, "medium"), q.kind]      # English words: they import back in any language
            if q.level:
                words.append(q.level)
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

