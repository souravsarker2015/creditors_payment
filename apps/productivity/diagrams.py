"""Diagrams: the starting points (templates), the checks on what a page
saves, and turning a mind map into an outline or tasks.

Mind maps, system design boards and free drawings are drawn by hand; their
shapes live in `Diagram.data`:

    mind map  {"root": {"id", "text", "children": [...], "collapsed"?, "color"?, "done"?},
               "layout": "map"|"right"|"down"}
    board     {"nodes": [{"id", "type", "x", "y", "w", "h", "label", "tech", "note", "color"}],
               "edges": [{"id", "from", "to", "label", "style": "solid"|"dashed", "arrow": "end"|"both"|"none"}],
               "est": {back-of-the-envelope numbers}}
    drawing   {"nodes": [{"id", "shape", "x", "y", "w", "h", "label", …}], "edges": [{"id", "from", "to", …}]}
              (see static/js/drawmodel.js)

Every other kind is Mermaid text in `Diagram.source`, drawn in the browser;
its `data` says how it looks: {"look": "handDrawn"}. Flowcharts, state, class
and database diagrams can be drawn by dragging shapes too: then `data` also
holds {"mode": "draw"|"text", "draw": {a drawing, plus "src": the text it was
made from}} and the text is written from the drawing.

Earlier states are kept as DiagramVersion rows (see `remember`).
"""
import json
import re
from datetime import timedelta

from django.utils import timezone
from django.utils.translation import gettext as _, gettext_lazy

from .models import DRAG_KINDS, DiagramKind, DiagramVersion

MAX_SOURCE = 100_000          # characters of Mermaid text
MAX_DATA = 1_000_000          # bytes of shapes (JSON)
MAX_PREVIEW = 800_000         # bytes of the SVG picture
MAX_ITEMS = 3000              # nodes + links on a board, nodes in a mind map
MAX_TEXT = 500                # characters in one label


# ── Checking what the page sends ────────────────────────────────────────────
class Invalid(ValueError):
    pass


def clean_data(kind, raw):
    """The shapes a page saved, checked: valid JSON, not too big, the right shape."""
    if len(raw) > MAX_DATA:
        raise Invalid(_("This diagram is too big to save."))
    try:
        data = json.loads(raw or "{}")
    except ValueError:
        raise Invalid(_("The diagram couldn't be read."))
    if not isinstance(data, dict):
        raise Invalid(_("The diagram couldn't be read."))
    if kind == DiagramKind.MINDMAP:
        root = data.get("root")
        if not isinstance(root, dict):
            raise Invalid(_("A mind map needs its central idea."))
        if count_nodes(root) > MAX_ITEMS:
            raise Invalid(_("This diagram is too big to save."))
        _clip_texts(root)
    elif kind in (DiagramKind.SYSTEM, DiagramKind.DRAWING):
        data = _clean_shapes(data, ("label", "tech", "note", "attrs", "methods"))
    else:                                   # a text diagram: how it looks (and, for some, its drawing)
        out = {"look": "handDrawn"} if data.get("look") == "handDrawn" and kind in SKETCH_KINDS else {}
        if kind in DRAG_KINDS:
            if data.get("mode") in ("draw", "text"):
                out["mode"] = data["mode"]
            if isinstance(data.get("draw"), dict):
                draw = _clean_shapes(data["draw"], ("label", "attrs", "methods"))
                out["draw"] = {"nodes": draw["nodes"], "edges": draw["edges"], "dir": str(draw.get("dir") or "")[:2],
                               "extra": [str(x)[:MAX_TEXT * 2] for x in draw.get("extra") or [] if isinstance(x, str)][:500],
                               "front": str(draw.get("front") or "")[:MAX_TEXT * 4], "src": str(draw.get("src") or "")[:MAX_SOURCE]}
        data = out
    return data


def _clean_shapes(data, texts):
    """Shapes and the links between them: lists of objects with ids, words cut to size,
    and links whose end was deleted dropped rather than saved broken."""
    nodes, edges = data.get("nodes", []), data.get("edges", [])
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise Invalid(_("The diagram couldn't be read."))
    if len(nodes) + len(edges) > MAX_ITEMS:
        raise Invalid(_("This diagram is too big to save."))
    ids = set()
    for n in nodes:
        if not isinstance(n, dict) or not n.get("id"):
            raise Invalid(_("The diagram couldn't be read."))
        ids.add(n["id"])
        for key in texts:
            if isinstance(n.get(key), str):
                n[key] = n[key][:MAX_TEXT * (8 if key in ("note", "attrs", "methods") else 4 if key == "label" else 1)]
        if "src" in n:                      # a picture: one of ours (/media/…) or on the web — nothing else
            src = n["src"] if isinstance(n["src"], str) else ""
            if not (src.startswith("/") and not src.startswith("//") or src.startswith("https://")) or len(src) > 2000:
                n.pop("src")
    data["nodes"] = nodes
    data["edges"] = [e for e in edges if isinstance(e, dict) and e.get("from") in ids and e.get("to") in ids]
    for e in data["edges"]:
        for key in ("label", "fromLabel", "toLabel"):
            if isinstance(e.get(key), str):
                e[key] = e[key][:MAX_TEXT]
    return data


def _clip_texts(node, depth=0):
    if depth > 60:
        raise Invalid(_("This mind map goes too deep."))
    node["text"] = str(node.get("text", ""))[:MAX_TEXT]
    kids = node.get("children") or []
    if not isinstance(kids, list):
        raise Invalid(_("The diagram couldn't be read."))
    node["children"] = [k for k in kids if isinstance(k, dict)]
    for k in node["children"]:
        _clip_texts(k, depth + 1)


def count_nodes(node):
    return 1 + sum(count_nodes(k) for k in (node.get("children") or []) if isinstance(k, dict))


def clean_preview(svg):
    """The list's picture of a diagram: an SVG drawn by the page. It is only
    ever shown as an image with scripts off (see views.diagram_preview_view);
    anything that looks like it carries a script is not kept at all."""
    svg = (svg or "").strip()
    if not svg or len(svg) > MAX_PREVIEW or not svg.startswith("<svg"):
        return ""
    if re.search(r"<script|<foreignObject|javascript:|<[^>]*\son\w+\s*=", svg, re.I):
        return ""
    return svg


# Text diagrams that can be drawn as if by hand (Mermaid's "handDrawn" look).
SKETCH_KINDS = (DiagramKind.FLOWCHART, DiagramKind.STATE, DiagramKind.CLASS)

KIND_WORDS = [
    (r"^(flowchart|graph)\b", DiagramKind.FLOWCHART), (r"^sequenceDiagram\b", DiagramKind.SEQUENCE),
    (r"^erDiagram\b", DiagramKind.ER), (r"^classDiagram\b", DiagramKind.CLASS), (r"^stateDiagram", DiagramKind.STATE),
    (r"^gantt\b", DiagramKind.GANTT), (r"^timeline\b", DiagramKind.TIMELINE), (r"^journey\b", DiagramKind.JOURNEY),
    (r"^C4(Context|Container|Component|Dynamic|Deployment)\b", DiagramKind.C4), (r"^architecture(-beta)?\b", DiagramKind.ARCHITECTURE),
    (r"^block(-beta)?\b", DiagramKind.BLOCK), (r"^gitGraph\b", DiagramKind.GITGRAPH), (r"^pie\b", DiagramKind.PIE),
    (r"^quadrantChart\b", DiagramKind.QUADRANT), (r"^xychart(-beta)?\b", DiagramKind.XYCHART), (r"^sankey(-beta)?\b", DiagramKind.SANKEY),
]


def kind_of_source(source, current):
    """The kind of Mermaid text, from its first real line (front matter and %% comments skipped)."""
    lines = [l.strip() for l in (source or "").splitlines()]
    if lines and lines[0] == "---":                     # --- front matter ---
        try:
            lines = lines[lines.index("---", 1) + 1:]
        except ValueError:
            pass
    first = next((l for l in lines if l and not l.startswith("%%")), "")
    for pattern, kind in KIND_WORDS:
        if re.match(pattern, first):
            return kind
    return current


# ── Mind map → outline, tasks ───────────────────────────────────────────────
def find(node, node_id):
    if node.get("id") == node_id:
        return node
    for k in node.get("children") or []:
        hit = find(k, node_id)
        if hit:
            return hit
    return None


def outline(node, depth=0):
    """A mind map as a Markdown list: the centre as a heading, branches indented (done ideas ticked)."""
    text = " ".join(str(node.get("text", "")).split())
    tick = "[x] " if node.get("done") else ""
    lines = [f"# {text}", ""] if depth == 0 else ["  " * (depth - 1) + f"- {tick}{text}"]
    for k in node.get("children") or []:
        lines += outline(k, depth + 1)
    return lines


def outline_text(data):
    return "\n".join(outline(data.get("root") or {"text": ""})).strip() + "\n"


def branch_titles(data, node_id):
    """The ideas under one node (or the node itself when it has none), as task titles."""
    node = find(data.get("root") or {}, node_id)
    if node is None:
        return []
    kids = node.get("children") or []
    picked = [k for k in kids if not k.get("done")] if kids else [node]
    return [" ".join(str(k.get("text", "")).split())[:300] for k in picked if str(k.get("text", "")).strip()]


# ── A note's outline → a mind map ───────────────────────────────────────────
OUTLINE_LINE = re.compile(r"^(?P<indent>[ \t]*)(?:(?P<hashes>#{1,6})\s+|(?:[-*+]|\d+[.)])\s+(?P<tick>\[[ xX]\]\s+)?)(?P<text>\S.*)$")


def _plain(text):
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)      # links and pictures keep their words
    text = re.sub(r"\[\[([^\]]+)\]\]", r"\1", text)                # [[Other note]]
    return re.sub(r"[*_`~]+", "", text).strip()[:MAX_TEXT]


def outline_map(title, body):
    """Headings and list items of a note as a mind map: the title in the middle,
    headings as branches and each list under the heading it sits in. Code
    blocks and plain sentences are left out. None when there's no outline."""
    root = {"id": "r", "text": _plain(title) or "…", "children": []}
    stack, count, fence = [(-1, root)], 0, False
    for line in (body or "").splitlines():
        if line.lstrip().startswith("```"):
            fence = not fence
            continue
        m = None if fence else OUTLINE_LINE.match(line)
        if not m:
            continue
        text = _plain(m.group("text"))
        if not text:
            continue
        if m.group("hashes"):
            level = len(m.group("hashes"))
            if level == 1 and count == 0 and text.lower() == root["text"].lower():
                continue                      # the note's own title as its first heading
        else:
            level = 10 + len(m.group("indent").expandtabs(4)) // 2    # lists sit under every heading
        while stack[-1][0] >= level:
            stack.pop()
        count += 1
        if count > MAX_ITEMS:
            break
        node = {"id": f"n{count}", "text": text, "children": []}
        if m.group("tick") and m.group("tick").strip().lower() == "[x]":
            node["done"] = True
        stack[-1][1]["children"].append(node)
        stack.append((level, node))
    return {"root": root} if count else None


# ── Versions: earlier states to go back to ──────────────────────────────────
AUTO_EVERY = timedelta(minutes=10)    # a new automatic copy at most this often while editing
KEEP_AUTO = 40                        # automatic copies kept per diagram (named ones are always kept)


def has_drawing(d):
    return bool(d.source.strip() if not d.is_visual else (d.data.get("root") or d.data.get("nodes")))


def remember(d, name="", force=False):
    """Keep the diagram as it is now. Without `force`, only when the last copy is
    old enough — so one sitting of edits can be undone as a whole."""
    if not has_drawing(d):
        return None
    last = d.versions.only("created_at", "source", "data").first()
    now = timezone.now()
    if last and not force and now - last.created_at < AUTO_EVERY:
        return None
    if last and not name and last.source == d.source and last.data == d.data:
        return None                    # nothing changed since the last copy
    v = DiagramVersion.objects.create(diagram=d, name=name[:120], title=d.title, source=d.source, data=d.data,
                                      notes=d.notes, preview=d.preview, created_at=now)
    old = d.versions.filter(name="").values_list("pk", flat=True)[KEEP_AUTO:]
    if old:
        DiagramVersion.objects.filter(pk__in=list(old)).delete()
    return v


def bring_back(d, version):
    """Put an earlier version back (keeping what was there as a version first, so this can be undone too)."""
    remember(d, force=True)
    d.title, d.source, d.data, d.notes, d.preview = version.title, version.source, version.data, version.notes, version.preview
    if not d.is_visual:
        d.kind = kind_of_source(d.source, d.kind)
    d.save()
    return d


# ── Templates ───────────────────────────────────────────────────────────────
def _tree(text, *children):
    return {"text": text, "children": list(children)}


def _number(node, counter=None):
    counter = counter if counter is not None else [0]
    node["id"] = "r" if counter[0] == 0 else f"n{counter[0]}"
    counter[0] += 1
    for k in node["children"]:
        _number(k, counter)
    return node


def _mind(root):
    return {"root": _number(root)}


def _board(nodes, edges, est=None):
    """nodes: (key, type, x, y, label, tech[, w, h]); edges: (from, to, label, style)."""
    out = {"nodes": [], "edges": [], "est": est or {}}
    size = {"zone": (300, 220), "note": (200, 110), "client": (140, 72), "mobile": (140, 72)}
    for key, typ, x, y, label, tech, *wh in nodes:
        w, h = wh if wh else size.get(typ, (160, 72))
        out["nodes"].append({"id": key, "type": typ, "x": x, "y": y, "w": w, "h": h, "label": label, "tech": tech, "note": "", "color": ""})
    for i, (a, b, label, style) in enumerate(edges, 1):
        out["edges"].append({"id": f"e{i}", "from": a, "to": b, "label": label, "style": style, "arrow": "end"})
    return out


SYSTEM_NOTES = """## Requirements
**Functional**
-

**Non-functional** — availability, latency, consistency, scale
-

## API
-

## Data model
-

## Bottlenecks & trade-offs
-
"""


def _mindmap_templates():
    return [
        ("blank", gettext_lazy("Blank mind map"), lambda: _mind(_tree(_("Central idea")))),
        ("project", gettext_lazy("Plan a project"), lambda: _mind(_tree(
            _("Project"),
            _tree(_("Goals"), _tree(_("Why we're doing it")), _tree(_("What success looks like"))),
            _tree(_("Scope"), _tree(_("In")), _tree(_("Out"))),
            _tree(_("Milestones"), _tree(_("First version")), _tree(_("Launch"))),
            _tree(_("Risks"), _tree(_("Unknowns")), _tree(_("Dependencies"))),
            _tree(_("People"), _tree(_("Owner")), _tree(_("Helpers"))),
        ))),
        ("sysdesign", gettext_lazy("System design interview"), lambda: _mind(_tree(
            _("Design the system"),
            _tree(_("Requirements"), _tree(_("Functional")), _tree(_("Non-functional")), _tree(_("Out of scope"))),
            _tree(_("Estimates"), _tree(_("Requests per second")), _tree(_("Storage")), _tree(_("Bandwidth"))),
            _tree(_("API"), _tree(_("Endpoints")), _tree(_("Auth"))),
            _tree(_("Data model"), _tree(_("Tables / collections")), _tree(_("SQL or NoSQL?"))),
            _tree(_("High-level design"), _tree(_("Clients")), _tree(_("Services")), _tree(_("Storage"))),
            _tree(_("Deep dives"), _tree(_("Caching")), _tree(_("Sharding")), _tree(_("Queues")), _tree(_("Consistency"))),
            _tree(_("Trade-offs")),
        ))),
        ("learn", gettext_lazy("Learn a topic"), lambda: _mind(_tree(
            _("Topic"),
            _tree(_("What it is")), _tree(_("Why it matters")),
            _tree(_("Key ideas"), _tree(_("Idea 1")), _tree(_("Idea 2"))),
            _tree(_("Practice")), _tree(_("Resources")), _tree(_("Questions")),
        ))),
    ]


def _shapes(nodes, edges):
    """A free drawing: nodes (id, shape, x, y, w, h, label), edges (from, to, label)."""
    return {"nodes": [{"id": i, "shape": shape, "x": x, "y": y, "w": w, "h": h, "label": str(label)} for i, shape, x, y, w, h, label in nodes],
            "edges": [{"id": f"e{k}", "from": a, "to": b, "line": "solid", **({"label": str(label)} if label else {})}
                      for k, (a, b, label) in enumerate(edges, 1)]}


def _drawing_templates():
    return [
        ("blank", gettext_lazy("Blank page"), lambda: {"nodes": [], "edges": []}),
        ("process", gettext_lazy("A process with a decision"), lambda: _shapes([
            ("start", "stadium", 225, 40, 140, 50, _("Start")),
            ("work", "rect", 220, 150, 150, 64, _("Do the work")),
            ("check", "diamond", 215, 280, 160, 100, _("Is it done?")),
            ("end", "stadium", 225, 450, 140, 50, _("Finish")),
            ("fix", "rect", 470, 298, 150, 64, _("Fix what's missing")),
        ], [("start", "work", ""), ("work", "check", ""), ("check", "end", _("Yes")), ("check", "fix", _("No")), ("fix", "work", "")])),
        ("team", gettext_lazy("Team chart"), lambda: _shapes([
            ("lead", "rounded", 290, 40, 170, 64, _("Team lead")),
            ("a", "rounded", 60, 180, 170, 64, _("Design")),
            ("b", "rounded", 290, 180, 170, 64, _("Engineering")),
            ("c", "rounded", 520, 180, 170, 64, _("Marketing")),
        ], [("lead", "a", ""), ("lead", "b", ""), ("lead", "c", "")])),
    ]


def _system_templates():
    return [
        ("blank", gettext_lazy("Blank board"), lambda: {"nodes": [], "edges": [], "est": {}}),
        ("webapp", gettext_lazy("Web app (three tiers)"), lambda: _board([
            ("users", "client", 0, 170, _("Users"), _("Browser & phone")),
            ("dns", "dns", 0, 20, "DNS", ""),
            ("cdn", "cdn", 230, 20, "CDN", _("Static files")),
            ("lb", "lb", 230, 170, _("Load balancer"), ""),
            ("zone", "zone", 450, 70, _("App servers (auto-scaling)"), "", 230, 270),
            ("api1", "service", 485, 120, _("Web / API"), "Django"),
            ("api2", "service", 485, 230, _("Web / API"), "Django"),
            ("cache", "cache", 770, 40, _("Cache"), "Redis"),
            ("db", "db", 770, 170, _("Primary database"), "PostgreSQL"),
            ("replica", "db", 770, 300, _("Read replica"), "PostgreSQL"),
            ("queue", "queue", 485, 400, _("Job queue"), "RabbitMQ"),
            ("worker", "worker", 770, 430, _("Workers"), _("Emails, reports")),
            ("files", "storage", 230, 400, _("File storage"), "S3"),
        ], [
            ("users", "dns", _("look up"), "dashed"), ("users", "cdn", "", "solid"), ("users", "lb", "HTTPS", "solid"),
            ("lb", "api1", "", "solid"), ("lb", "api2", "", "solid"), ("api1", "cache", _("read"), "solid"),
            ("api1", "db", _("write"), "solid"), ("api2", "replica", _("read"), "solid"), ("db", "replica", _("replicate"), "dashed"),
            ("api2", "queue", _("enqueue"), "dashed"), ("queue", "worker", "", "dashed"), ("api2", "files", "", "solid"),
        ], {"dau": 200000, "rpu": 30, "rw": 10, "size": 2, "peak": 3, "years": 3, "copies": 3})),
        ("shortener", gettext_lazy("URL shortener"), lambda: _board([
            ("users", "client", 0, 200, _("Users"), ""),
            ("lb", "lb", 200, 200, _("Load balancer"), ""),
            ("write", "service", 420, 110, _("Shorten API"), "POST /urls"),
            ("read", "service", 420, 290, _("Redirect API"), "GET /{code}"),
            ("keys", "service", 660, 10, _("Key generator"), _("Pre-made unique keys")),
            ("cache", "cache", 660, 200, _("Cache"), _("Redis, hot links")),
            ("store", "nosql", 900, 200, _("URL store"), "DynamoDB / Cassandra"),
            ("events", "stream", 660, 380, _("Click events"), "Kafka"),
            ("stats", "analytics", 900, 380, _("Analytics"), _("Click counts")),
        ], [
            ("users", "lb", "HTTPS", "solid"), ("lb", "write", "", "solid"), ("lb", "read", "", "solid"),
            ("write", "keys", _("take a key"), "solid"), ("write", "store", _("save"), "solid"),
            ("read", "cache", _("look up"), "solid"), ("cache", "store", _("on a miss"), "dashed"),
            ("read", "events", _("click"), "dashed"), ("events", "stats", "", "dashed"),
        ], {"dau": 10000000, "rpu": 10, "rw": 100, "size": 0.5, "peak": 3, "years": 5, "copies": 3})),
        ("chat", gettext_lazy("Chat app"), lambda: _board([
            ("users", "mobile", 0, 200, _("Phone & web apps"), ""),
            ("lb", "lb", 220, 200, _("Load balancer"), _("Sticky sessions")),
            ("chat", "service", 440, 120, _("Chat servers"), "WebSocket"),
            ("presence", "service", 440, 290, _("Presence"), _("Who's online")),
            ("bus", "stream", 670, 120, _("Message bus"), "Kafka"),
            ("msgs", "nosql", 900, 40, _("Messages"), "Cassandra"),
            ("push", "worker", 900, 200, _("Push sender"), ""),
            ("apns", "external", 1120, 200, _("Push services"), "APNs / FCM"),
            ("sessions", "cache", 670, 290, _("Sessions"), "Redis"),
            ("media", "storage", 900, 360, _("Photos & files"), "S3 + CDN"),
        ], [
            ("users", "lb", "WebSocket", "solid"), ("lb", "chat", "", "solid"), ("chat", "bus", _("publish"), "solid"),
            ("bus", "msgs", _("store"), "dashed"), ("bus", "push", _("offline users"), "dashed"), ("push", "apns", "", "solid"),
            ("chat", "presence", "", "solid"), ("presence", "sessions", "", "solid"), ("users", "media", _("upload"), "dashed"),
        ], {"dau": 50000000, "rpu": 40, "rw": 1, "size": 0.2, "peak": 4, "years": 5, "copies": 3})),
    ]


def _mermaid_templates(today):
    d0 = today.isoformat()
    return {
        DiagramKind.FLOWCHART: [
            ("signin", gettext_lazy("Sign-in flow"), """flowchart TD
    A([Start]) --> B[Open the app]
    B --> C{Signed in?}
    C -- Yes --> D[Show the home page]
    C -- No --> E[Sign-in form]
    E --> F{Password right?}
    F -- Yes --> D
    F -- No --> G[Show an error] --> E
    D --> H([End])
"""),
            ("pipeline", gettext_lazy("Deploy pipeline"), """flowchart LR
    push[Push to main] --> ci[Run tests]
    ci --> ok{Green?}
    ok -- No --> fix[Fix and push again] --> push
    ok -- Yes --> build[Build the image]
    build --> stage[Deploy to staging]
    stage --> check{Smoke tests pass?}
    check -- Yes --> prod[Deploy to production]
    check -- No --> rollback[Roll back]
"""),
        ],
        DiagramKind.SEQUENCE: [
            ("payment", gettext_lazy("Paying for an order"), """sequenceDiagram
    autonumber
    actor U as User
    participant App
    participant API
    participant DB as Database
    participant Pay as Payment provider
    U->>App: Tap "Pay"
    App->>API: POST /orders/42/pay
    API->>DB: Save the order (pending)
    API->>Pay: Create a charge
    Pay-->>API: Charge id
    API-->>App: 202 Accepted
    Note over Pay,API: Later, the provider calls back
    Pay->>API: Webhook: charge succeeded
    API->>DB: Mark the order paid
    App-->>U: Show the receipt
"""),
        ],
        DiagramKind.ER: [
            ("shop", gettext_lazy("Shop orders"), """erDiagram
    CUSTOMER ||--o{ ORDER : places
    ORDER ||--|{ ORDER_ITEM : contains
    PRODUCT ||--o{ ORDER_ITEM : "is in"
    CUSTOMER {
        int id PK
        string email UK
        string name
    }
    ORDER {
        int id PK
        int customer_id FK
        datetime created_at
        string status
    }
    ORDER_ITEM {
        int order_id FK
        int product_id FK
        int quantity
        decimal price
    }
    PRODUCT {
        int id PK
        string name
        decimal price
    }
"""),
        ],
        DiagramKind.CLASS: [
            ("accounts", gettext_lazy("Bank accounts"), """classDiagram
    class Account {
        +String owner
        +Decimal balance
        +deposit(amount)
        +withdraw(amount) bool
    }
    class SavingsAccount {
        +Decimal rate
        +addInterest()
    }
    class Transaction {
        +Date date
        +Decimal amount
    }
    Account <|-- SavingsAccount
    Account "1" --> "*" Transaction : records
"""),
        ],
        DiagramKind.STATE: [
            ("order", gettext_lazy("Order status"), """stateDiagram-v2
    [*] --> Pending
    Pending --> Paid: payment received
    Pending --> Cancelled: timed out or cancelled
    Paid --> Shipped
    Shipped --> Delivered
    Delivered --> [*]
    Cancelled --> [*]
"""),
        ],
        DiagramKind.GANTT: [
            ("release", gettext_lazy("Release plan"), f"""gantt
    title Release plan
    dateFormat YYYY-MM-DD
    excludes weekends
    section Design
    Requirements      :done, req, {d0}, 3d
    Mock-ups          :active, ui, after req, 4d
    section Build
    Backend API       :api, after req, 8d
    Frontend          :fe, after ui, 8d
    section Ship
    Testing           :qa, after fe, 4d
    Release           :milestone, after qa, 0d
"""),
        ],
        DiagramKind.TIMELINE: [
            ("career", gettext_lazy("Career path"), f"""timeline
    title Career path
    {today.year - 2} : Junior developer : First production deploy
    {today.year - 1} : Developer : Led the payments rewrite
    {today.year} : Senior developer : Practising system design
    {today.year + 1} : Tech lead
"""),
        ],
        DiagramKind.JOURNEY: [
            ("signup", gettext_lazy("Signing up"), """journey
    title Signing up
    section Discover
      Find the app: 4: Visitor
      Read the home page: 3: Visitor
    section Sign up
      Fill in the form: 2: Visitor
      Confirm the email: 3: User
    section First use
      Add the first entry: 5: User
"""),
        ],
        DiagramKind.C4: [
            ("shop", gettext_lazy("Online shop (context)"), """C4Context
    title Online shop — who and what it talks to
    Person(customer, "Customer", "Browses and buys")
    Person(staff, "Staff", "Packs and ships orders")
    System(shop, "Shop", "Web and phone app, orders, stock")
    System_Ext(pay, "Payment provider", "Cards and mobile wallets")
    System_Ext(mail, "Email service", "Receipts and updates")
    System_Ext(courier, "Courier", "Delivers parcels")
    Rel(customer, shop, "Orders with", "HTTPS")
    Rel(staff, shop, "Manages orders in")
    Rel(shop, pay, "Takes payments via", "HTTPS")
    Rel(shop, mail, "Sends receipts via")
    Rel(shop, courier, "Books deliveries with", "API")
    UpdateLayoutConfig($c4ShapeInRow="3", $c4BoundaryInRow="1")
"""),
            ("containers", gettext_lazy("Inside the app (containers)"), """C4Container
    title Inside the shop
    Person(customer, "Customer")
    System_Boundary(shop, "Shop") {
        Container(web, "Web app", "React", "What customers use")
        Container(api, "API", "Django", "Orders, stock, accounts")
        ContainerDb(db, "Database", "PostgreSQL", "Orders and products")
        Container(worker, "Worker", "Celery", "Emails and reports")
    }
    System_Ext(pay, "Payment provider")
    Rel(customer, web, "Uses", "HTTPS")
    Rel(web, api, "Calls", "JSON")
    Rel(api, db, "Reads and writes", "SQL")
    Rel(api, worker, "Queues jobs for")
    Rel(api, pay, "Charges cards via")
    UpdateLayoutConfig($c4ShapeInRow="3", $c4BoundaryInRow="1")
"""),
        ],
        DiagramKind.ARCHITECTURE: [
            ("cloud", gettext_lazy("Web app in the cloud"), """architecture-beta
    group cloud(cloud)[Cloud]
    group private(server)[Private network] in cloud

    service users(internet)[Users]
    service lb(server)[Load balancer] in cloud
    service app(server)[App servers] in private
    service db(database)[Database] in private
    service cache(database)[Cache] in private
    service files(disk)[File storage] in cloud

    users:R --> L:lb
    lb:R --> L:app
    app:R --> L:db
    app:T --> B:cache
    app:B --> T:files
"""),
        ],
        DiagramKind.BLOCK: [
            ("layers", gettext_lazy("App layers"), """block-beta
    columns 3
    ui["Screens (web and phone)"]:3
    space:3
    api["API"] auth["Sign-in"] jobs["Background jobs"]
    space:3
    db[("Database")] cache[("Cache")] files[("Files")]
    ui --> api
    api --> db
    api --> cache
    jobs --> files
"""),
        ],
        DiagramKind.GITGRAPH: [
            ("flow", gettext_lazy("Feature branch and release"), """gitGraph
    commit id: "start"
    branch develop
    checkout develop
    commit id: "set up"
    branch feature/login
    checkout feature/login
    commit id: "login form"
    commit id: "tests"
    checkout develop
    merge feature/login
    checkout main
    merge develop tag: "v1.0"
    checkout develop
    commit id: "next work"
"""),
        ],
        DiagramKind.PIE: [
            ("week", gettext_lazy("Where my week went"), """pie showData
    title Where my week went (hours)
    "Deep work" : 18
    "Meetings" : 7
    "Email and chat" : 5
    "Learning" : 4
    "Admin" : 3
"""),
        ],
        DiagramKind.QUADRANT: [
            ("priorities", gettext_lazy("What to do first"), """quadrantChart
    title What to do first
    x-axis Little effort --> Lots of effort
    y-axis Small impact --> Big impact
    quadrant-1 Plan it
    quadrant-2 Do it now
    quadrant-3 Maybe later
    quadrant-4 Hand it off
    Fix the sign-in bug: [0.2, 0.9]
    New dashboard: [0.75, 0.8]
    Tidy the README: [0.15, 0.25]
    Rewrite billing: [0.9, 0.4]
    Faster search: [0.45, 0.65]
"""),
            ("skills", gettext_lazy("Skills to work on"), """quadrantChart
    title Skills to work on
    x-axis Weak now --> Strong now
    y-axis Rarely needed --> Often needed
    quadrant-1 Keep sharp
    quadrant-2 Learn next
    quadrant-3 Ignore for now
    quadrant-4 Nice to have
    System design: [0.35, 0.9]
    SQL: [0.7, 0.75]
    Docker: [0.5, 0.55]
    Rust: [0.1, 0.2]
"""),
        ],
        DiagramKind.XYCHART: [
            ("hours", gettext_lazy("Hours worked each month"), f"""xychart-beta
    title "Hours worked in {today.year}"
    x-axis [Jan, Feb, Mar, Apr, May, Jun]
    y-axis "Hours" 0 --> 200
    bar [142, 151, 168, 139, 175, 160]
    line [150, 150, 150, 150, 150, 150]
"""),
        ],
        DiagramKind.SANKEY: [
            ("money", gettext_lazy("Where the money goes"), """sankey-beta

Salary,Rent,30000
Salary,Food,15000
Salary,Savings,20000
Salary,Transport,6000
Salary,Bills,9000
Freelance,Savings,12000
Freelance,Learning,4000
"""),
        ],
    }


BLANK_SOURCE = {
    DiagramKind.FLOWCHART: "flowchart TD\n    A[Start] --> B[Next step]\n",
    DiagramKind.SEQUENCE: "sequenceDiagram\n    participant A\n    participant B\n    A->>B: Hello\n",
    DiagramKind.ER: "erDiagram\n    THING {\n        int id PK\n        string name\n    }\n",
    DiagramKind.CLASS: "classDiagram\n    class Thing {\n        +String name\n    }\n",
    DiagramKind.STATE: "stateDiagram-v2\n    [*] --> Ready\n    Ready --> [*]\n",
    DiagramKind.GANTT: "gantt\n    dateFormat YYYY-MM-DD\n    section Work\n    First task :a1, {today}, 3d\n",
    DiagramKind.TIMELINE: "timeline\n    title My timeline\n    {year} : Something happened\n",
    DiagramKind.JOURNEY: "journey\n    title A journey\n    section Start\n      First step: 3: Me\n",
    DiagramKind.C4: 'C4Context\n    Person(user, "User")\n    System(app, "My system")\n    Rel(user, app, "Uses")\n',
    DiagramKind.ARCHITECTURE: "architecture-beta\n    service web(internet)[Web]\n    service api(server)[API]\n    web:R --> L:api\n",
    DiagramKind.BLOCK: 'block-beta\n    columns 2\n    a["First"] b["Second"]\n',
    DiagramKind.GITGRAPH: 'gitGraph\n    commit id: "start"\n    branch feature\n    commit id: "work"\n    checkout main\n    merge feature\n',
    DiagramKind.PIE: 'pie showData\n    title My chart\n    "One" : 60\n    "Two" : 40\n',
    DiagramKind.QUADRANT: "quadrantChart\n    x-axis Low --> High\n    y-axis Low --> High\n    Item A: [0.3, 0.7]\n",
    DiagramKind.XYCHART: 'xychart-beta\n    x-axis [A, B, C]\n    y-axis "Value" 0 --> 10\n    bar [3, 7, 5]\n',
    DiagramKind.SANKEY: "sankey-beta\n\nFrom,To,10\nFrom,Elsewhere,5\n",
}


def templates(today=None):
    """{kind: [(key, title), …]} for the "New" menu and the gallery."""
    today = today or timezone.localdate()
    out = {DiagramKind.MINDMAP: [(k, t) for k, t, _f in _mindmap_templates()],
           DiagramKind.SYSTEM: [(k, t) for k, t, _f in _system_templates()],
           DiagramKind.DRAWING: [(k, t) for k, t, _f in _drawing_templates()]}
    for kind, items in _mermaid_templates(today).items():
        out[kind] = [("blank", gettext_lazy("Blank"))] + [(k, t) for k, t, _s in items]
    return out


def start(kind, key, today=None):
    """(title, source, data, notes) for a new diagram of `kind` from template `key`."""
    today = today or timezone.localdate()
    kind_label = DiagramKind(kind).label
    if kind == DiagramKind.MINDMAP:
        for k, title, make in _mindmap_templates():
            if k == key:
                return (str(kind_label) if k == "blank" else str(title)), "", make(), ""
        return str(kind_label), "", _mindmap_templates()[0][2](), ""
    if kind == DiagramKind.DRAWING:
        for k, title, make in _drawing_templates():
            if k == key:
                return (str(kind_label) if k == "blank" else str(title)), "", make(), ""
        return str(kind_label), "", _drawing_templates()[0][2](), ""
    if kind == DiagramKind.SYSTEM:
        for k, title, make in _system_templates():
            if k == key:
                return (str(kind_label) if k == "blank" else str(title)), "", make(), SYSTEM_NOTES
        return str(kind_label), "", _system_templates()[0][2](), SYSTEM_NOTES
    for k, title, source in _mermaid_templates(today).get(kind, []):
        if k == key:
            return str(title), source, {}, ""
    blank = BLANK_SOURCE[kind].replace("{today}", today.isoformat()).replace("{year}", str(today.year))
    return str(kind_label), blank, {}, ""
