"""Diagrams: the starting points (templates), the checks on what a page
saves, and turning a mind map into an outline or tasks.

Mind maps and system design boards are drawn by hand; their shapes live in
`Diagram.data`:

    mind map  {"root": {"id", "text", "children": [...], "collapsed"?, "color"?, "side"?}}
    board     {"nodes": [{"id", "type", "x", "y", "w", "h", "label", "tech", "note", "color"}],
               "edges": [{"id", "from", "to", "label", "style": "solid"|"dashed", "arrow": "end"|"both"|"none"}],
               "est": {back-of-the-envelope numbers}}

Every other kind is Mermaid text in `Diagram.source`, drawn in the browser.
"""
import json
import re
from django.utils import timezone
from django.utils.translation import gettext as _, gettext_lazy

from .models import DiagramKind

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
    elif kind == DiagramKind.SYSTEM:
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
            for key in ("label", "tech", "note"):
                if isinstance(n.get(key), str):
                    n[key] = n[key][:MAX_TEXT * (8 if key == "note" else 1)]
        # a link whose end was deleted is dropped rather than saved broken
        data["edges"] = [e for e in edges if isinstance(e, dict) and e.get("from") in ids and e.get("to") in ids]
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


KIND_WORDS = [
    (r"^(flowchart|graph)\b", DiagramKind.FLOWCHART), (r"^sequenceDiagram\b", DiagramKind.SEQUENCE),
    (r"^erDiagram\b", DiagramKind.ER), (r"^classDiagram\b", DiagramKind.CLASS), (r"^stateDiagram", DiagramKind.STATE),
    (r"^gantt\b", DiagramKind.GANTT), (r"^timeline\b", DiagramKind.TIMELINE), (r"^journey\b", DiagramKind.JOURNEY),
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
    """A mind map as a Markdown list: the centre as a heading, branches indented."""
    text = " ".join(str(node.get("text", "")).split())
    lines = [f"# {text}", ""] if depth == 0 else ["  " * (depth - 1) + f"- {text}"]
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
    picked = kids if kids else [node]
    return [" ".join(str(k.get("text", "")).split())[:300] for k in picked if str(k.get("text", "")).strip()]


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
}


def templates(today=None):
    """{kind: [(key, title), …]} for the "New" menu and the gallery."""
    today = today or timezone.localdate()
    out = {DiagramKind.MINDMAP: [(k, t) for k, t, _f in _mindmap_templates()],
           DiagramKind.SYSTEM: [(k, t) for k, t, _f in _system_templates()]}
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
