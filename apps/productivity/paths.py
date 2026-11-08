"""Learning roadmaps (Productivity), as roadmap.sh has them: a map of what to learn, step by
step — the main steps down the middle, the topics under each step branching off to the sides,
checkpoints (something to build) along the way. Each box is To learn, Learning, Done or Skipped,
and can have tasks (Productivity tasks), so learning shows up in the day's work.

The boxes sit anywhere on a canvas (static/js/paths.js): what comes in without places — a
ready-made roadmap, a file written by ChatGPT or Claude — is laid out here first.

The format people (and AI assistants) write, also what the download gives back:

    {"format": "learning-roadmap", "version": 1, "title": "…", "description": "…", "color": "blue",
     "steps": [{"id": "http", "title": "HTTP", "type": "step"|"checkpoint", "description": "…",
                "optional": false, "status": "todo"|"learning"|"done"|"skipped",
                "resources": [{"title": "…", "url": "https://…", "type": "article"}],
                "children": [{…the same, a topic under it…}]}],
     "notes": [{"title": "…"}], "links": [{"from": "id", "to": "id", "style": "solid"|"dashed"}],
     "autoLinks": true}

Only "title" and "steps" (each with a "title") are needed. Lines join the steps in order and each
box to the one it hangs under unless "autoLinks" is false; "links" adds more (or, with autoLinks
false, are all of them). "x", "y" and "w" keep a box's place and width. The outline format of
learning_paths/README.md is read too.
"""
import json
import math
import re
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from .models import Color, LearningPath, PathNode, PathNodeKind, PathStatus

FORMAT, VERSION = "learning-roadmap", 1
MAX_NODES = 600
MAX_TEXT = 20000
RESOURCE_TYPES = ("article", "video", "course", "book", "docs", "tool", "other")
FINISHED = (PathStatus.DONE, PathStatus.SKIPPED)
DIR = Path(__file__).parent / "learning_paths"
CATEGORIES = {"role": gettext_lazy("Roles"), "skill": gettext_lazy("Skills"), "language": gettext_lazy("Languages")}
TEMPLATES = ("backend", "frontend", "devops", "data-engineer", "ml-engineer", "senior-engineer",
             "system-design", "oop", "design-patterns", "dsa", "python", "java", "go", "rust")

# (width, height) of each kind of box; a topic under a topic is a little smaller. The page uses the same.
SIZES = {"step": (260, 48), "checkpoint": (260, 48), "topic": (210, 40), "sub": (190, 36), "note": (220, 40)}
STEP_GAP, ROW_GAP, SIDE_GAP, SUB_GAP = 64, 12, 70, 40


class Invalid(ValueError):
    """What's wrong with a roadmap someone gave, said so they can fix it."""


# ── Reading what someone gives: JSON (also inside ``` fences or chat text) or an outline ──
def read(text):
    text = (text or "").strip().lstrip("﻿")
    if not text:
        raise Invalid(_("It's empty. Paste the roadmap, or choose a .json file."))
    first = text.lstrip("`").lstrip()
    if text.startswith("{") or "```" in text or (first.lower().startswith("json") and "{" in text) or ('"steps"' in text and "{" in text):
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end < start:
            raise Invalid(_("That looks like JSON but has no { … } in it."))
        try:
            data = json.loads(text[start:end + 1])
        except json.JSONDecodeError as e:
            raise Invalid(_("That isn't valid JSON — line %(line)s, column %(col)s: %(msg)s.") % {"line": e.lineno, "col": e.colno, "msg": e.msg})
        if not isinstance(data, dict):
            raise Invalid(_("The JSON should be one object: { \"title\": …, \"steps\": [ … ] }."))
        return data
    return outline(text)


_FIELD = re.compile(r"^(title|about|description|color|colour|category)\s*:\s*(.*)$", re.I)


def _outline_node(body):
    body = body.strip()
    optional = body.startswith("?")
    title, _sep, about = body.lstrip("?").strip().partition(" :: ")
    return {"title": title.strip(), "description": about.strip(), "optional": optional, "resources": [], "children": []}


def outline(text):
    """The outline format: `# step`, `! checkpoint`, `- topic` (indented: a topic under it),
    `?` for optional, ` :: ` before a description, `@ title | url` for a link, `key: value` on top."""
    spec, last, topic = {"title": "", "description": "", "color": "", "category": "", "steps": []}, None, None
    for raw in text.splitlines():
        if not raw.strip():
            continue
        indent = len(raw.expandtabs(2)) - len(raw.expandtabs(2).lstrip())
        line = raw.strip()
        field = _FIELD.match(line)
        if field and not spec["steps"]:
            name = {"about": "description", "colour": "color"}.get(field.group(1).lower(), field.group(1).lower())
            spec[name] = field.group(2).strip()
        elif line[0] in "#!" and not line.startswith("#!"):
            node = _outline_node(line.lstrip("#!"))
            node["type"] = "checkpoint" if line[0] == "!" else "step"
            spec["steps"].append(node)
            last, topic = node, None
        elif line[:2] in ("- ", "* ") or (line[:1] in "-*" and len(line) > 1 and line[1] == "?"):
            node = _outline_node(line[1:])
            if not spec["steps"]:
                spec["steps"].append({"title": spec["title"] or _("Start"), "type": "step", "resources": [], "children": []})
            if indent >= 2 and topic is not None:
                topic["children"].append(node)
            else:
                spec["steps"][-1]["children"].append(node)
                topic = node
            last = node
        elif line.startswith("@") and last is not None:
            title, _sep, url = line[1:].partition("|")
            url = (url or title).strip()
            last["resources"].append({"title": title.strip() if _sep else url, "url": url})
        elif last is not None:                       # a line of its own: more of the description above
            last["description"] = (last["description"] + "\n" + line).strip()
        elif not spec["title"]:
            spec["title"] = line.lstrip("# ").strip()
    if not spec["steps"]:
        raise Invalid(_("No steps found. Start step lines with “# ” (or give JSON with a \"steps\" list)."))
    return spec


# ── Checking it and turning it into boxes and lines ──────────────────────────
def _text(value, limit, where=None, multiline=False):
    if value is None:
        return ""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        value = str(value)
    if not isinstance(value, str):
        if where:
            raise Invalid(_("%(where)s: this should be text.") % {"where": where})
        return ""
    value = value.replace("\r\n", "\n").strip()
    if not multiline:
        value = " ".join(value.split())
    return value[:limit]


def _resources(value, where=""):
    out = []
    if not isinstance(value, list):
        return out
    for r in value[:20]:
        if isinstance(r, str):
            r = {"url": r}
        if not isinstance(r, dict):
            continue
        url = _text(r.get("url") or r.get("link") or r.get("href"), 500)
        if not re.match(r"^https?://\S+$", url, re.I):
            continue
        kind = _text(r.get("type") or r.get("kind"), 20).lower()
        out.append({"title": _text(r.get("title") or r.get("name"), 200) or url, "url": url, "type": kind if kind in RESOURCE_TYPES else "other"})
    return out


def _slug(raw):
    s = re.sub(r"[^a-z0-9]+", "-", str(raw or "").lower()).strip("-")[:48]
    return s


def _key(raw, used, title=""):
    base = _slug(raw) or _slug(title) or "n"
    key, n = base, 2
    while key in used:
        key, n = f"{base}-{n}", n + 1
    used.add(key)
    return key


def _number(value, lo=-1e6, hi=1e6):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return max(lo, min(hi, float(value)))


def build(spec):
    """The JSON format checked: (the roadmap's fields, [box dicts], [lines]). Raises Invalid saying where."""
    if not isinstance(spec, dict):
        raise Invalid(_("The roadmap should be one object with a title and steps."))
    title = _text(spec.get("title") or spec.get("name"), 150)
    if not title:
        raise Invalid(_("Give the roadmap a \"title\"."))
    steps = spec.get("steps", spec.get("nodes"))
    if not isinstance(steps, list) or not steps:
        raise Invalid(_("It needs a \"steps\" list with at least one step in it."))
    nodes, used, ids = [], set(), {}

    def walk(item, where, default_kind, parent):
        if isinstance(item, str):
            item = {"title": item}
        if not isinstance(item, dict):
            raise Invalid(_("%(where)s should be an object with a \"title\".") % {"where": where})
        t = _text(item.get("title") or item.get("name"), 200, where)
        if not t:
            raise Invalid(_("%(where)s has no \"title\".") % {"where": where})
        if len(nodes) >= MAX_NODES:
            raise Invalid(_("That's more than %(n)s boxes — split it into smaller roadmaps.") % {"n": MAX_NODES})
        kind = _text(item.get("type") or item.get("kind"), 20).lower()
        kind = kind if kind in PathNodeKind.values else default_kind
        status = _text(item.get("status"), 20).lower()
        color = _text(item.get("color"), 10).lower()
        raw_id = item.get("id")
        key = _key(raw_id, used, t)
        if raw_id is not None:
            ids.setdefault(str(raw_id), key)
        ids.setdefault(key, key)
        node = {"key": key, "kind": kind, "title": t, "description": _text(item.get("description"), MAX_TEXT, multiline=True),
                "status": status if status in PathStatus.values else PathStatus.TODO, "optional": bool(item.get("optional")),
                "color": color if color in Color.values else "", "resources": _resources(item.get("resources"), where),
                "parent": parent, "order": len(nodes),
                "x": _number(item.get("x")), "y": _number(item.get("y")), "w": _number(item.get("w"), 80, 800)}
        nodes.append(node)
        children = item.get("children", item.get("topics")) or []
        if not isinstance(children, list):
            raise Invalid(_("%(where)s: \"children\" should be a list.") % {"where": where})
        for i, child in enumerate(children):
            walk(child, f"{where} › {_('item')} {i + 1}", PathNodeKind.TOPIC, key)

    for i, step in enumerate(steps):
        walk(step, _("Step %(n)s") % {"n": i + 1}, PathNodeKind.STEP, "")
    for i, note in enumerate(spec.get("notes") or []):
        walk(note if isinstance(note, dict) else {"title": note}, _("Note %(n)s") % {"n": i + 1}, PathNodeKind.NOTE, "")
        nodes[-1]["kind"] = PathNodeKind.NOTE

    edges, seen = [], set()

    def link(a, b, style):
        if a and b and a != b and (a, b) not in seen:
            seen.add((a, b))
            edges.append({"from": a, "to": b, "style": style})

    if spec.get("autoLinks", True) is not False:
        spine = [n["key"] for n in nodes if not n["parent"] and n["kind"] != PathNodeKind.NOTE]
        for a, b in zip(spine, spine[1:]):
            link(a, b, "solid")
        for n in nodes:
            if n["parent"]:
                link(n["parent"], n["key"], "dashed")
    for line in spec.get("links") or []:
        if isinstance(line, dict):
            style = line.get("style") if line.get("style") in ("solid", "dashed") else "dashed"
            link(ids.get(str(line.get("from"))), ids.get(str(line.get("to"))), style)

    if any(n["x"] is None or n["y"] is None for n in nodes):
        layout(nodes)
    color = _text(spec.get("color"), 10).lower()
    fields = {"title": title, "description": _text(spec.get("description") or spec.get("about"), 2000, multiline=True),
              "color": color if color in Color.values else Color.BLUE}
    return fields, nodes, edges


# ── Laying it out: steps down the middle, topics to the sides ────────────────
def size(node, depth=1):
    if node["kind"] == PathNodeKind.TOPIC and depth > 1:
        w, h = SIZES["sub"]
    else:
        w, h = SIZES.get(node["kind"], SIZES["topic"])
    return (node.get("w") or w), h


def layout(nodes):
    """Gives every box a place (x, y: its top-left corner), as roadmap.sh draws them: the top-level
    boxes in a column down the middle, in order; what hangs under each to its right or left (both,
    when there are many); what hangs under those further out. Notes go to the far right."""
    keys = {n["key"] for n in nodes}
    kids = defaultdict(list)
    for n in nodes:
        if n["kind"] != PathNodeKind.NOTE and n["parent"] in keys and n["parent"] != n["key"]:
            kids[n["parent"]].append(n)
    spine = [n for n in nodes if n["kind"] != PathNodeKind.NOTE and n["parent"] not in keys]

    def height(items, depth, seen):
        total = 0
        for c in items:
            if c["key"] in seen:
                continue
            total += max(size(c, depth)[1], height(kids[c["key"]], depth + 1, seen | {c["key"]})) + ROW_GAP
        return max(total - ROW_GAP, 0)

    def column(items, side, top, edge, depth, seen):
        y = top
        for c in items:
            if c["key"] in seen:
                continue
            w, h = size(c, depth)
            sub = kids[c["key"]]
            block = max(h, height(sub, depth + 1, seen | {c["key"]}))
            c["x"] = edge if side > 0 else -edge - w
            c["y"] = y + (block - h) / 2
            if sub:
                column(sub, side, y + (block - height(sub, depth + 1, seen | {c["key"]})) / 2, edge + w + SUB_GAP, depth + 1, seen | {c["key"]})
            y += block + ROW_GAP

    y = 0
    for i, st in enumerate(spine):
        children = kids[st["key"]]
        if len(children) <= 4:
            right, left = (children, []) if i % 2 == 0 else ([], children)
        else:
            half = math.ceil(len(children) / 2)
            right, left = children[:half], children[half:]
        w, h = size(st, 0)
        seen = {st["key"]}
        hr, hl = height(right, 1, seen), height(left, 1, seen)
        band = max(h, hr, hl)
        st["x"], st["y"] = -w / 2, y + (band - h) / 2
        column(right, 1, y + (band - hr) / 2, w / 2 + SIDE_GAP, 1, seen)
        column(left, -1, y + (band - hl) / 2, w / 2 + SIDE_GAP, 1, seen)
        y += band + STEP_GAP
    placed = [n for n in nodes if n.get("x") is not None and n["kind"] != PathNodeKind.NOTE]
    right_edge = max((n["x"] + size(n)[0] for n in placed), default=300)
    for i, n in enumerate(x for x in nodes if x["kind"] == PathNodeKind.NOTE):
        n["x"], n["y"] = right_edge + 80, i * 60
    for n in nodes:                                   # anything left over (a loop of parents): below
        if n.get("x") is None:
            n["x"], n["y"] = 0, y
            y += 60
        n["x"], n["y"] = round(n["x"]), round(n["y"])
    return nodes


# ── Making, copying, exporting ───────────────────────────────────────────────
def _row(n, now):
    return {"key": n["key"], "kind": n["kind"], "title": n["title"], "description": n["description"], "x": n["x"], "y": n["y"],
            "w": int(n["w"]) if n.get("w") else None, "status": n["status"], "optional": n["optional"], "color": n["color"],
            "resources": n["resources"], "parent": n["parent"], "order": n["order"],
            "done_at": now if n["status"] == PathStatus.DONE else None}


@transaction.atomic
def create(user, spec, template=""):
    fields, nodes, edges = build(spec)
    path = LearningPath.objects.create(owner=user, template=template[:40], edges=edges, **fields)
    now = timezone.now()
    PathNode.objects.bulk_create([PathNode(path=path, **_row(n, now)) for n in nodes])
    return path


@lru_cache(maxsize=None)
def _template(key):
    spec = outline((DIR / f"{key}.txt").read_text(encoding="utf-8"))
    fields, nodes, _edges = build(spec)
    return spec, len([n for n in nodes if n["kind"] != PathNodeKind.NOTE]), len(spec["steps"])


def templates():
    out = []
    for key in TEMPLATES:
        spec, count, steps = _template(key)
        out.append({"key": key, "title": spec["title"], "about": spec["description"], "color": spec["color"] or Color.BLUE,
                    "category": spec.get("category") or "skill", "count": count, "steps": steps})
    return out


def from_template(user, key):
    if key not in TEMPLATES:
        raise Invalid(_("There's no ready-made roadmap called that."))
    return create(user, _template(key)[0], template=key)


def ordered(nodes):
    """In reading order: the top-level boxes top to bottom, each followed by what hangs under it."""
    keys = {n.key for n in nodes}
    kids = defaultdict(list)
    for n in nodes:
        if n.parent in keys and n.parent != n.key:
            kids[n.parent].append(n)
    out, seen = [], set()

    def visit(n):
        if n.key in seen:
            return
        seen.add(n.key)
        out.append(n)
        for c in sorted(kids[n.key], key=lambda c: (c.y, c.x)):
            visit(c)

    for n in sorted((n for n in nodes if n.parent not in keys), key=lambda n: (n.y, n.x)):
        visit(n)
    for n in nodes:                                   # (a loop of parents)
        visit(n)
    return out


def export(path, progress=True):
    nodes = list(path.nodes.all())
    by_key = {n.key: n for n in nodes}
    kids = defaultdict(list)
    for n in nodes:
        if n.parent in by_key and n.parent != n.key:
            kids[n.parent].append(n)

    def one(n, seen):
        d = {"id": n.key, "title": n.title}
        if n.kind != (PathNodeKind.STEP if n.parent not in by_key else PathNodeKind.TOPIC):     # only when it isn't what its place makes it
            d["type"] = n.kind
        if n.description:
            d["description"] = n.description
        if n.optional:
            d["optional"] = True
        if progress and n.status != PathStatus.TODO:
            d["status"] = n.status
        if n.color:
            d["color"] = n.color
        if n.resources:
            d["resources"] = n.resources
        d.update({"x": round(n.x), "y": round(n.y)})
        if n.w:
            d["w"] = n.w
        children = [one(c, seen | {n.key}) for c in sorted(kids[n.key], key=lambda c: (c.y, c.x)) if c.key not in seen]
        if children:
            d["children"] = children
        return d

    top = sorted((n for n in nodes if n.parent not in by_key and n.kind != PathNodeKind.NOTE), key=lambda n: (n.y, n.x))
    notes = [n for n in nodes if n.kind == PathNodeKind.NOTE and n.parent not in by_key]
    return {"format": FORMAT, "version": VERSION, "title": path.title, "description": path.description, "color": path.color,
            "autoLinks": False, "steps": [one(n, set()) for n in top],
            "notes": [{"id": n.key, "title": n.title, **({"description": n.description} if n.description else {}), "x": round(n.x), "y": round(n.y)} for n in notes],
            "links": path.edges}


@transaction.atomic
def duplicate(path, title=None):
    spec = export(path, progress=False)
    spec["title"] = title or (_("%(title)s (copy)") % {"title": path.title})[:150]
    return create(path.owner, spec, template=path.template)


# ── The canvas, as the page has it now ───────────────────────────────────────
NODE_FIELDS = ("kind", "title", "description", "x", "y", "w", "status", "optional", "color", "resources", "parent", "order")


def node_json(n, tasks=None):
    t = (tasks or {}).get(n.pk, (0, 0))
    return {"key": n.key, "kind": n.kind, "title": n.title, "description": n.description, "x": n.x, "y": n.y, "w": n.w,
            "status": n.status, "optional": n.optional, "color": n.color, "resources": n.resources, "parent": n.parent,
            "tasks": {"open": t[0], "done": t[1]}}


def task_counts(path):
    from .models import Status, Task

    out = defaultdict(lambda: [0, 0])
    for node_id, status in Task.objects.filter(path_node__path=path).values_list("path_node_id", "status"):
        out[node_id][1 if status == Status.DONE else 0] += 1
    return {k: tuple(v) for k, v in out.items()}


@transaction.atomic
def save_graph(path, graph):
    """Every box and line as the page has them: new boxes made, changed ones saved, missing ones deleted
    (their tasks stay, unlinked). Raises Invalid."""
    if not isinstance(graph, dict) or not isinstance(graph.get("nodes"), list):
        raise Invalid(_("Nothing to save."))
    raw = graph["nodes"]
    if len(raw) > MAX_NODES:
        raise Invalid(_("That's more than %(n)s boxes — split it into smaller roadmaps.") % {"n": MAX_NODES})
    clean, keys = [], set()
    for i, d in enumerate(raw):
        if not isinstance(d, dict):
            continue
        key = _text(d.get("key"), 64)
        if not key or key in keys:
            continue
        keys.add(key)
        kind, status, color = d.get("kind"), d.get("status"), d.get("color") or ""
        w = _number(d.get("w"), 80, 800)
        clean.append({"key": key, "kind": kind if kind in PathNodeKind.values else PathNodeKind.TOPIC,
                      "title": _text(d.get("title"), 200) or "…", "description": _text(d.get("description"), MAX_TEXT, multiline=True),
                      "x": _number(d.get("x")) or 0.0, "y": _number(d.get("y")) or 0.0, "w": int(w) if w else None,
                      "status": status if status in PathStatus.values else PathStatus.TODO, "optional": bool(d.get("optional")),
                      "color": color if color in Color.values else "", "resources": _resources(d.get("resources")),
                      "parent": _text(d.get("parent"), 64), "order": i})
    now = timezone.now()
    # A write first: SQLite then holds the write lock from the start, so a save made while another
    # request writes waits its turn, instead of failing ("database is locked") when its reads turn into writes.
    LearningPath.objects.filter(pk=path.pk).update(updated_at=now)
    have = {n.key: n for n in path.nodes.all()}
    changed, made = [], []
    for d in clean:
        n = have.pop(d["key"], None)
        if n is None:
            made.append(PathNode(path=path, done_at=now if d["status"] == PathStatus.DONE else None, **d))
            continue
        if any(getattr(n, f) != d[f] for f in NODE_FIELDS):
            if d["status"] != n.status:
                n.done_at = now if d["status"] == PathStatus.DONE else None
            for f in NODE_FIELDS:
                setattr(n, f, d[f])
            n.updated_at = now
            changed.append(n)
    if changed:
        PathNode.objects.bulk_update(changed, [*NODE_FIELDS, "done_at", "updated_at"])
    if made:
        PathNode.objects.bulk_create(made)
    if have:
        PathNode.objects.filter(pk__in=[n.pk for n in have.values()]).delete()
    edges, seen = [], set()
    for e in graph.get("edges") or []:
        if not isinstance(e, dict):
            continue
        a, b = str(e.get("from")), str(e.get("to"))
        if a in keys and b in keys and a != b and (a, b) not in seen:
            seen.add((a, b))
            edges.append({"from": a, "to": b, "style": "dashed" if e.get("style") == "dashed" else "solid"})
    path.edges = edges
    path.save(update_fields=["edges", "updated_at"])
    return path


def tidy(path):
    """New places for every box (the layout of a fresh roadmap), keeping who hangs under whom: {key: [x, y]}."""
    nodes = [{"key": n.key, "kind": n.kind, "parent": n.parent, "w": n.w} for n in ordered(list(path.nodes.all()))]
    layout(nodes)
    return {n["key"]: [n["x"], n["y"]] for n in nodes}


# ── How far along ────────────────────────────────────────────────────────────
def progress(nodes):
    counted = [n for n in nodes if n.kind != PathNodeKind.NOTE]
    done = sum(1 for n in counted if n.status == PathStatus.DONE)
    skipped = sum(1 for n in counted if n.status == PathStatus.SKIPPED)
    left = len(counted) - skipped
    return {"total": len(counted), "done": done, "skipped": skipped, "learning": sum(1 for n in counted if n.status == PathStatus.LEARNING),
            "pct": round(100 * done / left) if left else (100 if counted else 0)}


def next_up(nodes, n=1):
    """What to learn next, in reading order: what's being learnt first, then what's not started
    (a step with topics under it is reached through its topics)."""
    keys_with_kids = {x.parent for x in nodes}
    left = [x for x in ordered(nodes) if x.kind != PathNodeKind.NOTE and x.status not in FINISHED]
    learning = [x for x in left if x.status == PathStatus.LEARNING]
    rest = [x for x in left if x.status != PathStatus.LEARNING and not (x.kind == PathNodeKind.STEP and x.key in keys_with_kids)]
    return (learning + rest)[:n]


def summary(path):
    nodes = list(path.nodes.all())
    nxt = next_up(nodes)
    return {**progress(nodes), "next": nxt[0].title if nxt else ""}


def plan_next(path, user, n=5, today=None):
    """Tasks for the next topics to learn (those without an open task yet), in order. Returns them."""
    from . import services
    from .models import Status, Task

    busy = set(Task.objects.filter(path_node__path=path).exclude(status=Status.DONE).values_list("path_node_id", flat=True))
    made = []
    for node in next_up(list(path.nodes.all()), n=MAX_NODES):
        if node.pk in busy:
            continue
        made.append(Task.objects.create(owner=user, title=(_("Learn: %(topic)s") % {"topic": node.title})[:300], path_node=node,
                                        link=node.resources[0]["url"] if node.resources else "", my_day=today,
                                        order=services.next_order(user, Status.TODO)))
        if len(made) >= n:
            break
    return made


# ── Examples to give people (and the prompt to give an AI assistant) ──────────
EXAMPLE = {
    "format": FORMAT, "version": VERSION,
    "title": "Docker in two weeks",
    "description": "From the first container to a multi-service app.",
    "color": "teal",
    "steps": [
        {"id": "basics", "title": "Container basics", "description": "What a container is, and how it differs from a virtual machine.",
         "resources": [{"title": "Docker: get started", "url": "https://docs.docker.com/get-started/", "type": "docs"}],
         "children": [
             {"id": "images", "title": "Images and layers", "description": "How images are built and cached."},
             {"id": "run", "title": "Running containers", "description": "docker run, ports, volumes, logs."},
         ]},
        {"id": "dockerfile", "title": "Writing a Dockerfile",
         "children": [
             {"id": "multistage", "title": "Multi-stage builds", "description": "Small, safe production images."},
             {"id": "cache", "title": "Build cache", "optional": True},
         ]},
        {"id": "compose", "title": "Docker Compose", "description": "Several containers that work together.",
         "children": [{"id": "networks", "title": "Networks and volumes"}]},
        {"id": "project", "title": "Checkpoint: containerise an app", "type": "checkpoint",
         "description": "A web app plus its database, started with one command."},
    ],
    "links": [{"from": "images", "to": "multistage", "style": "dashed"}],
}

PROMPT = """Make a learning roadmap for: {topic}
My level now: {level}. Time I have: {time}.

Answer with JSON only (no explanation), in exactly this format:
{{
  "format": "learning-roadmap",
  "version": 1,
  "title": "short name",
  "description": "one sentence",
  "color": "blue",
  "steps": [
    {{
      "id": "short-unique-id",
      "title": "Main step",
      "type": "step",
      "description": "1–2 sentences: what it is and why it matters",
      "resources": [{{"title": "name", "url": "https://...", "type": "docs"}}],
      "children": [
        {{"id": "another-id", "title": "Topic under it", "description": "...", "optional": false,
          "children": []}}
      ]
    }},
    {{"id": "cp-1", "title": "Checkpoint: build something", "type": "checkpoint", "description": "a small project that proves the steps above"}}
  ]
}}

Rules:
- 8 to 14 steps in learning order, each with 3 to 6 topics in "children" (topics may have their own children).
- After every 3 or 4 steps, add a step with "type": "checkpoint" — a project to build.
- Mark nice-to-have topics with "optional": true.
- "color" is one of: slate, blue, teal, green, lime, amber, orange, red, pink, purple.
- "type" of a resource is one of: article, video, course, book, docs, tool, other.
- Only add resources whose links you are sure exist (official documentation is best). Leave "resources" out otherwise.
- Every "id" is unique, lowercase, with dashes."""


def keep_going(user):
    """For Today: the learning roadmap last worked on that still has something to learn, and its next topic."""
    for path in LearningPath.objects.filter(owner=user, is_archived=False).order_by("-updated_at")[:3]:
        nodes = list(path.nodes.all())
        nxt = next_up(nodes)
        if nxt:
            return {"path": path, "next": nxt[0], "pct": progress(nodes)["pct"]}
    return None
