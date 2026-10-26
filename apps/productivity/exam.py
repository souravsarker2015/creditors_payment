"""Exam notes: questions and answers kept to revise before an exam. A plain
list per subject, grouped by chapter when the questions have one. This module
reads a pasted list into questions and writes a subject back out as text.

A pasted list can look like any of these — the last ones are what ChatGPT or
Claude usually write when asked for questions and answers:

    Q: What is photosynthesis?          "Q:" starts each question; the answer
    A: Plants making food from light.   ("A:" or not) runs until the next "Q:"

    Capital of France<TAB>Paris          two columns copied from a spreadsheet

    ## What is osmosis?                  Markdown headings: each heading is a
    Water moving through a membrane…     question, everything under it the answer
                                         (# headings above them become chapters)

    **1. What is diffusion?**            whole bold lines are the questions
    Particles spreading out…

    What is a cell?                      otherwise: blocks split by an empty line,
    The smallest unit of life.           the first line the question

Code blocks (```) are kept whole: an empty line or a "#" inside one never
splits a question.
"""
import re
from collections import Counter
from datetime import timedelta

from django.utils import timezone

MAX_QUESTION, MAX_ANSWER, MAX_CHAPTER, MAX_PASTE = 2000, 20000, 120, 500

B = r"(?:\*\*|__)?"                                     # bold around a label: **Q1:**
FENCE = re.compile(r"^\s{0,3}(```|~~~)")
HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
RULE = re.compile(r"^\s{0,3}([-*_])(?:\s*\1){2,}\s*$")   # --- between questions
Q_LINE = re.compile(r"^\s*(?:#{1,6}\s+)?" + B + r"\s*(?:Q|Ques|Question|প্রশ্ন)\s*-?\s*(?:\d+|[০-৯]+)?\s*[:.)\-–]\s*" + B + r"\s*", re.I)
A_LINE = re.compile(r"^\s*" + B + r"\s*(?:A|Ans|Answer|উত্তর)\s*(?:\d+|[০-৯]+)?\s*[:.)\-–]\s*" + B + r"\s*", re.I)
A_ALONE = re.compile(r"^\s*" + B + r"\s*(?:Answer|Ans|উত্তর)\s*" + B + r"\s*:?\s*" + B + r"\s*$", re.I)
NUMBER = re.compile(r"^\s*(?:\d+|[০-৯]+)\s*[.):]\s+")    # "1. ", "2) " in front of a question
BOLD_LINE = re.compile(r"^\s*(?:(?:\d+|[০-৯]+)\s*[.)]\s*)?(\*\*|__)(?!\s)(.+?)\1\s*:?\s*$")


def _scan(lines):
    """[(line, in_code)] — the ``` lines themselves count as code."""
    out, fence = [], None
    for line in lines:
        m = FENCE.match(line)
        if fence:
            out.append((line, True))
            if m and line.strip().startswith(fence):
                fence = None
        elif m:
            fence = m.group(1)
            out.append((line, True))
        else:
            out.append((line, False))
    return out


def _unbold(text):
    text = text.strip()
    m = re.fullmatch(r"(\*\*|__)(.+)\1:?", text)
    if m:
        text = m.group(2).strip()
    if text.count("**") % 2:                      # "What is X?**" left from "**Q1. What is X?**"
        text = text.replace("**", "")
    return text.strip()


def _question(text):
    text = text.strip()
    if Q_LINE.match(text):
        text = Q_LINE.sub("", text, count=1)
    text = NUMBER.sub("", _unbold(NUMBER.sub("", text)))
    return text.strip()[:MAX_QUESTION]


def _chapter(text):
    return _unbold(text).rstrip(":").strip()[:MAX_CHAPTER]


def _answer(rows):
    lines = [line for line, _code in rows]
    code = [c for _line, c in rows]
    blank = lambda i: not lines[i].strip() or (not code[i] and RULE.match(lines[i]))   # noqa: E731
    start, end = 0, len(lines)
    while start < end and blank(start):
        start += 1
    while end > start and blank(end - 1):
        end -= 1
    lines = lines[start:end]
    if lines and not code[start]:
        if A_ALONE.match(lines[0]):
            lines = lines[1:]
            while lines and not lines[0].strip():
                lines = lines[1:]
        elif A_LINE.match(lines[0]):
            lines[0] = A_LINE.sub("", lines[0], count=1)
    return "\n".join(lines).rstrip()[:MAX_ANSWER]


class _Notes(list):
    """Collects the questions as they're read: start one, add answer lines, finish it."""
    def __init__(self):
        super().__init__()
        self.cur, self.chapter = None, ""

    def start(self, question):
        self.finish()
        self.cur = (question, [], self.chapter)

    def add(self, row):
        if self.cur:
            self.cur[1].append(row)

    def finish(self):
        if self.cur:
            q, rows, chapter = self.cur
            q = _question(q)
            if q:
                self.append({"question": q, "answer": _answer(rows), "chapter": chapter})
        self.cur = None


def _next_filled(rows, i):
    for line, code in rows[i + 1:]:
        if line.strip():
            return line, code
    return "", False


def _marked(rows):
    """Q:/A: lists. A heading right before a Q: line names the chapter."""
    out = _Notes()
    for i, (line, code) in enumerate(rows):
        if not code and Q_LINE.match(line):
            out.start(line)
            continue
        h = None if code else HEADING.match(line)
        if h:
            nxt, nxt_code = _next_filled(rows, i)
            if not nxt_code and Q_LINE.match(nxt):
                out.finish()
                out.chapter = _chapter(h.group(2))
                continue
        out.add((line, code))
    out.finish()
    return out


def _headed(rows):
    """Markdown headings. The level that repeats (## mostly) holds the questions —
    unless its headings only hold other headings: then those are the questions.
    A heading above the questions' level names the chapter of the ones under it;
    deeper headings stay inside the answers."""
    heads = {i: (len(m.group(1)), m.group(2)) for i, (line, code) in enumerate(rows) if not code and (m := HEADING.match(line))}
    if not heads:
        return []
    counts = Counter(level for level, _text in heads.values())
    level = min((lv for lv, n in counts.items() if n >= 2), default=min(counts))

    def body(i):        # the rows under heading i, up to the next heading of its level or above
        out = []
        for j in range(i + 1, len(rows)):
            if j in heads and heads[j][0] <= heads[i][0]:
                break
            out.append(j)
        return out

    def holds_headings(i):
        first = next((j for j in body(i) if rows[j][0].strip()), None)
        return first in heads and heads[first][0] > heads[i][0]

    tops = [i for i, (lv, _t) in heads.items() if lv == level]
    if all(holds_headings(i) for i in tops):
        level = min(heads[j][0] for i in tops for j in body(i) if j in heads)
    out = _Notes()
    for i, row in enumerate(rows):
        if i in heads and heads[i][0] <= level:
            lv, text = heads[i]
            if lv == level:
                out.start(text)
            else:
                out.finish()
                out.chapter = _chapter(text)
            continue
        out.add(row)
    out.finish()
    return out


def _bolded(rows):
    """Whole bold lines as the questions — the ones ending in "?" when there are a few of those."""
    bold = [i for i, (line, code) in enumerate(rows) if not code and BOLD_LINE.match(line)]
    asks = [i for i in bold if _unbold(BOLD_LINE.match(rows[i][0]).group(2)).endswith(("?", "？"))]
    starts = set(asks if len(asks) >= 2 else bold)
    if len(starts) < 2:
        return []
    out = _Notes()
    for i, row in enumerate(rows):
        if i in starts:
            out.start(row[0])
        else:
            out.add(row)
    out.finish()
    return out


def _blocks(rows):
    out = _Notes()
    for line, code in rows + [("", False)]:
        if not line.strip() and not code:
            out.finish()
        elif out.cur is None:
            out.start(line)
        else:
            out.add((line, code))
    return out


def parse(text, chapter=""):
    """[{question, answer, chapter}, …] from pasted text — at most MAX_PASTE.
    `chapter` is given to the questions the text doesn't put in one."""
    lines = (text or "").replace("\r\n", "\n").replace("\r", "\n").replace("\u00a0", " ").split("\n")
    rows = _scan(lines)
    filled = [line for line in lines if line.strip()]
    if not filled:
        return []
    if not any(code for _line, code in rows) and all("\t" in line for line in filled):
        notes = []
        for line in filled:
            q, _tab, a = line.partition("\t")
            if _question(q):
                notes.append({"question": _question(q), "answer": a.strip()[:MAX_ANSWER], "chapter": ""})
    elif any(not code and Q_LINE.match(line) for line, code in rows):
        notes = _marked(rows)
    else:
        notes = _headed(rows) or _bolded(rows) or _blocks(rows)
    chapter = (chapter or "").strip()[:MAX_CHAPTER]
    for n in notes:
        n["chapter"] = n["chapter"] or chapter
    return list(notes)[:MAX_PASTE]


def same(text):
    """A question's text for spotting one that's already there: case, spaces and bold don't count."""
    return " ".join(re.sub(r"[*_`]", "", text).lower().split()).rstrip("?？ ")


def ordered(notes):
    """Each chapter's questions together, the chapters in the order their first question comes."""
    groups = {}
    for n in sorted(notes, key=lambda n: (n.order, n.pk or 0)):
        groups.setdefault(n.chapter, []).append(n)
    return [n for group in groups.values() for n in group]


def next_order(subject):
    from django.db.models import Max

    return (subject.notes.aggregate(m=Max("order"))["m"] or 0) + 1


def as_text(subject, notes):
    """The subject as a Q:/A: list, chapters as ## headings — reads back in with parse()."""
    out, chapter = [subject.name, ""], ""      # a plain line: a heading right before a Q: would read back as a chapter
    for n in ordered(notes):
        if n.chapter != chapter:
            chapter = n.chapter
            out += [f"## {chapter}", ""]
        out.append(f"Q: {n.question.strip()}")
        out.append(f"A: {n.answer.strip()}" if n.answer.strip() else "A:")
        out.append("")
    return "\n".join(out)


def as_json(note, number=None, today=None):
    return {"id": note.pk, "question": note.question, "answer": note.answer, "chapter": note.chapter, "starred": note.is_starred,
            "known": note.is_known, "misses": note.misses, "color": note.color, "number": number,
            "due": is_due(note, today), "dueOn": note.due_on.isoformat() if note.due_on else "", "interval": note.interval}


# ── Spaced repetition: a question you knew comes back later each time (1, 3, 7, 16, 35… days, as
#    Anki does); one you didn't, tomorrow. Before an exam, nothing is put off past the day before it. ──
STEPS = (1, 3, 7, 16, 35, 75, 150)


def schedule(note, knew, today=None, exam_date=None):
    """Sets note.interval and note.due_on after an answer (not saved)."""
    today = today or timezone.localdate()
    if not knew:
        note.interval, note.due_on = 0, today + timedelta(days=1)
        return note
    note.interval = next((s for s in STEPS if s > note.interval), STEPS[-1])
    note.due_on = today + timedelta(days=note.interval)
    if exam_date and today < exam_date - timedelta(days=1) and note.due_on >= exam_date:
        note.due_on = exam_date - timedelta(days=1)          # one last look the day before the exam
    return note


def is_due(note, today=None):
    """Known, and its day to come back has come. (Questions not known yet are "to learn" anyway.)"""
    return bool(note.is_known and note.due_on and note.due_on <= (today or timezone.localdate()))


# ── Pages of questions, from the database (a subject can hold thousands) ────
PAGE = 30
SHOWS = ("all", "unknown", "due", "missed", "starred")


def in_order(qs):
    """Chapter by chapter (chapters in the order their first question comes), then by place — what ordered() does, in SQL."""
    from django.db.models import Min, OuterRef, Subquery

    same = qs.model.objects.filter(subject=OuterRef("subject"), chapter=OuterRef("chapter")).values("chapter")
    first = same.annotate(m=Min("order")).values("m")
    first_pk = same.annotate(m=Min("pk")).values("m")          # questions with no place yet (0): the chapter's oldest decides
    return qs.annotate(chapter_first=Subquery(first[:1]), chapter_pk=Subquery(first_pk[:1])).order_by("chapter_first", "chapter_pk", "order", "pk")


def numbers(subject):
    """{note id: its number} — the place in the subject, the same everywhere."""
    return {pk: i for i, pk in enumerate(in_order(subject.notes.all()).values_list("pk", flat=True), 1)}


def filtered(subject, show="all", chapter=None, q=""):
    from django.db.models import Q

    qs = subject.notes.all()
    if show == "unknown":
        qs = qs.filter(is_known=False)
    elif show == "due":
        qs = qs.filter(is_known=True, due_on__lte=timezone.localdate())
    elif show == "missed":
        qs = qs.filter(misses__gt=0)
    elif show == "starred":
        qs = qs.filter(is_starred=True)
    if chapter is not None:
        qs = qs.filter(chapter=chapter)
    for word in (q or "").split()[:6]:
        qs = qs.filter(Q(question__icontains=word) | Q(answer__icontains=word) | Q(chapter__icontains=word))
    return qs


def counts(subject):
    from django.db.models import Count, Q

    c = subject.notes.aggregate(all=Count("pk"), unknown=Count("pk", filter=Q(is_known=False)),
                                due=Count("pk", filter=Q(is_known=True, due_on__lte=timezone.localdate())),
                                missed=Count("pk", filter=Q(misses__gt=0)), starred=Count("pk", filter=Q(is_starred=True)))
    return {"shows": c, "chapters": chapter_list(subject)}


def chapter_list(subject):
    """[{name, n, known}] in the subject's order."""
    from collections import OrderedDict

    out = OrderedDict()
    for chapter, known in in_order(subject.notes.all()).values_list("chapter", "is_known"):
        row = out.setdefault(chapter, {"name": chapter, "n": 0, "known": 0})
        row["n"] += 1
        row["known"] += 1 if known else 0
    return list(out.values())


def move(note, before_id=None):
    """Put a question just before another (or last) and into that one's chapter, renumbering the subject."""
    ids = list(in_order(note.subject.notes.all()).values_list("pk", flat=True))
    ids.remove(note.pk)
    if before_id and before_id in ids:
        ids.insert(ids.index(before_id), note.pk)
        neighbour = before_id
    else:
        ids.append(note.pk)
        neighbour = ids[-2] if len(ids) > 1 else None
    if neighbour:
        note.chapter = type(note).objects.filter(pk=neighbour).values_list("chapter", flat=True).first() or ""
    rows = {n.pk: n for n in note.subject.notes.all()}
    rows[note.pk].chapter = note.chapter
    for place, pk in enumerate(ids, 1):
        rows[pk].order = place
    type(note).objects.bulk_update(rows.values(), ["order", "chapter"])


def plain(text):
    """Markdown as one line of plain words, for a search result's snippet."""
    text = re.sub(r"```\w*|~~~\w*|!\[[^\]]*\]\([^)]*\)", " ", text or "")
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"(?m)^\s{0,3}(?:#{1,6}\s+|>\s?|[-*+]\s+|\d+[.)]\s+)", "", text)
    text = re.sub(r"[*_`|]|==|\\[()[\]]|\$\$?", "", text)
    return " ".join(text.split())
