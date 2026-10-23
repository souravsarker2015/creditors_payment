"""Exam notes: questions and answers kept to revise before an exam. A plain
list per subject — no scheduling, no levels. This module reads a pasted list
into questions and writes a subject back out as text.

What a pasted list can look like (the same text the download gives):

    Q: What is photosynthesis?          one question after another, each
    A: Plants making food from light.   starting with "Q:"; the answer
                                        starts with "A:" and may run on
    Q: …                                for several lines

    What is osmosis?                    or: blocks split by an empty line —
    Water moving through a membrane.    the first line is the question,
                                        the rest its answer

    Capital of France<TAB>Paris          or: two columns pasted from a sheet
"""
import re

MAX_QUESTION, MAX_ANSWER, MAX_PASTE = 2000, 20000, 500

Q_LINE = re.compile(r"^\s*(?:Q|Question|প্রশ্ন)\s*\d*\s*[:.)\-]\s*", re.I)
A_LINE = re.compile(r"^\s*(?:A|Ans|Answer|উত্তর)\s*[:.)\-]\s*", re.I)
NUMBER = re.compile(r"^\s*(?:\d+|[০-৯]+)\s*[.)]\s+")      # "1. ", "2) " in front of a question


def _note(question, answer_lines):
    question = NUMBER.sub("", question).strip()
    answer = "\n".join(answer_lines).strip("\n").rstrip()
    return (question[:MAX_QUESTION], answer[:MAX_ANSWER]) if question else None


def _marked(lines):
    """Q:/A: lists: everything after a Q: line is its answer, "A:" or not.
    Anything before the first Q: is ignored."""
    out, q, a = [], None, []
    for line in lines:
        if Q_LINE.match(line):
            if q is not None:
                out.append(_note(q, a))
            q, a = Q_LINE.sub("", line), []
        elif q is not None:
            if not any(x.strip() for x in a) and A_LINE.match(line):
                line = A_LINE.sub("", line)
            a.append(line)
    if q is not None:
        out.append(_note(q, a))
    return out


def _blocks(lines):
    out, block = [], []
    for line in lines + [""]:
        if line.strip():
            block.append(line)
        elif block:
            first, rest = block[0], block[1:]
            if rest and A_LINE.match(rest[0]):
                rest[0] = A_LINE.sub("", rest[0])
            out.append(_note(first, rest))
            block = []
    return out


def parse(text):
    """[(question, answer), …] from pasted text — at most MAX_PASTE."""
    lines = (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    filled = [line for line in lines if line.strip()]
    if not filled:
        return []
    if all("\t" in line for line in filled):
        notes = [_note(q, [a]) for q, _tab, a in (line.partition("\t") for line in filled)]
    elif any(Q_LINE.match(line) for line in filled):
        notes = _marked(lines)
    else:
        notes = _blocks(lines)
    return [n for n in notes if n][:MAX_PASTE]


def as_text(subject, notes):
    """The subject as a Q:/A: list — reads back in with parse()."""
    out = [f"# {subject.name}", ""]
    for n in notes:
        out.append(f"Q: {n.question.strip()}")
        out.append(f"A: {n.answer.strip()}" if n.answer.strip() else "A:")
        out.append("")
    return "\n".join(out)


def as_json(note, number=None):
    return {"id": note.pk, "question": note.question, "answer": note.answer, "starred": note.is_starred, "known": note.is_known,
            "number": number}
