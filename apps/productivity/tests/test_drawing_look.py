"""Free drawings as draw.io, Excalidraw and Miro have them: any colour, borders, words lined up and in another
font, see-through and shadow, a link on a shape, locks, new shapes, icons and the pen — and only what the
editor makes gets saved, since it goes back into the page as it is."""
import json
import shutil
import subprocess
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from .. import diagrams
from ..models import Diagram, DiagramKind

PW = "Str0ng-pass-123"


class CleaningTheLookTests(SimpleTestCase):
    def clean(self, node, edge=None):
        data = {"nodes": [{"id": "a", "shape": "rect", "x": 0, "y": 0, "w": 100, "h": 50, "label": "A", **node},
                          {"id": "b", "shape": "rect", "x": 200, "y": 0, "w": 100, "h": 50, "label": "B"}],
                "edges": [{"id": "e", "from": "a", "to": "b", **(edge or {})}]}
        out = diagrams.clean_data(DiagramKind.DRAWING, json.dumps(data))
        return out["nodes"][0], out["edges"][0]

    def test_what_the_editor_makes_is_kept(self):
        look = {"fill": "#ffe3e3", "stroke": "#1c7ed6", "color": "#ffffff", "opacity": 0.6, "sw": 4, "dash": "dotted", "shadow": True,
                "size": 18, "bold": True, "italic": True, "underline": True, "align": "left", "valign": "top", "font": "hand",
                "link": "https://example.com/spec?a=1", "locked": True}
        n, e = self.clean(look, {"color": "#e03131"})
        self.assertEqual({k: n.get(k) for k in look}, look)
        self.assertEqual(e["color"], "#e03131")
        self.assertEqual(self.clean({"fill": "none", "sw": 0})[0]["sw"], 0)
        self.assertEqual(self.clean({"link": "/work/tasks/4/"})[0]["link"], "/work/tasks/4/")
        self.assertEqual(self.clean({"link": "mailto:me@example.com"})[0]["link"], "mailto:me@example.com")

    def test_anything_else_is_dropped(self):
        n, e = self.clean({"fill": 'red" onload="x', "stroke": "url(#x)", "color": "var(--a)", "opacity": 7, "sw": "4", "dash": "wavy",
                           "align": "justify", "font": "Comic", "italic": 0, "link": "javascript:alert(1)", "icon": "<svg>"},
                          {"color": "red;"})
        for key in ("fill", "stroke", "color", "opacity", "sw", "dash", "align", "font", "italic", "link", "icon"):
            self.assertNotIn(key, n, key)
        self.assertNotIn("color", e)
        for bad in ("//evil.example", "https://x.example/\" onclick=", "data:text/html,hi", "https://" + "a" * 600):
            self.assertNotIn("link", self.clean({"link": bad})[0], bad)

    def test_a_pen_stroke(self):
        n = self.clean({"shape": "ink", "pts": [[0, 0], [10.123, 5], [20, 9]], "pw": 100, "ph": 50, "hl": 1})[0]
        self.assertEqual((n["pts"], n["hl"]), ([[0, 0], [10.1, 5], [20, 9]], True))
        for bad in ([[0, "x"]], [[1, 2, 3]], "M0 0", [[0, 0]] * (diagrams.MAX_INK + 1)):
            self.assertNotIn("pts", self.clean({"shape": "ink", "pts": bad})[0])


class DrawingPageTests(TestCase):
    def setUp(self):
        self.me = User.objects.create_superuser("me", "me@example.com", PW)
        self.client.force_login(self.me)

    def test_the_page_brings_icons_and_the_hand_font(self):
        d = Diagram.objects.create(owner=self.me, title="Sketch", kind=DiagramKind.DRAWING, data={"nodes": [], "edges": []})
        html = self.client.get(reverse("work:diagram", args=[d.pk])).content.decode()
        self.assertIn('id="diagram-icons"', html)
        self.assertIn("family=Caveat", html)
        self.assertIn("Keyboard shortcuts", html)
        icons = json.loads(html.split('id="diagram-icons" type="application/json">')[1].split("</script>")[0])
        self.assertGreaterEqual(len(icons), 40)
        self.assertTrue(all(v.startswith("<path") or v.startswith("<circle") or v.startswith("<rect") or v.startswith("<g") for v in icons.values()))
        flow = Diagram.objects.create(owner=self.me, title="Flow", kind=DiagramKind.FLOWCHART, source="flowchart TD\n  A --> B")
        self.assertNotIn('id="diagram-icons"', self.client.get(reverse("work:diagram", args=[flow.pk])).content.decode())

    def test_saving_a_drawing_with_the_new_things(self):
        d = Diagram.objects.create(owner=self.me, title="Sketch", kind=DiagramKind.DRAWING, data={"nodes": [], "edges": []})
        data = {"nodes": [{"id": "s", "shape": "star", "x": 0, "y": 0, "w": 110, "h": 104, "label": "Best", "size": 18, "opacity": 0.8},
                          {"id": "i", "shape": "icon", "icon": "server", "x": 200, "y": 0, "w": 56, "h": 56, "label": "API"},
                          {"id": "p", "shape": "ink", "x": 0, "y": 200, "w": 80, "h": 30, "label": "", "pts": [[0, 0], [40, 20], [80, 5]], "pw": 80, "ph": 30, "sw": 4},
                          {"id": "l", "shape": "container", "lane": True, "x": -20, "y": -40, "w": 400, "h": 300, "label": "Team"}],
                "edges": [{"id": "e", "from": "s", "to": "i", "color": "#2f9e44"}]}
        r = self.client.post(reverse("work:api_diagram_save", args=[d.pk]), {"data": json.dumps(data)})
        self.assertEqual(r.status_code, 200)
        d.refresh_from_db()
        shapes = {n["id"]: n for n in d.data["nodes"]}
        self.assertEqual((shapes["s"]["opacity"], shapes["i"]["icon"], len(shapes["p"]["pts"]), shapes["l"]["lane"]), (0.8, "server", 3, True))


MODEL = Path(settings.BASE_DIR) / "static" / "js" / "drawmodel.js"
SCRIPT = r"""
const M = require(process.argv[1]);
const box = s => M.textBox({ shape: s, w: 200, h: 100 });
const g = { nodes: [
  { id: "a", shape: "star", x: 0, y: 0, w: 110, h: 104, label: "Star", italic: true, underline: true, color: "#ff0000", dash: "dotted", shadow: true, link: "https://x.example" },
  { id: "b", shape: "icon", icon: "server", x: 200, y: 0, w: 56, h: 56, label: "API" },
  { id: "c", shape: "container", lane: true, x: 0, y: 200, w: 400, h: 200, label: "Lane" },
], edges: [{ id: "e", from: "a", to: "b", color: "#2f9e44" }] };
console.log(JSON.stringify({
  shapes: M.shapesOf("drawing"), icons: M.ICON_NAMES.length,
  boxes: { star: box("star"), callout: box("callout"), icon: box("icon"), cube: box("cube") },
  tight: !!M.TIGHT.ink,
  xml: M.toDrawio(g, null, "", n => "PIC" + n.id),
}));
"""


@skipUnless(shutil.which("node"), "Node isn't installed")
class DrawModelShapesTests(SimpleTestCase):
    def setUp(self):
        out = subprocess.run(["node", "-e", SCRIPT, str(MODEL)], capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.r = json.loads(out.stdout)

    def test_the_new_shapes_are_known(self):
        for shape in ("star", "callout", "arrow", "plus", "chevron", "cube", "sticky", "icon", "ink"):
            self.assertIn(shape, self.r["shapes"])          # so a copy-paste keeps them
        self.assertGreaterEqual(self.r["icons"], 40)
        self.assertTrue(self.r["tight"])                    # a pen stroke has no words inside
        self.assertGreater(self.r["boxes"]["icon"]["y"], 99)  # an icon's name goes under it
        self.assertLess(self.r["boxes"]["callout"]["h"], 100)

    def test_draw_io_gets_the_look(self):
        xml = self.r["xml"]
        for part in ("shape=mxgraph.basic.star", "fontStyle=6", "fontColor=#ff0000", "dashPattern=1 4", "shadow=1", "link=https://x.example",
                     "image=data:image/svg+xml,PICb", "swimlane;", "strokeColor=#2f9e44"):
            self.assertIn(part, xml)
