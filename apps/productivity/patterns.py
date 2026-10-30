"""Coding patterns, as NeetCode's roadmap lays them out: the problems solved (on LeetCode or anywhere) logged
under the pattern they use, how it went, and which patterns are weak or not started.

No tables of its own: each problem is a question in the bank (topic "Coding problems", a section for each
pattern), so it comes back by itself in spaced practice, and its link is in the question to open it again."""
from django.db.models import Max
from django.utils.translation import gettext_lazy as _

from . import cards, prep
from .models import Difficulty, PrepTopic, Question, QuestionKind

TOPIC = "Coding problems"
# (the section's name in the bank, the name shown)
PATTERNS = (
    ("Arrays & hashing", _("Arrays & hashing")), ("Two pointers", _("Two pointers")), ("Sliding window", _("Sliding window")),
    ("Stack", _("Stack")), ("Binary search", _("Binary search")), ("Linked list", _("Linked list")), ("Trees", _("Trees")),
    ("Tries", _("Tries")), ("Heap / priority queue", _("Heap / priority queue")), ("Backtracking", _("Backtracking")),
    ("Graphs", _("Graphs")), ("Dynamic programming", _("Dynamic programming")), ("Greedy", _("Greedy")), ("Intervals", _("Intervals")),
    ("Math & geometry", _("Math & geometry")), ("Bit manipulation", _("Bit manipulation")),
)
# how it went → the answer it counts as in spaced practice
OUTCOMES = (("alone", _("Solved alone"), cards.GOOD), ("hints", _("Needed hints"), cards.HARD), ("stuck", _("Couldn't solve it"), cards.AGAIN))


def topic_for(user, create=False):
    found = PrepTopic.objects.filter(owner=user, name=TOPIC).first()
    return found or (PrepTopic.objects.create(owner=user, name=TOPIC, code="CP") if create else None)


def log(user, title, url, pattern, difficulty, outcome, minutes=0):
    """A problem solved: added under its pattern, or — solved again — another attempt at the one there.
    Returns (question, is_new); (None, False) for a pattern or outcome that isn't one."""
    title = " ".join(title.split())[:200]
    rating = next((r for key, _label, r in OUTCOMES if key == outcome), None)
    if not title or rating is None or pattern not in dict(PATTERNS):
        return None, False
    url = url.strip()[:500] if url.strip().startswith(("http://", "https://")) else ""
    topic = topic_for(user, create=True)
    mine = Question.objects.filter(owner=user, topic=topic)
    q = (mine.filter(source=url).first() if url else None) or mine.filter(prompt__iexact=title).first() or mine.filter(prompt__istartswith=title + "\n").first()
    is_new = q is None
    if is_new:
        section = prep.section_named(topic, pattern)
        top = mine.filter(section=section).aggregate(m=Max("order"))["m"] or 0
        q = Question.objects.create(owner=user, topic=topic, section=section, order=top + 1, kind=QuestionKind.LONG, source=url,
                                    prompt=f"{title}\n\n{url}" if url else title,
                                    difficulty=difficulty if difficulty in Difficulty.values else Difficulty.MEDIUM)
    prep.answer(q, rating, seconds=max(0, minutes) * 60)
    return q, is_new


def roadmap(user, today):
    """Every pattern with its numbers: {"name", "label", "total", "mastered", "weak", "due", "pct", "section"}, and what to do next."""
    topic = topic_for(user)
    rows = []
    questions = list(Question.objects.filter(topic=topic).select_related("section")) if topic else []
    for name, label in PATTERNS:
        mine = [q for q in questions if q.section_id and q.section.name.lower() == name.lower()]
        solved = sum(1 for q in mine if q.status in ("learning", "mastered"))
        rows.append({"name": name, "label": label, "total": len(mine), "solved": solved, "mastered": sum(1 for q in mine if q.status == "mastered"),
                     "weak": sum(1 for q in mine if q.status == "weak"), "due": sum(1 for q in mine if q.due <= today),
                     "pct": round(100 * solved / len(mine)) if mine else 0, "section": mine[0].section_id if mine else None})
    labels = {name.lower(): label for name, label in PATTERNS}
    for q in questions:
        q.pattern = labels.get(q.section.name.lower(), q.section.name) if q.section_id else ""
    weak = max(rows, key=lambda r: r["weak"])
    next_up = weak if weak["weak"] else next((r for r in rows if not r["total"]), None)
    return {"rows": rows, "topic": topic, "next": next_up, "total": len(questions), "due": sum(r["due"] for r in rows),
            "started": sum(1 for r in rows if r["total"]), "recent": sorted(questions, key=lambda q: q.last_reviewed or q.created_at, reverse=True)[:10]}
