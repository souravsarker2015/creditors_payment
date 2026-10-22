"""Interview prep: a bank of questions to practise and be tested on.

Every answer — in practice or in a mock exam — moves the question's next
review with the same spaced repetition as flashcards (cards.next_state):
what you got wrong comes back tomorrow, what you know waits weeks. A question
reviewed three weeks apart or more counts as mastered.

Multiple choice is marked by the app. Short, coding and written answers are
checked by you against the model answer; ticking the key points you covered
suggests the mark.
"""
import json
import random
import re
from collections import Counter, defaultdict
from datetime import timedelta

from django.db import transaction
from django.db.models import Count, Q
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _

from . import cards
from .models import Difficulty, PrepAttempt, PrepExam, PrepTopic, Question, QuestionKind, WorkSettings

AGAIN, HARD, GOOD, EASY = cards.RATINGS
SESSION_MAX = 100
EXAM_MAX = 100


# ── Answering ─────────────────────────────────────────────────────────────
def chosen_right(question, chosen):
    """A multiple-choice answer is right when exactly the right choices are picked."""
    right = {i for i, o in enumerate(question.options or []) if o.get("correct")}
    return bool(right) and set(chosen or []) == right


def rating_for(score):
    """The suggested rating for a mark: all the key points → Good, most → Hard, few → Again."""
    if score >= 0.999:
        return GOOD
    if score >= 0.6:
        return HARD
    return AGAIN


def answer(question, rating, *, score=None, seconds=0, response=None, exam=None, now=None):
    """Records an answer: the question's next review moves and the numbers update."""
    if rating not in cards.RATINGS:
        raise ValueError("rating")
    now = now or timezone.now()
    interval, ease, reps, lapses = cards.next_state(question, rating)
    question.interval, question.ease, question.reps, question.lapses = interval, ease, reps, lapses
    question.due = timezone.localdate(now) + timedelta(days=interval)
    question.last_reviewed, question.last_rating = now, rating
    question.attempts += 1
    if rating >= GOOD:
        question.right += 1
    question.save(update_fields=["interval", "ease", "reps", "lapses", "due", "last_reviewed", "last_rating", "attempts", "right", "updated_at"])
    if score is None:
        score = {AGAIN: 0, HARD: 0.5, GOOD: 1, EASY: 1}[rating]
    PrepAttempt.objects.create(owner=question.owner, question=question, exam=exam, rating=rating, score=score,
                               seconds=max(0, min(int(seconds or 0), 6 * 3600)), response=response or {}, created_at=now)
    return question


def previews(question):
    """What each rating would do: {1: "now", 3: "4 days"…}."""
    return cards.previews(question)


# ── What to practise ──────────────────────────────────────────────────────
def _day_start(today):
    return cards._day_start(today)


def new_left(user, today=None):
    today = today or timezone.localdate()
    per_day = WorkSettings.for_user(user).prep_new_per_day
    start = _day_start(today)
    seen = (Question.objects.filter(owner=user, history__created_at__gte=start)          # first seen today
            .exclude(history__created_at__lt=start).distinct().count())
    return max(per_day - seen, 0)


def filtered(user, f):
    """The person's questions narrowed by a filter dict: topic, kind, difficulty, status, starred, q, company, tag."""
    qs = Question.objects.filter(owner=user).select_related("topic")
    if str(f.get("topic", "")).isdigit():
        qs = qs.filter(topic_id=int(f["topic"]))
    if f.get("kind") in QuestionKind.values:
        qs = qs.filter(kind=f["kind"])
    if str(f.get("difficulty", "")).isdigit():
        qs = qs.filter(difficulty=int(f["difficulty"]))
    if f.get("starred"):
        qs = qs.filter(is_starred=True)
    if f.get("q"):
        q = f["q"]
        qs = qs.filter(Q(prompt__icontains=q) | Q(answer__icontains=q) | Q(companies__icontains=q) | Q(notes__icontains=q))
    if f.get("company"):
        qs = qs.filter(companies__icontains=f["company"])
    if f.get("tag"):
        qs = qs.filter(tags__name=f["tag"].lower())
    status = f.get("status")
    if status == "new":
        qs = qs.filter(last_reviewed__isnull=True)
    elif status == "weak":
        qs = qs.filter(last_rating=AGAIN)
    elif status == "mastered":
        qs = qs.filter(interval__gte=Question.MASTERED).exclude(last_rating=AGAIN)
    elif status == "learning":
        qs = qs.filter(last_reviewed__isnull=False, interval__lt=Question.MASTERED).exclude(last_rating=AGAIN)
    elif status == "due":
        qs = qs.filter(last_reviewed__isnull=False, due__lte=timezone.localdate())
    return qs.distinct()


def today_queue(user, today=None, topic=None):
    """Today's practice: what's due (most overdue first), then a few new ones."""
    today = today or timezone.localdate()
    qs = Question.objects.filter(owner=user).select_related("topic")
    if topic:
        qs = qs.filter(topic=topic)
    due = list(qs.filter(last_reviewed__isnull=False, due__lte=today).order_by("due", "-lapses")[:SESSION_MAX])
    fresh = list(qs.filter(last_reviewed__isnull=True).order_by("topic__order", "topic__name", "difficulty", "pk")[:min(new_left(user, today), SESSION_MAX - len(due))])
    return due + fresh


def practice_queue(user, f, count=20, order="smart"):
    """A practice set from a filter: weakest and most overdue first ("smart"), or shuffled."""
    items = list(filtered(user, f)[:1000])
    if order == "random":
        random.shuffle(items)
    else:
        today = timezone.localdate()

        def need(q):        # lower comes first: wrong last time, then due, then new, then the rest by when they're due
            if q.last_rating == AGAIN:
                return (0, q.due)
            if q.last_reviewed and q.due <= today:
                return (1, q.due)
            if q.last_reviewed is None:
                return (2, today)
            return (3, q.due)
        items.sort(key=need)
    return items[:max(1, min(int(count or 20), SESSION_MAX))]


def as_json(q, *, for_exam=False):
    """What the practice and exam pages need for one question (no right answers in an exam)."""
    data = {
        "id": q.pk, "topic": q.topic.name, "color": q.topic.color, "kind": q.kind, "kindLabel": q.get_kind_display(),
        "difficulty": q.difficulty, "difficultyLabel": q.get_difficulty_display(), "prompt": q.prompt, "language": q.language,
        "starter": q.starter, "options": [o.get("text", "") for o in q.options or []],
        "multi": sum(1 for o in q.options or [] if o.get("correct")) > 1, "status": q.status, "starred": q.is_starred,
        "url": reverse("work:question", args=[q.pk]), "edit": reverse("work:question_edit", args=[q.pk]),
    }
    if not for_exam:
        data.update({"answer": q.answer, "explanation": q.explanation, "points": q.points_list,
                     "correct": [i for i, o in enumerate(q.options or []) if o.get("correct")], "hints": previews(q),
                     "companies": q.company_list})
    return data


# ── How ready am I ───────────────────────────────────────────────────────
def topic_rows(user, today=None):
    """Each topic with its counts, mastery and accuracy."""
    today = today or timezone.localdate()
    rows = []
    for t in PrepTopic.objects.filter(owner=user).annotate(
            total=Count("questions"),
            new=Count("questions", filter=Q(questions__last_reviewed__isnull=True)),
            weak=Count("questions", filter=Q(questions__last_rating=AGAIN)),
            mastered=Count("questions", filter=Q(questions__interval__gte=Question.MASTERED) & ~Q(questions__last_rating=AGAIN)),
            due=Count("questions", filter=Q(questions__last_reviewed__isnull=False, questions__due__lte=today))):
        learning = t.total - t.new - t.weak - t.mastered
        rows.append({"t": t, "total": t.total, "new": t.new, "weak": t.weak, "mastered": t.mastered, "learning": learning, "due": t.due,
                     "ready": readiness(t.total, t.mastered, learning, t.weak)})
    return rows


def readiness(total, mastered, learning, weak):
    """0–100: mastered counts in full, learning half, weak a little, new nothing."""
    if not total:
        return 0
    return round(100 * (mastered + 0.5 * learning + 0.15 * weak) / total)


def overview(user, today=None):
    """The numbers for the Interview prep page."""
    today = today or timezone.localdate()
    rows = topic_rows(user, today)
    total = sum(r["total"] for r in rows)
    mastered, learning, weak = (sum(r[k] for r in rows) for k in ("mastered", "learning", "weak"))
    since = today - timedelta(days=13)
    by_day = Counter(timezone.localtime(a).date() for a in PrepAttempt.objects.filter(owner=user, created_at__gte=_day_start(since))
                     .values_list("created_at", flat=True))
    days = [{"date": since + timedelta(days=i), "n": by_day.get(since + timedelta(days=i), 0)} for i in range(14)]
    top = max([d["n"] for d in days] + [1])
    for d in days:
        d["pct"] = round(100 * d["n"] / top)
    week = PrepAttempt.objects.filter(owner=user, created_at__gte=_day_start(today - timedelta(days=6)))
    week_n = week.count()
    week_right = week.filter(rating__gte=GOOD).count()
    return {
        "rows": rows, "total": total, "mastered": mastered, "learning": learning, "weak": weak, "new": sum(r["new"] for r in rows),
        "ready": readiness(total, mastered, learning, weak), "due": sum(r["due"] for r in rows),
        "new_today": min(new_left(user, today), sum(r["new"] for r in rows)), "days": days, "streak": streak(user, today),
        "week_n": week_n, "week_acc": round(100 * week_right / week_n) if week_n else None,
        "weakest": list(Question.objects.filter(owner=user, attempts__gt=0).select_related("topic")
                        .order_by("last_rating", "-lapses", "right", "-attempts")[:6]) if total else [],
    }


def streak(user, today=None):
    """Days in a row (to today, or yesterday) with at least one answer."""
    today = today or timezone.localdate()
    days = {timezone.localtime(a).date() for a in PrepAttempt.objects.filter(owner=user, created_at__gte=_day_start(today - timedelta(days=400)))
            .values_list("created_at", flat=True)}
    day = today if today in days else today - timedelta(days=1)
    n = 0
    while day in days:
        n += 1
        day -= timedelta(days=1)
    return n


# ── Mock exams ────────────────────────────────────────────────────────────
def new_exam(user, f, count=20, minutes=30, title=""):
    """A timed exam from a filter: a mix weighted towards what you don't know yet."""
    pool = list(filtered(user, f)[:2000])
    if not pool:
        return None
    random.shuffle(pool)
    pool.sort(key=lambda q: 0 if q.status in ("weak", "new") else 1 if q.status == "learning" else 2)
    picked = pool[:max(1, min(int(count or 20), EXAM_MAX))]
    random.shuffle(picked)
    topics = sorted({q.topic.name for q in picked})
    name = title.strip() or (_("Mock exam: %(topics)s") % {"topics": ", ".join(topics[:3]) + ("…" if len(topics) > 3 else "")})
    return PrepExam.objects.create(owner=user, title=name[:120], question_ids=[q.pk for q in picked], minutes=max(1, min(int(minutes or 30), 600)))


def exam_questions(exam):
    found = Question.objects.filter(owner=exam.owner, pk__in=exam.question_ids).select_related("topic").in_bulk()
    return [found[i] for i in exam.question_ids if i in found]


def save_answers(exam, answers):
    """Keeps the answers given so far (autosave); only while the exam is open."""
    if exam.finished_at:
        return False
    ids = {str(i) for i in exam.question_ids}
    clean = {}
    for key, a in (answers or {}).items():
        if str(key) in ids and isinstance(a, dict):
            clean[str(key)] = {"choice": [int(c) for c in a.get("choice") or [] if str(c).isdigit()][:20],
                               "text": str(a.get("text") or "")[:20000], "flag": bool(a.get("flag")),
                               "seconds": max(0, min(int(a.get("seconds") or 0), 36000))}
    exam.answers = clean
    exam.save(update_fields=["answers"])
    return True


@transaction.atomic
def finish(exam, answers=None, now=None):
    """Hands the exam in: multiple choice is marked now; the rest wait for you to mark them."""
    if exam.finished_at:
        return exam
    if answers is not None:
        save_answers(exam, answers)
    exam.finished_at = now or timezone.now()
    marks = {}
    for q in exam_questions(exam):
        a = exam.answers.get(str(q.pk)) or {}
        if q.kind == QuestionKind.CHOICE:
            marks[str(q.pk)] = 1.0 if chosen_right(q, a.get("choice")) else 0.0
        elif not (a.get("text") or "").strip():
            marks[str(q.pk)] = 0.0         # left empty: nothing to mark
    exam.marks = marks
    exam.save(update_fields=["finished_at", "marks", "answers"])
    _settle(exam)
    return exam


def mark(exam, marks):
    """Your marks for the written answers ({id: 0, 0.5 or 1}); once all are in, the exam is scored."""
    if not exam.finished_at or exam.graded_at:
        return exam
    ids = {str(i) for i in exam.question_ids}
    for key, value in (marks or {}).items():
        try:
            v = float(value)
        except (TypeError, ValueError):
            continue
        if str(key) in ids and 0 <= v <= 1:
            exam.marks[str(key)] = v
    exam.save(update_fields=["marks"])
    _settle(exam)
    return exam


def _settle(exam):
    """When every question has a mark: the score, and each answer goes into the questions' schedules."""
    if exam.graded_at or any(str(i) not in exam.marks for i in exam.question_ids):
        return
    now = timezone.now()
    for q in exam_questions(exam):
        a = exam.answers.get(str(q.pk)) or {}
        m = exam.marks[str(q.pk)]
        answer(q, GOOD if m >= 0.999 else HARD if m >= 0.5 else AGAIN, score=m, seconds=a.get("seconds") or 0,
               response={"choice": a.get("choice") or [], "text": (a.get("text") or "")[:4000]}, exam=exam, now=now)
    exam.score = round(100 * sum(exam.marks.values()) / len(exam.question_ids), 1) if exam.question_ids else 0
    exam.graded_at = now
    exam.save(update_fields=["score", "graded_at"])


def exam_report(exam):
    """Per topic: questions, points scored; and the list in order with your answer next to the model one."""
    items, topics = [], defaultdict(lambda: [0, 0.0])
    for i, q in enumerate(exam_questions(exam), 1):
        a = exam.answers.get(str(q.pk)) or {}
        m = exam.marks.get(str(q.pk))
        items.append({"n": i, "q": q, "a": a, "mark": m, "chosen": set(a.get("choice") or []),
                      "correct": {j for j, o in enumerate(q.options or []) if o.get("correct")}})
        topics[q.topic.name][0] += 1
        topics[q.topic.name][1] += m or 0
    by_topic = [{"name": k, "n": n, "got": round(g, 1), "pct": round(100 * g / n) if n else 0} for k, (n, g) in sorted(topics.items())]
    return {"items": items, "by_topic": by_topic, "to_mark": [x for x in items if x["mark"] is None]}


# ── Import / export ───────────────────────────────────────────────────────
KIND_WORDS = {"choice": QuestionKind.CHOICE, "mcq": QuestionKind.CHOICE, "short": QuestionKind.SHORT, "code": QuestionKind.CODE,
              "coding": QuestionKind.CODE, "long": QuestionKind.LONG, "design": QuestionKind.LONG, "essay": QuestionKind.LONG,
              "behavioral": QuestionKind.LONG, "behavioural": QuestionKind.LONG}
LEVEL_WORDS = {"easy": Difficulty.EASY, "medium": Difficulty.MEDIUM, "hard": Difficulty.HARD}
LANGS = {"python", "javascript", "typescript", "java", "go", "c", "cpp", "c++", "csharp", "c#", "rust", "kotlin", "swift", "ruby", "php", "sql", "bash", "shell"}
SECTION = re.compile(r"^###\s*(answer|solution|key points|why|explanation|starter|starting code|notes)\s*:?\s*$", re.I)
OPTION = re.compile(r"^\s*[-*]\s*\[( |x|X)\]\s+(.+)$")
HEAD = re.compile(r"^##\s*(?:Q:\s*)?(.+?)\s*(?:\{([^}]*)\})?\s*$")

EXAMPLE = """# Python
## What does `is` compare, and what does `==` compare? {easy, choice}
- [ ] Both compare values
- [x] `is` compares identity, `==` compares values
- [ ] `is` compares types
### Why
`a is b` is true only for the same object; `==` calls `__eq__`.

## Explain how a dict lookup works. {medium, long}
### Answer
A hash table: `hash(key)` picks a slot; collisions are probed; average O(1).
### Key points
- hash() of the key
- open addressing / probing
- average O(1), worst O(n)
- keys must be hashable (immutable)

## Reverse a linked list. {medium, code python}
### Starter
```python
def reverse(head): ...
```
### Solution
```python
def reverse(head):
    prev = None
    while head:
        head.next, prev, head = prev, head, head.next
    return prev
```
"""


def parse_markdown(text, default_topic=""):
    """Questions from the Markdown format shown on the import page:
    "# Topic", then "## Question {easy, choice}", "- [x] options", "### Answer", "### Key points", "### Why", "### Starter"."""
    out, topic, cur, section = [], default_topic, None, "prompt"

    def close():
        if cur and cur["prompt"].strip():
            for k in ("prompt", "answer", "explanation", "starter", "notes"):
                cur[k] = cur[k].strip()
            cur["key_points"] = "\n".join(ln.strip(" -*•\t") for ln in cur["key_points"].splitlines() if ln.strip(" -*•\t"))
            if cur["options"] and cur["kind"] == QuestionKind.SHORT and not cur["kind_set"]:
                cur["kind"] = QuestionKind.CHOICE
            cur.pop("kind_set")
            out.append(cur)

    for line in (text or "").replace("\r\n", "\n").split("\n"):
        if line.startswith("# ") and not line.startswith("## "):
            close()
            cur, topic = None, line[2:].strip()[:80]
            continue
        m = HEAD.match(line) if line.startswith("##") and not line.startswith("###") else None
        if m:
            close()
            words = [w.strip().lower() for w in re.split(r"[,\s]+", m.group(2) or "") if w.strip()]
            kind = next((KIND_WORDS[w] for w in words if w in KIND_WORDS), QuestionKind.SHORT)
            lang = next((w.replace("c++", "cpp").replace("c#", "csharp") for w in words if w in LANGS), "")
            cur = {"topic": topic or _("General"), "prompt": m.group(1).strip() + "\n", "answer": "", "key_points": "", "explanation": "",
                   "starter": "", "notes": "", "options": [], "language": lang, "kind": QuestionKind.CODE if lang and kind == QuestionKind.SHORT else kind,
                   "kind_set": any(w in KIND_WORDS for w in words) or bool(lang),
                   "difficulty": next((LEVEL_WORDS[w] for w in words if w in LEVEL_WORDS), Difficulty.MEDIUM)}
            section = "prompt"
            continue
        if cur is None:
            continue
        s = SECTION.match(line)
        if s:
            word = s.group(1).lower()
            section = {"answer": "answer", "solution": "answer", "key points": "key_points", "why": "explanation", "explanation": "explanation",
                       "starter": "starter", "starting code": "starter", "notes": "notes"}[word]
            continue
        o = OPTION.match(line)
        if o and section == "prompt":
            cur["options"].append({"text": o.group(2).strip()[:500], "correct": o.group(1).lower() == "x"})
            continue
        cur[section] += line + "\n"
    close()
    for q in out:
        if q["kind"] == QuestionKind.CODE and q["starter"].startswith("```"):
            q["starter"] = re.sub(r"^```\w*\n|\n?```$", "", q["starter"]).strip()
    return out


def parse_json(text):
    data = json.loads(text)
    items = data.get("questions") if isinstance(data, dict) else data
    out = []
    for x in items or []:
        if not isinstance(x, dict) or not str(x.get("prompt") or x.get("question") or "").strip():
            continue
        kind = x.get("kind") if x.get("kind") in QuestionKind.values else KIND_WORDS.get(str(x.get("type", "")).lower(), QuestionKind.SHORT)
        diff = x.get("difficulty")
        diff = diff if diff in Difficulty.values else LEVEL_WORDS.get(str(diff).lower(), Difficulty.MEDIUM)
        opts = [{"text": str(o.get("text", ""))[:500], "correct": bool(o.get("correct"))} for o in x.get("options") or [] if isinstance(o, dict)]
        points = x.get("key_points") or ""
        out.append({"topic": str(x.get("topic") or _("General"))[:80], "prompt": str(x.get("prompt") or x.get("question")), "answer": str(x.get("answer") or ""),
                    "key_points": "\n".join(points) if isinstance(points, list) else str(points), "explanation": str(x.get("explanation") or ""),
                    "starter": str(x.get("starter") or ""), "notes": str(x.get("notes") or ""), "options": opts, "language": str(x.get("language") or "")[:20],
                    "kind": QuestionKind.CHOICE if opts and kind == QuestionKind.SHORT else kind, "difficulty": diff,
                    "companies": str(x.get("companies") or "")[:200], "source": str(x.get("source") or "")[:500]})
    return out


@transaction.atomic
def add_many(user, items, topic=None):
    """Saves parsed questions; topics are found by name (or made). `topic` overrides theirs."""
    topics, n = {}, 0
    for x in items[:2000]:
        t = topic
        if t is None:
            name = (x.get("topic") or _("General")).strip()[:80]
            key = name.lower()
            if key not in topics:
                topics[key] = (PrepTopic.objects.filter(owner=user, name__iexact=name).first()
                               or PrepTopic.objects.create(owner=user, name=name, order=PrepTopic.objects.filter(owner=user).count()))
            t = topics[key]
        source = x.get("source") or ""
        Question.objects.create(owner=user, topic=t, kind=x.get("kind") or QuestionKind.SHORT, difficulty=x.get("difficulty") or Difficulty.MEDIUM,
                                prompt=x["prompt"][:20000], answer=(x.get("answer") or "")[:50000], key_points=(x.get("key_points") or "")[:5000],
                                options=x.get("options") or [], explanation=(x.get("explanation") or "")[:20000], language=(x.get("language") or "")[:20],
                                starter=(x.get("starter") or "")[:20000], notes=(x.get("notes") or "")[:20000],
                                companies=(x.get("companies") or "")[:200], source=source if source.startswith(("http://", "https://")) else "")
        n += 1
    return n


def export(user, qs=None):
    """The bank as JSON (it imports back here, or into another account)."""
    qs = qs if qs is not None else Question.objects.filter(owner=user).select_related("topic")
    return {"format": "fintrack-prep/1", "questions": [{
        "topic": q.topic.name, "kind": q.kind, "difficulty": q.difficulty, "prompt": q.prompt, "answer": q.answer,
        "key_points": q.points_list, "options": q.options, "explanation": q.explanation, "language": q.language, "starter": q.starter,
        "companies": q.companies, "source": q.source, "notes": q.notes} for q in qs]}


def install_pack(user, key):
    """Adds a starter pack's questions (prep_packs.PACKS) under its topic; returns how many were added."""
    from .prep_packs import PACKS

    pack = PACKS.get(key)
    if not pack:
        return 0
    topic = PrepTopic.objects.filter(owner=user, name__iexact=pack["name"]).first()
    have = set(Question.objects.filter(owner=user, topic=topic).values_list("prompt", flat=True)) if topic else set()
    if topic is None:
        topic = PrepTopic.objects.create(owner=user, name=pack["name"], color=pack.get("color", "blue"), description=pack.get("about", "")[:200],
                                         order=PrepTopic.objects.filter(owner=user).count())
    fresh = []
    for x in pack["questions"]:
        if x["prompt"] in have:
            continue
        options = [dict(o) for o in x.get("options") or []]
        if options and not x.get("ordered"):
            random.shuffle(options)       # the packs list the right choice first
        fresh.append(dict(x, topic=pack["name"], options=options))
    return add_many(user, fresh, topic=topic)
