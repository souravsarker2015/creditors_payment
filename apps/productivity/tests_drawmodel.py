"""The drag-and-drop drawings' model (static/js/drawmodel.js), run under Node:
Mermaid text → shapes → Mermaid text, and the tidy layout."""
import json
import shutil
import subprocess
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.test import SimpleTestCase

MODEL = Path(settings.BASE_DIR) / "static" / "js" / "drawmodel.js"
SCRIPT = r"""
const M = require(process.argv[1]);
const cases = JSON.parse(process.argv[2]), out = {};
for (const [kind, text] of Object.entries(cases)) {
  const g = M.importText(kind, text);
  const again = M.importText(kind, M.toMermaid(kind, g), g);
  const overlaps = [];
  const boxes = g.nodes.filter(n => n.shape !== "container");
  for (const a of boxes) for (const b of boxes) if (a.id < b.id && a.parent === b.parent &&
      a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h) overlaps.push([a.id, b.id]);
  out[kind] = { nodes: g.nodes.map(n => [n.id, n.shape, n.label, n.parent || ""]), edges: g.edges.map(e => [e.from, e.to, e.label || "", e.start || "", e.end || "", e.line]),
                text: M.toMermaid(kind, g), same: JSON.stringify(again.nodes.map(n => [n.id, n.shape, n.label, n.x, n.y]).sort()) === JSON.stringify(g.nodes.map(n => [n.id, n.shape, n.label, n.x, n.y]).sort()),
                sameLinks: again.edges.length === g.edges.length, overlaps, extra: g.extra };
}
console.log(JSON.stringify(out));
"""
CASES = {
    "flowchart": "flowchart LR\n    A([Start]) --> B{Ok?}\n    B -- Yes --> C[Ship]\n    B -->|No| D[[Fix]] & E[(Logs)]\n    D -.-> B\n    C ==> F((Done)) --- G\n"
                 "    subgraph ops [Operations]\n        E\n    end\n    style C fill:#d3f9d8\n    classDef hot fill:#f96\n",
    "state": "stateDiagram-v2\n    [*] --> Idle\n    Idle --> Busy : work\n    Busy --> Idle\n    Busy --> [*]\n    state Busy {\n        [*] --> Step\n    }\n    note right of Idle : waiting\n",
    "class": "classDiagram\n    class Animal {\n        <<abstract>>\n        +name\n        +speak() str\n    }\n    Animal <|-- Dog\n    Dog \"1\" *-- \"4\" Leg : has\n    Dog ..> Food\n",
    "er": "erDiagram\n    CUSTOMER ||--o{ ORDER : places\n    ORDER ||--|{ ITEM : contains\n    CUSTOMER {\n        int id PK\n        string email UK \"login\"\n    }\n",
}


@skipUnless(shutil.which("node"), "Node isn't installed")
class DrawModelTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        run = subprocess.run(["node", "-e", SCRIPT, str(MODEL), json.dumps(CASES)], capture_output=True, text=True, timeout=60)
        assert run.returncode == 0, run.stderr
        cls.out = json.loads(run.stdout)

    def test_round_trips_keep_shapes_and_places(self):
        for kind, r in self.out.items():
            self.assertTrue(r["same"], kind)
            self.assertTrue(r["sameLinks"], kind)
            self.assertEqual(r["overlaps"], [], kind)

    def test_flowchart(self):
        r = self.out["flowchart"]
        shapes = {n[0]: n[1] for n in r["nodes"]}
        self.assertEqual(shapes, {"A": "stadium", "B": "diamond", "C": "rect", "D": "subroutine", "E": "cylinder", "F": "circle", "G": "rect", "ops": "container"})
        self.assertIn(["E", "cylinder", "Logs", "ops"], r["nodes"])
        self.assertIn(["B", "C", "Yes", "", "arrow", "solid"], r["edges"])
        self.assertIn(["D", "B", "", "", "arrow", "dashed"], r["edges"])
        self.assertIn(["C", "F", "", "", "arrow", "thick"], r["edges"])
        self.assertIn(["F", "G", "", "", "none", "solid"], r["edges"])
        self.assertIn("style C fill:#d3f9d8", r["text"])
        self.assertIn("classDef hot fill:#f96", r["text"])
        self.assertIn('subgraph ops ["Operations"]', r["text"])

    def test_state(self):
        r = self.out["state"]
        self.assertIn(["Step", "rounded", "Step", "Busy"], r["nodes"])
        self.assertIn("note right of Idle : waiting", r["text"])
        self.assertIn("Idle --> Busy : work", r["text"])

    def test_class(self):
        r = self.out["class"]
        self.assertIn("Animal <|-- Dog", r["text"])
        self.assertIn('Dog "1" *-- "4" Leg : has', r["text"])
        self.assertIn("<<abstract>>", r["text"])

    def test_er(self):
        r = self.out["er"]
        self.assertIn('CUSTOMER ||--o{ ORDER : "places"', r["text"])
        self.assertIn('string email UK "login"', r["text"])
