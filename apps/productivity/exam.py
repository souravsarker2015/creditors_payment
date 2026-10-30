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

    1. What is a cell?                   a numbered list, with or without answers
    2. What is a tissue?

    What is a cell?                      otherwise: blocks split by an empty line,
    The smallest unit of life.           the first line the question

    Which is prime?                      a multiple-choice question: the choices stay
    a) 4   b) 7   (one a line)           with the question, the answer is what's
    Answer: b                            under them

A .csv file works too (two columns, or Question / Answer / Chapter headers), and
what Anki and Quizlet export. Code blocks (```) are kept whole: an empty line or
a "#" inside one never splits a question.
"""
import csv
import io
import re
from collections import Counter
from datetime import timedelta

from django.utils import timezone

MAX_QUESTION, MAX_ANSWER, MAX_CHAPTER, MAX_PASTE = 2000, 20000, 120, 500

B = r"(?:\*\*|__)?"                                     # bold around a label: **Q1:**
FENCE = re.compile(r"^\s{0,3}(?:(?:A|Ans|Answer|উত্তর)\s*:\s*)?(```|~~~)", re.I)    # "A: ```python" opens one too
HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
RULE = re.compile(r"^\s{0,3}([-*_])(?:\s*\1){2,}\s*$")   # --- between questions
# After a label: a colon, or . ) - with a number before it or a space after it — so "Q-learning", "Q.E.D." and
# "A-star" are words, not labels.
END = r"(?:[:：]|(?<=[\d০-৯])\s*[.)\-–—]|\s*[.)\-–—](?=[\s*_]|$))"
Q_LINE = re.compile(r"^\s*(?:#{1,6}\s+)?" + B + r"\s*(?:Q\.\s*(?:\d+|[০-৯]+)[.):]?(?=\s)|(?:Q|Ques|Question|প্রশ্ন)\s*-?\s*(?:\d+|[০-৯]+)?\s*" + END + r")\s*" + B + r"\s*", re.I)
A_LINE = re.compile(r"^\s*" + B + r"\s*(?:A|Ans|Answer|উত্তর)\s*(?:\d+|[০-৯]+)?\s*" + END + r"\s*" + B + r"\s*", re.I)
A_LABEL = re.compile(r"^\s*" + B + r"\s*(?:A|Ans|Answer|উত্তর)\s*(?:\d+|[০-৯]+)?\s*" + B + r"\s*[:：]", re.I)
A_ALONE = re.compile(r"^\s*" + B + r"\s*(?:Answer|Ans|উত্তর)\s*" + B + r"\s*:?\s*" + B + r"\s*$", re.I)
NUMBER = re.compile(r"^\s*(\d+|[০-৯]+)\s*[.):]\s+")    # "1. ", "2) " in front of a question
CHOICE = re.compile(r"^\s*\(?[a-fA-Fক-ঘ]\s*[.)]\s+\S")   # a) … B. … (ক) … — the choices of a multiple-choice question
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
    if lines and not code[start] and A_ALONE.match(lines[0]):
        lines = lines[1:]
        while lines and not lines[0].strip():
            lines = lines[1:]
    elif lines and A_LINE.match(lines[0]) and not _listed(lines):
        lines[0] = A_LINE.sub("", lines[0], count=1)
    return "\n".join(lines).rstrip()[:MAX_ANSWER]


def _listed(lines):
    """A list ("a) … b) …"): its first "a)" is a choice, not the label of an answer."""
    filled = [line for line in lines if line.strip()]
    return len(filled) > 1 and all(CHOICE.match(line) for line in filled[:2])


def _lift(rows):
    """(the lines that belong to the question, the rows left for the answer): a multiple-choice question's
    choices, when something follows them, and the rest of a question that runs on until its "Answer:" label."""
    filled = [i for i, (line, code) in enumerate(rows) if line.strip()]
    if not filled or rows[filled[0]][1]:
        return [], rows
    choices = 0
    for i in filled:
        if rows[i][1] or not CHOICE.match(rows[i][0]):
            break
        choices += 1
    if choices >= 2:
        if choices == len(filled):               # nothing under them: they're the answer, a list
            return [], rows
        return [rows[i][0].strip() for i in filled[:choices]], rows[filled[choices - 1] + 1:]
    if A_LABEL.match(rows[filled[0]][0]) or A_ALONE.match(rows[filled[0]][0]):
        return [], rows
    for k, i in enumerate(filled[1:5], 1):
        if i != filled[k - 1] + 1 or rows[i][1]:  # an empty line first: this is the answer, it just has no label
            break
        if A_LABEL.match(rows[i][0]) or A_ALONE.match(rows[i][0]):
            return [rows[j][0].strip() for j in filled[:k]], rows[i:]
    return [], rows


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
            more, rows = _lift(rows)
            q = _question(q)
            if q:
                self.append({"question": "\n".join([q, *more])[:MAX_QUESTION], "answer": _answer(rows), "chapter": chapter})
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


def _numbered(rows):
    """Every number, 1, 2, 3… in order, starts a question (a list of questions needs no answers under them).
    Numbers out of order: they're lists inside the answers."""
    starts, expected = [], 1
    for i, (line, code) in enumerate(rows):
        m = None if code else NUMBER.match(line)
        if m:
            if int(m.group(1)) != expected:
                return []
            starts.append(i)
            expected += 1
    if len(starts) < 2 or any(line.strip() for line, _code in rows[:starts[0]]):
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


QUESTION_HEADS, ANSWER_HEADS, CHAPTER_HEADS = ("question", "q", "front", "term", "প্রশ্ন"), ("answer", "a", "back", "definition", "উত্তর"), ("chapter", "topic", "label", "deck", "অধ্যায়")
ANKI_HEADER = re.compile(r"^#(?:separator|html|tags|columns|deck|notetype)\b.*:", re.I)     # the lines Anki puts at the top of its export


def _table(cells):
    """Rows of cells → notes, if they're two columns (or say which column is which in a header row); else None."""
    if len(cells) < 2:
        return None
    head = [c.strip().lower() for c in cells[0]]
    q = next((head.index(h) for h in QUESTION_HEADS if h in head), None)
    a = next((head.index(h) for h in ANSWER_HEADS if h in head), None)
    named = q is not None and a is not None
    if named:
        cells = cells[1:]
    elif any(len(row) != 2 for row in cells):
        return None
    q, a = (q, a) if named else (0, 1)
    ch = next((head.index(h) for h in CHAPTER_HEADS if h in head), None) if named else None
    notes = []
    for row in cells:
        cell = lambda i: row[i].strip() if i is not None and i < len(row) else ""     # noqa: E731
        if _question(cell(q)):
            notes.append({"question": _question(cell(q)), "answer": cell(a)[:MAX_ANSWER], "chapter": cell(ch)[:MAX_CHAPTER]})
    return notes


def _columns(text, filled):
    """Two columns copied from a spreadsheet (tabs, as Anki and Quizlet export), or a .csv file."""
    if all("\t" in line for line in filled):
        return _table([line.split("\t", 1) if not _has_head(filled[0]) else line.split("\t") for line in filled])
    if "," in filled[0]:
        cells = [row for row in csv.reader(io.StringIO(text)) if any(c.strip() for c in row)]
        if _has_head(filled[0]) or (len(cells) >= 3 and len(cells) == len(filled)):      # (three rows at least: a line of prose has commas too)
            return _table(cells)
    return None


def _has_head(line):
    return {c.strip().strip('"').lower() for c in re.split(r"[\t,]", line)} & set(QUESTION_HEADS) != set()


def parse(text, chapter=""):
    """[{question, answer, chapter}, …] from pasted text — at most MAX_PASTE.
    `chapter` is given to the questions the text doesn't put in one."""
    lines = (text or "").replace("\r\n", "\n").replace("\r", "\n").replace("\u00a0", " ").split("\n")
    lines = [line for line in lines if not ANKI_HEADER.match(line)]
    rows = _scan(lines)
    filled = [line for line in lines if line.strip()]
    if not filled:
        return []
    table = _columns("\n".join(lines), filled) if not any(code for _line, code in rows) else None
    if table:
        notes = table
    elif any(not code and Q_LINE.match(line) for line, code in rows):
        notes = _marked(rows)
    else:
        notes = _headed(rows) or _numbered(rows) or _bolded(rows) or _blocks(rows)
    chapter = (chapter or "").strip()[:MAX_CHAPTER]
    for n in notes:
        n["chapter"] = n["chapter"] or chapter
    return list(notes)[:MAX_PASTE]


def parse_note(text):
    """Exam questions from a note: its ## headings, Q:/A: lines, bold questions, numbered list or "question ::
    answer" lines. Plain paragraphs aren't questions, so unlike parse() this doesn't fall back on them."""
    from .cards import parse_pairs

    lines = (text or "").replace("\r\n", "\n").split("\n")
    rows = _scan(lines)
    if any(not code and Q_LINE.match(line) for line, code in rows):
        return list(_marked(rows))[:MAX_PASTE]
    found = list(_headed(rows) or _numbered(rows) or _bolded(rows))
    return found[:MAX_PASTE] or [{"question": q[:MAX_QUESTION], "answer": a[:MAX_ANSWER], "chapter": ""} for q, a in parse_pairs(text)][:MAX_PASTE]


def add_found(user, subject, found):
    """Saves parsed questions at the end of the subject → the new rows, in order."""
    from .models import ExamNote

    start = next_order(subject)
    made = ExamNote.objects.bulk_create([ExamNote(owner=user, subject=subject, question=n["question"], answer=n["answer"], chapter=n["chapter"],
                                                  order=start + i) for i, n in enumerate(found)])
    return list(subject.notes.order_by("-pk")[:len(made)])[::-1] if made else []     # bulk_create gives no ids on every database


def fresh(subject, found):
    """Marks each parsed question `dupe` when it's already in the subject, or twice in the text → the others."""
    seen = {same(q) for q in subject.notes.values_list("question", flat=True)}
    for n in found:
        key = same(n["question"])
        n["dupe"] = key in seen
        seen.add(key)
    return [n for n in found if not n["dupe"]]


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
    # (the ones with no chapter come first: an empty heading can't say "no chapter" for those after a chapter)
    for n in sorted(ordered(notes), key=lambda n: bool(n.chapter)):
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


def in_order(qs, subject):
    """Chapter by chapter (chapters in the order their first question comes), then by place — what ordered() does,
    in SQL. The chapters are ranked once, up front: asking for each row took minutes on a subject of thousands."""
    from django.db.models import Case, IntegerField, Min, Value, When

    # (questions with no place yet, 0: the chapter's oldest decides)
    ranks = subject.notes.order_by().values("chapter").annotate(first=Min("order"), first_pk=Min("pk")).order_by("first", "first_pk")
    rank = Case(*[When(chapter=r["chapter"], then=Value(i)) for i, r in enumerate(ranks)], default=Value(0), output_field=IntegerField())
    return qs.annotate(chapter_rank=rank).order_by("chapter_rank", "order", "pk")


def numbers(subject):
    """{note id: its number} — the place in the subject, the same everywhere."""
    return {pk: i for i, pk in enumerate(in_order(subject.notes.all(), subject).values_list("pk", flat=True), 1)}


def matching(qs, text):
    """Each word in the question, the answer or the chapter, in any order."""
    from django.db.models import Q

    for word in (text or "").split()[:6]:
        qs = qs.filter(Q(question__icontains=word) | Q(answer__icontains=word) | Q(chapter__icontains=word))
    return qs


def filtered(subject, show="all", chapter=None, q=""):
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
    return matching(qs, q)


def due_today(user, today=None):
    """Questions that came due again, across every subject: [{subject, n}], most first — one each for the
    Today page and the morning email, or spaced repetition is only as good as remembering to open it."""
    from django.db.models import Count, Q

    from .models import ExamSubject

    today = today or timezone.localdate()
    rows = ExamSubject.objects.filter(owner=user).annotate(n=Count("notes", filter=Q(notes__is_known=True, notes__due_on__lte=today))).filter(n__gt=0)
    return sorted(rows, key=lambda s: -s.n)


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
    for chapter, known in in_order(subject.notes.all(), subject).values_list("chapter", "is_known"):
        row = out.setdefault(chapter, {"name": chapter, "n": 0, "known": 0})
        row["n"] += 1
        row["known"] += 1 if known else 0
    return list(out.values())


def move(note, before_id=None):
    """Put a question just before another (or last) and into that one's chapter, renumbering the subject."""
    ids = list(in_order(note.subject.notes.all(), note.subject).values_list("pk", flat=True))
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
