/* Drawings (Productivity): the shapes a drag-and-drop diagram is made of,
   turning Mermaid text into shapes (and back), and laying shapes out.

   No page code here — the editor (drawing.js) uses it in the browser, and it
   runs under Node for the tests. A drawing is a plain object:

     { nodes: [{ id, shape, x, y, w, h, label, fill?, stroke?, size?, parent?,
                 stereo?, attrs?, methods? }],
       edges: [{ id, from, to, label?, line: "solid"|"dashed"|"thick",
                 route?: "curve"|"elbow", start?, end?, fromLabel?, toLabel? }],
       dir: "TD"|"LR"|…, extra: [Mermaid lines kept as they were], front: "" }

   `attrs`/`methods` are text, one line each (a class's fields and methods,
   a table's columns). `start`/`end` name the mark at that end of a link:
   arrow, open, triangle, diamond, odiamond, circle, cross — or, between
   tables, one, zone (zero or one), many (one or more), zmany (zero or more). */
(function (root) {
  "use strict";

  // ── Shapes ────────────────────────────────────────────────────────────────
  // What each kind of diagram can be drawn with: [palette key, shape, w, h, extra].
  var LIBRARY = {
    flowchart: [["terminal", "stadium", 140, 50], ["process", "rect", 150, 64], ["decision", "diamond", 150, 100],
                ["io", "parallelogram", 160, 64], ["subroutine", "subroutine", 150, 64], ["database", "cylinder", 110, 80],
                ["document", "document", 140, 74], ["circle", "circle", 80, 80], ["dcircle", "dcircle", 86, 86],
                ["hexagon", "hexagon", 160, 64], ["manual", "trapezoid2", 160, 64], ["flag", "flag", 150, 60],
                ["rounded", "rounded", 150, 64], ["note", "note", 170, 90], ["text", "text", 140, 40], ["container", "container", 320, 220]],
    state: [["start", "start", 32, 32], ["state", "rounded", 150, 56], ["choice", "diamond", 56, 56], ["fork", "fork", 140, 10],
            ["end", "end", 34, 34], ["note", "note", 170, 90], ["container", "container", 320, 220]],
    "class": [["class", "class", 190, 110], ["interface", "class", 190, 96, { stereo: "interface" }],
              ["abstract", "class", 190, 96, { stereo: "abstract" }], ["enum", "class", 170, 96, { stereo: "enumeration" }], ["note", "note", 170, 90]],
    er: [["entity", "entity", 220, 120]],
  };
  LIBRARY.drawing = [
    ["rect", "rect", 150, 64], ["rounded", "rounded", 150, 64], ["ellipse", "ellipse", 140, 76], ["circle", "circle", 80, 80],
    ["decision", "diamond", 140, 96], ["triangle", "triangle", 110, 90], ["hexagon", "hexagon", 150, 64], ["io", "parallelogram", 160, 64],
    ["trapezoid", "trapezoid", 150, 64], ["database", "cylinder", 110, 80], ["document", "document", 140, 74], ["cloud", "cloud", 160, 96],
    ["actor", "actor", 46, 80], ["terminal", "stadium", 140, 50], ["subroutine", "subroutine", 150, 64], ["note", "note", 170, 90],
    ["text", "text", 140, 40], ["container", "container", 320, 220],
    ["class", "class", 190, 110], ["entity", "entity", 220, 120], ["start", "start", 32, 32], ["end", "end", 34, 34], ["fork", "fork", 140, 10],
    ["picture", "image", 200, 140],
  ];
  // the shapes that hold their words in rows (and grow to fit them)
  var ROWS = { "class": true, entity: true };
  var ROUND = { ellipse: true, circle: true, dcircle: true, start: true, end: true };
  var TIGHT = { start: true, end: true, fork: true, image: true };      // no words inside

  function libraryItem(kind, key) {
    var lib = LIBRARY[kind] || LIBRARY.drawing;
    for (var i = 0; i < lib.length; i++) if (lib[i][0] === key) return lib[i];
    return null;
  }
  function itemForShape(kind, shape) {
    var lib = LIBRARY[kind] || LIBRARY.drawing;
    for (var i = 0; i < lib.length; i++) if (lib[i][1] === shape) return lib[i];
    return libraryItem("drawing", shape) || [shape, shape, 150, 64];
  }
  function shapesOf(kind) {
    var seen = {}, out = [];
    (LIBRARY[kind] || LIBRARY.drawing).forEach(function (it) { if (!seen[it[1]]) { seen[it[1]] = true; out.push(it[1]); } });
    return out;
  }

  // ── Measuring words ───────────────────────────────────────────────────────
  var FONT = "system-ui, -apple-system, 'Segoe UI', Roboto, 'Noto Sans Bengali', sans-serif";
  var ctx = null;
  try { if (typeof document !== "undefined") ctx = document.createElement("canvas").getContext("2d"); } catch (e) { ctx = null; }
  function textWidth(s, size, weight) {
    s = String(s || "");
    if (ctx) { ctx.font = (weight || 400) + " " + (size || 14) + "px " + FONT; return ctx.measureText(s).width; }
    var w = 0;
    for (var i = 0; i < s.length; i++) w += /[ঀ-৿一-鿿]/.test(s[i]) ? 1 : /[A-Z@MWmw]/.test(s[i]) ? 0.72 : 0.55;
    return w * (size || 14);
  }
  /* Words broken into lines no wider than `max` (a word too long for a line is cut). */
  function wrap(text, max, size, weight) {
    var out = [];
    String(text == null ? "" : text).split("\n").forEach(function (para) {
      var line = "";
      para.split(/\s+/).forEach(function (word) {
        if (!word) return;
        var next = line ? line + " " + word : word;
        if (textWidth(next, size, weight) <= max || !line) {
          line = next;
          while (textWidth(line, size, weight) > max && line.length > 1) {     // one long word: cut it
            var cut = line.length - 1;
            while (cut > 1 && textWidth(line.slice(0, cut), size, weight) > max) cut--;
            out.push(line.slice(0, cut)); line = line.slice(cut);
          }
        } else { out.push(line); line = word; }
      });
      out.push(line);
    });
    return out;
  }
  function lines(text) { return String(text || "").split("\n").map(function (l) { return l.replace(/\s+$/, ""); }).filter(function (l) { return l.trim(); }); }

  /* Where the words go inside a shape: the box the label is centred in. */
  function textBox(n) {
    var w = n.w, h = n.h;
    switch (n.shape) {
      case "diamond": return { x: w * 0.2, y: h * 0.2, w: w * 0.6, h: h * 0.6 };
      case "ellipse": case "circle": case "dcircle": return { x: w * 0.15, y: h * 0.15, w: w * 0.7, h: h * 0.7 };
      case "triangle": return { x: w * 0.22, y: h * 0.45, w: w * 0.56, h: h * 0.5 };
      case "hexagon": case "parallelogram": case "parallelogram2": case "trapezoid": case "trapezoid2":
        return { x: Math.min(w / 4, h * 0.4) + 4, y: 4, w: w - 2 * Math.min(w / 4, h * 0.4) - 8, h: h - 8 };
      case "cylinder": var ry = Math.min(h * 0.15, 14); return { x: 6, y: ry * 2, w: w - 12, h: h - ry * 3 };
      case "document": return { x: 8, y: 4, w: w - 16, h: h - Math.min(h * 0.12, 10) * 2 - 4 };
      case "subroutine": return { x: 14, y: 4, w: w - 28, h: h - 8 };
      case "flag": return { x: Math.min(w / 5, 18), y: 4, w: w - Math.min(w / 5, 18) - 8, h: h - 8 };
      case "cloud": return { x: w * 0.18, y: h * 0.22, w: w * 0.64, h: h * 0.6 };
      case "actor": return { x: -50, y: h + 2, w: w + 100, h: 22 };                 // the name goes under the figure
      case "container": return { x: 12, y: 6, w: w - 24, h: 22 };                   // a group's name, top left
      case "note": return { x: 10, y: 8, w: w - 26, h: h - 14 };
      default: return { x: 8, y: 4, w: w - 16, h: h - 8 };
    }
  }
  var ROW_H = 20, HEAD_H = 30;
  /* Class and table rows: [name, type, keys, comment] for a column; the text for a field. */
  function columns(n) {
    return lines(n.attrs).map(function (l) {
      var m = /^\s*(\S+)\s+(\S+)((?:\s+(?:PK|FK|UK)\s*,?)*)\s*(?:"([^"]*)")?\s*$/i.exec(l);
      return m ? { type: m[1], name: m[2], keys: m[3].replace(/[\s,]+/g, " ").trim().toUpperCase(), comment: m[4] || "" }
               : { type: "", name: l.trim(), keys: "", comment: "" };
    });
  }
  /* The height a class or table needs for its rows. */
  function rowsHeight(n) {
    if (n.shape === "entity") return HEAD_H + Math.max(1, columns(n).length) * ROW_H + 6;
    var head = HEAD_H + (n.stereo ? 14 : 0);
    return head + Math.max(1, lines(n.attrs).length) * ROW_H + Math.max(1, lines(n.methods).length) * ROW_H + 12;
  }
  /* A size that fits the words (used for shapes made from text, and after a long label). */
  function fitSize(n, base) {
    var it = base || [null, n.shape, 150, 64], size = n.size || 14, w = it[2], h = it[3];
    if (TIGHT[n.shape]) return { w: n.w || w, h: n.h || h };
    if (ROWS[n.shape]) {
      var all = [n.label].concat(n.shape === "entity" ? columns(n).map(function (c) { return [c.type, c.name, c.keys, c.comment].join("   "); }) : lines(n.attrs).concat(lines(n.methods)));
      var widest = Math.max.apply(null, all.map(function (s) { return textWidth(s, 13, 500); }).concat([textWidth(n.label, 14, 700)]));
      return { w: Math.max(w, Math.min(420, Math.ceil((widest + 32) / 10) * 10)), h: Math.ceil(rowsHeight(n) / 2) * 2 };
    }
    var one = textWidth(String(n.label || "").split("\n").sort(function (a, b) { return b.length - a.length; })[0] || "", size, 500);
    var grow = n.shape === "diamond" ? 1.6 : ROUND[n.shape] ? 1.5 : n.shape === "triangle" || n.shape === "cloud" ? 1.6 : 1;
    w = Math.max(w, Math.min(280, Math.ceil((one * grow + 36) / 10) * 10));
    if (n.shape === "circle" || n.shape === "dcircle") h = w;
    var probe = { shape: n.shape, w: w, h: h }, box = textBox(probe), rows = wrap(n.label, box.w, size, 500).length;
    var need = rows * size * 1.35 + (h - box.h) + 6;
    if (need > h) h = Math.ceil(need / 10) * 10;
    if (n.shape === "circle" || n.shape === "dcircle") { w = h = Math.max(w, h); }
    return { w: w, h: h };
  }

  // ── Mermaid text → a drawing ──────────────────────────────────────────────
  function frontMatter(text) {
    var all = String(text || "").replace(/\r\n?/g, "\n").split("\n"), front = [], i = 0;
    if ((all[0] || "").trim() === "---") {
      var close = -1;
      for (var k = 1; k < all.length; k++) if (all[k].trim() === "---") { close = k; break; }
      if (close > 0) { front = all.slice(0, close + 1); i = close + 1; }
    }
    var rest = all.slice(i);
    // %%{init: …}%% settings stay with the front matter; other %% comments are dropped
    rest = rest.filter(function (l) { if (/^\s*%%\{/.test(l)) { front.push(l); return false; } return !/^\s*%%/.test(l); });
    return { front: front.join("\n"), lines: rest };
  }
  function unquote(s) {
    s = String(s == null ? "" : s).trim();
    if (s.length > 1 && s[0] === '"' && s[s.length - 1] === '"') s = s.slice(1, -1);
    if (s.length > 1 && s[0] === "`" && s[s.length - 1] === "`") s = s.slice(1, -1);
    return s.replace(/<br\s*\/?>/gi, "\n").replace(/#quot;/g, '"').replace(/#35;/g, "#").replace(/#59;/g, ";").replace(/&quot;/g, '"').replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">");
  }
  function empty(kind) { return { kind: kind, nodes: [], edges: [], dir: "", extra: [], front: "" }; }

  /* Flowchart ----------------------------------------------------------------- */
  // shape openers, longest first: [open, close, shape]
  var FLOW_SHAPES = [["(((", ")))", "dcircle"], ["((", "))", "circle"], ["([", "])", "stadium"], ["[[", "]]", "subroutine"],
    ["[(", ")]", "cylinder"], ["[/", "/]", "parallelogram"], ["[\\", "\\]", "parallelogram2"], ["[/", "\\]", "trapezoid"],
    ["[\\", "/]", "trapezoid2"], ["{{", "}}", "hexagon"], ["(", ")", "rounded"], ["[", "]", "rect"], ["{", "}", "diamond"], [">", "]", "flag"]];
  var NEW_SHAPES = { rect: "rect", rounded: "rounded", stadium: "stadium", "rounded-rect": "rounded", subroutine: "subroutine", "fr-rect": "subroutine",
    cyl: "cylinder", cylinder: "cylinder", database: "cylinder", db: "cylinder", circle: "circle", circ: "circle", "dbl-circ": "dcircle",
    "double-circle": "dcircle", diam: "diamond", diamond: "diamond", decision: "diamond", question: "diamond", hex: "hexagon", hexagon: "hexagon",
    "lean-r": "parallelogram", "lean-right": "parallelogram", "in-out": "parallelogram", "lean-l": "parallelogram2", "lean-left": "parallelogram2",
    "trap-b": "trapezoid", trapezoid: "trapezoid", "trap-t": "trapezoid2", "inv-trapezoid": "trapezoid2", manual: "trapezoid2",
    doc: "document", document: "document", tri: "triangle", triangle: "triangle", cloud: "cloud", text: "text", "notch-rect": "note",
    card: "note", odd: "flag", "sm-circ": "start", start: "start", "fr-circ": "end", stop: "end", "f-circ": "end", ellipse: "ellipse",
    stadium2: "stadium", pill: "stadium", terminal: "stadium", "fork": "fork", join: "fork" };
  var ID = /^[A-Za-z0-9_À-￿][\wÀ-￿\-.]*/;
  var FLOW_RESERVED = { end: 1, graph: 1, flowchart: 1, subgraph: 1, style: 1, linkStyle: 1, classDef: 1, "class": 1, click: 1, direction: 1, call: 1, href: 1 };

  /* One node reference at s[i…]: id, then maybe a shape with its label. */
  function flowNodeAt(s, i) {
    var m = ID.exec(s.slice(i));
    if (!m) return null;
    var id = m[0];
    // "A-->B": the id stops before an arrow
    var dash = id.search(/-[-.>=ox]|\.-|==/);
    if (dash > 0) id = id.slice(0, dash);
    id = id.replace(/[-.]+$/, "");
    if (!id) return null;
    var j = i + id.length, out = { id: id, end: j };
    if (s.slice(j, j + 2) === "@{") {             // A@{ shape: doc, label: "Text" }
      var close = s.indexOf("}", j);
      if (close < 0) return null;
      var body = s.slice(j + 2, close), sh = /shape\s*:\s*([\w-]+)/.exec(body), lb = /label\s*:\s*("([^"]*)"|[^,}]+)/.exec(body);
      out.shape = sh ? NEW_SHAPES[sh[1]] || "rect" : "rect";
      if (lb) out.label = unquote(lb[2] != null ? lb[2] : lb[1]);
      out.end = close + 1;
    } else {
      for (var k = 0; k < FLOW_SHAPES.length; k++) {
        var o = FLOW_SHAPES[k];
        if (s.slice(j, j + o[0].length) !== o[0]) continue;
        var from = j + o[0].length, at = -1;
        if (s[from] === '"') {                     // a quoted label may hold anything
          var q = s.indexOf('"', from + 1);
          if (q > 0 && s.slice(q + 1, q + 1 + o[1].length) === o[1]) at = q + 1;
        } else at = s.indexOf(o[1], from);
        if (at < 0) continue;
        // [/text/] and [/text\] share an opener: the closer decides
        out.shape = o[2]; out.label = unquote(s.slice(from, at)); out.end = at + o[1].length;
        break;
      }
    }
    var cls = /^:::([\w-]+)/.exec(s.slice(out.end));
    if (cls) { out.cls = cls[1]; out.end += cls[0].length; }
    return out;
  }
  var LINK_TEXT = /^\s*(<|o|x)?(--|==|-\.)(?![-=.>])\s*([^\s].*?)\s*(-{2,}>|-{3,}|={2,}>|={3,}|\.+->|\.+-|-{2,}o|-{2,}x)(?=[\s"A-Za-z0-9_À-￿]|$)/;
  var LINK = /^\s*(<|o|x)?(-{2,}|={2,}|-\.+-|~{3,})(>|o(?![\wÀ-￿])|x(?![\wÀ-￿]))?\s*(?:\|("[^"]*"|[^|]*)\|)?/;
  function flowLinkAt(s, i) {
    var rest = s.slice(i), m = LINK_TEXT.exec(rest), out;
    if (m) {
      var tail = m[4], endMark = /x$/.test(tail) ? "cross" : /o$/.test(tail) && !/->$/.test(tail) ? "circle" : />$/.test(tail) ? "arrow" : "";
      out = { start: m[1] === "<" ? "arrow" : m[1] === "o" ? "circle" : m[1] === "x" ? "cross" : "", end: endMark,
              line: m[2] === "==" ? "thick" : m[2] === "-." ? "dashed" : "solid", label: unquote(m[3]), len: m[0].length };
      return out;
    }
    m = LINK.exec(rest);
    if (!m || !m[2]) return null;
    var body = m[2];
    if (/^~/.test(body)) return { invisible: true, len: m[0].length };
    out = { start: m[1] === "<" ? "arrow" : m[1] === "o" ? "circle" : m[1] === "x" ? "cross" : "",
            end: m[3] === ">" ? "arrow" : m[3] === "o" ? "circle" : m[3] === "x" ? "cross" : "",
            line: body[0] === "=" ? "thick" : body.indexOf(".") >= 0 ? "dashed" : "solid", label: m[4] != null ? unquote(m[4]) : "", len: m[0].length };
    return out;
  }
  /* A statement: groups of nodes ("A & B") joined by links. Null when it isn't one. */
  function flowStatement(s) {
    var i = 0, groups = [], links = [];
    function skip() { while (i < s.length && /\s/.test(s[i])) i++; }
    function group() {
      var g = [];
      for (;;) {
        skip(); var n = flowNodeAt(s, i); if (!n) return null;
        g.push(n); i = n.end; skip();
        if (s[i] === "&") { i++; continue; }
        return g;
      }
    }
    var g = group(); if (!g) return null;
    groups.push(g);
    for (;;) {
      skip();
      if (i >= s.length) break;
      var l = flowLinkAt(s, i); if (!l) return null;
      i += l.len; links.push(l);
      g = group(); if (!g) return null;
      groups.push(g);
    }
    return { groups: groups, links: links };
  }
  function splitStatements(line) {
    var out = [], cur = "", q = false;
    for (var i = 0; i < line.length; i++) {
      var c = line[i];
      if (c === '"') q = !q;
      if (c === ";" && !q) { out.push(cur); cur = ""; } else cur += c;
    }
    out.push(cur);
    return out.map(function (x) { return x.trim(); }).filter(Boolean);
  }
  function parseFlowchart(text) {
    var fm = frontMatter(text), g = empty("flowchart"), byId = {}, stack = [], seq = 0, styles = {};
    g.front = fm.front;
    function node(ref) {
      var n = byId[ref.id];
      if (!n) {
        n = { id: ref.id, shape: "rect", label: ref.id, x: 0, y: 0, w: 0, h: 0 };
        if (stack.length) n.parent = stack[stack.length - 1];
        byId[ref.id] = n; g.nodes.push(n);
      }
      else if (stack.length && !n.parent && n.shape !== "container") n.parent = stack[stack.length - 1];     // listed inside a group: it's in it
      if (ref.shape) { n.shape = ref.shape; n.label = ref.label != null ? ref.label : n.label; }
      else if (ref.label != null) n.label = ref.label;
      return n;
    }
    var started = false;
    fm.lines.forEach(function (raw) {
      var line = raw.trim();
      if (!line) return;
      if (!started) {
        var h = /^(flowchart|graph)\b\s*(TB|TD|LR|RL|BT)?/i.exec(line);
        if (h) { g.dir = (h[2] || "TD").toUpperCase(); started = true; line = line.slice(h[0].length).trim(); if (!line) return; }
      }
      splitStatements(line).forEach(function (st) {
        var m;
        if ((m = /^subgraph\s+(.+)$/.exec(st))) {
          var head = m[1].trim(), id, label;
          var t = /^([\wÀ-￿-]+)\s*\[\s*(.*?)\s*\]$/.exec(head);
          if (t) { id = t[1]; label = unquote(t[2]); }
          else if (/^"/.test(head)) { label = unquote(head); id = "sg" + (++seq); }
          else if (/^[\wÀ-￿-]+$/.test(head)) { id = head; label = head; }
          else { label = head; id = "sg" + (++seq); }
          var c = byId[id] || { id: id, x: 0, y: 0, w: 0, h: 0 };
          c.shape = "container"; c.label = label;
          if (!byId[id]) { if (stack.length) c.parent = stack[stack.length - 1]; byId[id] = c; g.nodes.push(c); }
          stack.push(id);
          return;
        }
        if (st === "end" && stack.length) { stack.pop(); return; }
        if (/^direction\s+(TB|TD|LR|RL|BT)$/i.test(st)) return;               // a group's own direction: the drawing decides
        if ((m = /^style\s+([\wÀ-￿-]+)\s+(.+)$/.exec(st))) {
          var props = {}, other = [];
          m[2].split(",").forEach(function (p) {
            var kv = /^\s*([\w-]+)\s*:\s*(.+?)\s*$/.exec(p);
            if (kv && (kv[1] === "fill" || kv[1] === "stroke") && /^#[0-9a-f]{3,8}$|^none$/i.test(kv[2])) props[kv[1]] = kv[2];
            else other.push(p.trim());
          });
          styles[m[1]] = props;
          if (other.length) g.extra.push("style " + m[1] + " " + other.join(","));
          return;
        }
        if (/^(classDef|class|linkStyle|click|accTitle|accDescr|title)\b/.test(st)) { g.extra.push(st); return; }
        var s = flowStatement(st);
        if (!s) { g.extra.push(st); return; }
        var made = s.groups.map(function (grp) { return grp.map(node); });
        s.groups.forEach(function (grp) { grp.forEach(function (r) { if (r.cls) g.extra.push("class " + r.id + " " + r.cls); }); });
        s.links.forEach(function (l, k) {
          made[k].forEach(function (a) {
            made[k + 1].forEach(function (b) {
              if (l.invisible) { g.extra.push(a.id + " ~~~ " + b.id); return; }
              var e = { id: "e" + (g.edges.length + 1), from: a.id, to: b.id, line: l.line };
              if (l.label) e.label = l.label;
              if (l.start) e.start = l.start;
              e.end = l.end || "none";
              g.edges.push(e);
            });
          });
        });
      });
    });
    Object.keys(styles).forEach(function (id) { var n = byId[id]; if (!n) return; if (styles[id].fill) n.fill = styles[id].fill; if (styles[id].stroke) n.stroke = styles[id].stroke; });
    return g;
  }

  /* State diagram ------------------------------------------------------------- */
  function parseState(text) {
    var fm = frontMatter(text), g = empty("state"), byId = {}, stack = [], noteOpen = null, seq = 0;
    g.front = fm.front;
    function scope() { return stack.length ? stack[stack.length - 1] : ""; }
    function state(id, ends) {
      if (id === "[*]") {                              // the start (or end) of this group
        var key = (ends === "end" ? "end" : "start") + (scope() ? "_" + scope() : "");
        if (!byId[key]) { var p = { id: key, shape: ends === "end" ? "end" : "start", label: "", x: 0, y: 0, w: 0, h: 0 }; if (scope()) p.parent = scope(); byId[key] = p; g.nodes.push(p); }
        return byId[key];
      }
      if (!byId[id]) { var n = { id: id, shape: "rounded", label: id, x: 0, y: 0, w: 0, h: 0 }; if (scope()) n.parent = scope(); byId[id] = n; g.nodes.push(n); }
      return byId[id];
    }
    var started = false;
    fm.lines.forEach(function (raw) {
      var line = raw.trim(), m;
      if (noteOpen) {
        if (/^end\s+note$/i.test(line)) { noteOpen = null; return; }
        noteOpen.label += (noteOpen.label ? "\n" : "") + line; return;
      }
      if (!line) return;
      if (!started && /^stateDiagram(-v2)?\b/.test(line)) { started = true; return; }
      if ((m = /^direction\s+(TB|TD|LR|RL|BT)$/i.exec(line))) { if (!stack.length) g.dir = m[1].toUpperCase(); return; }
      if (line === "}") { stack.pop(); return; }
      if (line === "--") return;                                    // parallel regions: drawn side by side anyway
      if ((m = /^state\s+(?:"([^"]*)"\s+as\s+([\wÀ-￿-]+)|([\wÀ-￿-]+))\s*(<<(choice|fork|join)>>)?\s*(\{)?\s*$/.exec(line))) {
        var id = m[2] || m[3], n = state(id);
        if (m[1] != null) n.label = unquote(m[1]);
        if (m[5]) { n.shape = m[5] === "choice" ? "diamond" : "fork"; n.label = m[5] === "choice" ? "" : n.label; }
        if (m[6]) { n.shape = "container"; stack.push(id); }
        return;
      }
      if ((m = /^state\s+"([^"]*)"\s+as\s+([\wÀ-￿-]+)\s*\{?\s*$/.exec(line))) { return; }
      if ((m = /^note\s+(left|right)\s+of\s+([\wÀ-￿-]+)\s*(?::\s*(.*))?$/i.exec(line))) {
        var target = state(m[2]), note = { id: "note" + (++seq), shape: "note", label: m[3] != null ? m[3].trim() : "", x: 0, y: 0, w: 0, h: 0, side: m[1].toLowerCase() };
        if (target.parent) note.parent = target.parent;
        g.nodes.push(note); byId[note.id] = note;
        g.edges.push({ id: "e" + (g.edges.length + 1), from: note.id, to: target.id, line: "dashed", end: "none", note: true });
        if (m[3] == null) noteOpen = note;
        return;
      }
      if ((m = /^(\[\*\]|[\wÀ-￿-]+)\s*-->\s*(\[\*\]|[\wÀ-￿-]+)\s*(?::\s*(.*))?$/.exec(line))) {
        var a = state(m[1], "start"), b = state(m[2], "end"), e = { id: "e" + (g.edges.length + 1), from: a.id, to: b.id, line: "solid" };
        if (m[3]) e.label = m[3].trim();
        g.edges.push(e); return;
      }
      if ((m = /^([\wÀ-￿-]+)\s*:\s*(.+)$/.exec(line))) {
        var s = state(m[1]);
        s.attrs = (s.attrs ? s.attrs + "\n" : "") + m[2].trim();
        return;
      }
      if ((m = /^([\wÀ-￿-]+)$/.exec(line))) { state(m[1]); return; }
      g.extra.push(line);
    });
    return g;
  }

  /* Class diagram ------------------------------------------------------------- */
  var CLASS_REL = /^([\wÀ-￿~`.-]+)\s*(?:"([^"]*)")?\s*(<\||\*|o|<)?(--|\.\.)(\|>|\*|o|>)?\s*(?:"([^"]*)")?\s*([\wÀ-￿~`.-]+)\s*(?::\s*(.*))?$/;
  var CLASS_MARK = { "<|": "triangle", "|>": "triangle", "*": "diamond", o: "odiamond", "<": "arrow", ">": "arrow" };
  function parseClass(text) {
    var fm = frontMatter(text), g = empty("class"), byId = {}, open = null, seq = 0;
    g.front = fm.front;
    function cls(name) {
      name = name.replace(/`/g, "");
      if (!byId[name]) { var n = { id: name, shape: "class", label: name.replace(/~([^~]*)~/g, "<$1>"), attrs: "", methods: "", x: 0, y: 0, w: 0, h: 0 }; byId[name] = n; g.nodes.push(n); }
      return byId[name];
    }
    function member(c, text) {
      text = text.trim(); if (!text) return;
      var st = /^<<\s*(.+?)\s*>>$/.exec(text);
      if (st) { c.stereo = st[1]; return; }
      if (/\)/.test(text) && /\(/.test(text)) c.methods = (c.methods ? c.methods + "\n" : "") + text;
      else c.attrs = (c.attrs ? c.attrs + "\n" : "") + text;
    }
    var started = false;
    fm.lines.forEach(function (raw) {
      var line = raw.trim(), m;
      if (!line) return;
      if (open) { if (line === "}") { open = null; return; } member(open, line); return; }
      if (!started && /^classDiagram(-v2)?\b/.test(line)) { started = true; return; }
      if ((m = /^direction\s+(TB|TD|LR|RL|BT)$/i.exec(line))) { g.dir = m[1].toUpperCase(); return; }
      if ((m = /^class\s+([\wÀ-￿~`.-]+)\s*(?:\["([^"]*)"\])?\s*(?::::[\w-]+)?\s*(\{)?\s*(\})?$/.exec(line))) {
        var c = cls(m[1]);
        if (m[2]) c.label = m[2];
        if (m[3] && !m[4]) open = c;
        return;
      }
      if ((m = /^<<\s*(.+?)\s*>>\s+([\wÀ-￿~`.-]+)$/.exec(line))) { cls(m[2]).stereo = m[1]; return; }
      if ((m = /^note\s+for\s+([\wÀ-￿~`.-]+)\s+"([^"]*)"$/.exec(line))) {
        var target = cls(m[1]), note = { id: "note" + (++seq), shape: "note", label: unquote(m[2]).replace(/\\n/g, "\n"), x: 0, y: 0, w: 0, h: 0 };
        g.nodes.push(note);
        g.edges.push({ id: "e" + (g.edges.length + 1), from: note.id, to: target.id, line: "dashed", end: "none", note: true });
        return;
      }
      if ((m = /^note\s+"([^"]*)"$/.exec(line))) { g.nodes.push({ id: "note" + (++seq), shape: "note", label: unquote(m[1]).replace(/\\n/g, "\n"), x: 0, y: 0, w: 0, h: 0 }); return; }
      if ((m = CLASS_REL.exec(line)) && (m[3] || m[5] || m[4])) {
        var a = cls(m[1]), b = cls(m[7]), e = { id: "e" + (g.edges.length + 1), from: a.id, to: b.id, line: m[4] === ".." ? "dashed" : "solid" };
        if (m[3]) e.start = CLASS_MARK[m[3]];
        if (m[5]) e.end = CLASS_MARK[m[5]];
        if (m[2]) e.fromLabel = m[2];
        if (m[6]) e.toLabel = m[6];
        if (m[8]) e.label = m[8].trim();
        g.edges.push(e); return;
      }
      if ((m = /^([\wÀ-￿~`.-]+)\s*:\s*(.+)$/.exec(line))) { member(cls(m[1]), m[2]); return; }
      if (/^(classDef|cssClass|style|click|callback|link|namespace|\})/.test(line)) { g.extra.push(line); return; }
      g.extra.push(line);
    });
    return g;
  }

  /* ER diagram ----------------------------------------------------------------- */
  var ER_LEFT = { "||": "one", "|o": "zone", "}|": "many", "}o": "zmany" }, ER_RIGHT = { "||": "one", "o|": "zone", "|{": "many", "o{": "zmany" };
  var ER_REL = /^([\wÀ-￿-]+|"[^"]+")\s*(\|\||\|o|\}\||\}o)(--|\.\.)(\|\||o\||\|\{|o\{)\s*([\wÀ-￿-]+|"[^"]+")\s*:\s*(.*)$/;
  function parseER(text) {
    var fm = frontMatter(text), g = empty("er"), byId = {}, open = null;
    g.front = fm.front;
    function ent(name, label) {
      name = unquote(name);
      if (!byId[name]) { var n = { id: name, shape: "entity", label: name, attrs: "", x: 0, y: 0, w: 0, h: 0 }; byId[name] = n; g.nodes.push(n); }
      if (label) byId[name].label = label;
      return byId[name];
    }
    var started = false;
    fm.lines.forEach(function (raw) {
      var line = raw.trim(), m;
      if (!line) return;
      if (open) { if (line === "}") { open = null; return; } open.attrs = (open.attrs ? open.attrs + "\n" : "") + line; return; }
      if (!started && /^erDiagram\b/.test(line)) { started = true; return; }
      if ((m = /^direction\s+(TB|TD|LR|RL|BT)$/i.exec(line))) { g.dir = m[1].toUpperCase(); return; }
      if ((m = /^([\wÀ-￿-]+|"[^"]+")\s*(?:\[\s*("?)([^\]"]*)\2\s*\])?\s*\{\s*(\})?$/.exec(line))) {
        var e0 = ent(m[1], m[3]); if (!m[4]) open = e0; return;
      }
      if ((m = ER_REL.exec(line))) {
        var a = ent(m[1]), b = ent(m[5]);
        g.edges.push({ id: "e" + (g.edges.length + 1), from: a.id, to: b.id, start: ER_LEFT[m[2]], end: ER_RIGHT[m[4]],
                       line: m[3] === ".." ? "dashed" : "solid", label: unquote(m[6]) });
        return;
      }
      if ((m = /^([\wÀ-￿-]+|"[^"]+")\s*(?:\[\s*("?)([^\]"]*)\2\s*\])?$/.exec(line))) { ent(m[1], m[3]); return; }
      g.extra.push(line);
    });
    return g;
  }

  var PARSERS = { flowchart: parseFlowchart, state: parseState, "class": parseClass, er: parseER };
  function fromMermaid(kind, text) {
    var g = PARSERS[kind](text);
    g.nodes.forEach(function (n) {
      var s = fitSize(n, itemForShape(kind, n.shape));
      if (n.shape === "container") s = { w: 0, h: 0 };
      if (n.shape === "diamond" && kind === "state") s = { w: 56, h: 56 };
      n.w = s.w; n.h = s.h;
    });
    return g;
  }

  // ── A drawing → Mermaid text ──────────────────────────────────────────────
  var SAFE = /^[A-Za-z_][A-Za-z0-9_]*$/;
  function mmText(s) { return String(s == null ? "" : s).replace(/"/g, "#quot;").replace(/\n/g, "<br>"); }
  /* Mermaid names for the shapes: their own id when it's a plain word, else n1, n2… */
  function names(nodes, reserved) {
    var out = {}, used = {}, k = 0;
    nodes.forEach(function (n) { if (SAFE.test(n.id) && n.id[0] !== "_" && !reserved[n.id] && !reserved[n.id.toLowerCase()] && !used[n.id]) { out[n.id] = n.id; used[n.id] = true; } });
    nodes.forEach(function (n) { if (out[n.id]) return; do { k++; } while (used["n" + k]); out[n.id] = "n" + k; used["n" + k] = true; });
    return out;
  }
  function childrenOf(g) {
    var kids = {}, ids = {};
    g.nodes.forEach(function (n) { ids[n.id] = n; });
    g.nodes.forEach(function (n) { var p = n.parent && ids[n.parent] && ids[n.parent].shape === "container" ? n.parent : ""; (kids[p] = kids[p] || []).push(n); });
    return kids;
  }
  function withFront(g, body) { return (g.front ? g.front + "\n" : "") + body.join("\n") + "\n"; }
  var FLOW_WRAP = { rect: ['["', '"]'], rounded: ['("', '")'], stadium: ['(["', '"])'], subroutine: ['[["', '"]]'], cylinder: ['[("', '")]'],
    circle: ['(("', '"))'], dcircle: ['((("', '")))'], diamond: ['{"', '"}'], hexagon: ['{{"', '"}}'], parallelogram: ['[/"', '"/]'],
    parallelogram2: ['[\\"', '"\\]'], trapezoid: ['[/"', '"\\]'], trapezoid2: ['[\\"', '"/]'], flag: ['>"', '"]'] };
  var FLOW_NEW = { document: "doc", triangle: "tri", cloud: "cloud", ellipse: "stadium", start: "sm-circ", end: "fr-circ", fork: "fork", actor: "rect", "class": "rect", entity: "rect" };
  function flowLink(e) {
    var thick = e.line === "thick", dashed = e.line === "dashed";
    var end = e.end === undefined ? "arrow" : e.end, start = e.start || "";
    var mark = function (m, left) { return m === "arrow" || m === "open" || m === "triangle" ? (left ? "<" : ">") : m === "circle" || m === "odiamond" ? "o" : m === "cross" ? "x" : ""; };
    var a = mark(start, true), b = mark(end, false);
    var body = dashed ? (b ? "-.-" : "-.-") : thick ? (b ? "==" : "===") : (b ? "--" : "---");
    if (a && !b) body = dashed ? "-.-" : thick ? "===" : "---";
    return a + body + b;
  }
  function toFlowchart(g) {
    var nm = names(g.nodes, FLOW_RESERVED), kids = childrenOf(g), out = ["flowchart " + (g.dir || "TD")], styles = [];
    function emit(list, pad) {
      (list || []).forEach(function (n) {
        if (n.shape === "container") {
          out.push(pad + "subgraph " + nm[n.id] + ' ["' + mmText(n.label || " ") + '"]');
          emit(kids[n.id], pad + "    ");
          out.push(pad + "end");
        } else if (FLOW_WRAP[n.shape]) out.push(pad + nm[n.id] + FLOW_WRAP[n.shape][0] + mmText(n.label) + FLOW_WRAP[n.shape][1]);
        else if (n.shape === "note" || n.shape === "text") out.push(pad + nm[n.id] + '["' + mmText(n.label) + '"]');
        else out.push(pad + nm[n.id] + "@{ shape: " + (FLOW_NEW[n.shape] || "rect") + ', label: "' + mmText(n.label) + '" }');
        var fill = n.fill || (n.shape === "note" ? "#fff4bf" : n.shape === "text" ? "none" : ""), stroke = n.stroke || (n.shape === "note" ? "#f0c36d" : n.shape === "text" ? "none" : "");
        if (fill || stroke) styles.push("    style " + nm[n.id] + " " + [fill && "fill:" + fill, stroke && "stroke:" + stroke].filter(Boolean).join(","));
      });
    }
    emit(kids[""], "    ");
    g.edges.forEach(function (e) {
      if (!nm[e.from] || !nm[e.to]) return;
      var from = e.from, to = e.to, end = e.end === undefined ? "arrow" : e.end, start = e.start || "";
      if (start && start !== "none" && (!end || end === "none")) { from = e.to; to = e.from; end = start; start = ""; }   // only "<--": the other way round
      if (start !== end) start = "";                                         // Mermaid draws both ends alike, or only the end
      var link = flowLink({ line: e.line, start: start, end: end });
      out.push("    " + nm[from] + " " + link + (e.label ? '|"' + mmText(e.label) + '"|' : "") + " " + nm[to]);
    });
    (g.extra || []).forEach(function (l) { out.push("    " + l); });
    return withFront(g, out.concat(styles));
  }
  var STATE_RESERVED = { state: 1, note: 1, end: 1, direction: 1, classDef: 1, "class": 1, as: 1 };
  function toState(g) {
    var real = g.nodes.filter(function (n) { return n.shape !== "start" && n.shape !== "end" && n.shape !== "note"; });
    var nm = names(real, STATE_RESERVED), kids = childrenOf(g), ids = {}, out = ["stateDiagram-v2"];
    g.nodes.forEach(function (n) { ids[n.id] = n; if (n.shape === "start" || n.shape === "end") nm[n.id] = "[*]"; });
    if (g.dir && g.dir !== "TD" && g.dir !== "TB") out.push("    direction " + g.dir);
    function scopeOf(n) { return n && n.parent && ids[n.parent] && ids[n.parent].shape === "container" ? n.parent : ""; }
    var notes = [], byScope = {};
    g.edges.forEach(function (e) {
      var a = ids[e.from], b = ids[e.to]; if (!a || !b) return;
      if (a.shape === "note" || b.shape === "note") { var note = a.shape === "note" ? a : b, other = note === a ? b : a; if (other.shape !== "note" && nm[other.id] !== "[*]") notes.push([note, other]); return; }
      // a link stays inside a group only when both ends are in it; [*] belongs to its group
      var sa = scopeOf(a), sb = scopeOf(b), at = sa === sb ? sa : "";
      if (sa !== sb && (nm[a.id] === "[*]" || nm[b.id] === "[*]")) at = nm[a.id] === "[*]" ? sa : sb;
      (byScope[at] = byScope[at] || []).push(e);
    });
    function emit(scope, pad) {
      (kids[scope] || []).forEach(function (n) {
        if (n.shape === "start" || n.shape === "end" || n.shape === "note") return;
        var name = nm[n.id], label = String(n.label || "").replace(/\n/g, " ");
        if (n.shape === "container") {
          out.push(pad + (label && label !== name ? 'state "' + label.replace(/"/g, "'") + '" as ' + name : "state " + name) + " {");
          emit(n.id, pad + "    ");
          out.push(pad + "}");
          return;
        }
        if (n.shape === "diamond") { out.push(pad + "state " + name + " <<choice>>"); return; }
        if (n.shape === "fork") { out.push(pad + "state " + name + " <<fork>>"); return; }
        if (label && label !== name) out.push(pad + 'state "' + label.replace(/"/g, "'") + '" as ' + name);
        else if (!g.edges.some(function (e) { return e.from === n.id || e.to === n.id; })) out.push(pad + name);
        lines(n.attrs).forEach(function (l) { out.push(pad + name + " : " + l.replace(/^\s+/, "")); });
      });
      (byScope[scope] || []).forEach(function (e) { out.push(pad + nm[e.from] + " --> " + nm[e.to] + (e.label ? " : " + String(e.label).replace(/\n/g, " ") : "")); });
    }
    emit("", "    ");
    notes.forEach(function (p) {
      var note = p[0], target = p[1], side = note.x + note.w / 2 < target.x + target.w / 2 ? "left" : "right";
      var body = lines(note.label);
      if (body.length <= 1) out.push("    note " + side + " of " + nm[target.id] + " : " + (body[0] || ""));
      else { out.push("    note " + side + " of " + nm[target.id]); body.forEach(function (l) { out.push("        " + l); }); out.push("    end note"); }
    });
    (g.extra || []).forEach(function (l) { out.push("    " + l); });
    return withFront(g, out);
  }
  var CLASS_RESERVED = { "class": 1, note: 1, direction: 1, classDef: 1, namespace: 1, style: 1, click: 1, link: 1, callback: 1 };
  var CLASS_OUT_L = { triangle: "<|", diamond: "*", odiamond: "o", arrow: "<", open: "<" }, CLASS_OUT_R = { triangle: "|>", diamond: "*", odiamond: "o", arrow: ">", open: ">" };
  function className(n, k) { var s = String(n.label || "").replace(/<([^<>]*)>/g, "~$1~").trim(); return /^[A-Za-z_][\w]*(~[\w,\s]*~)?$/.test(s) && !CLASS_RESERVED[s] ? s : k; }
  function toClass(g) {
    var out = ["classDiagram"], nm = {}, used = {}, k = 0, ids = {};
    if (g.dir && g.dir !== "TD" && g.dir !== "TB") out.push("    direction " + g.dir);
    var classes = g.nodes.filter(function (n) { return n.shape !== "note"; });
    classes.forEach(function (n) { ids[n.id] = n; var s = className(n, ""); if (s && !used[s.replace(/~.*$/, "")]) { nm[n.id] = s; used[s.replace(/~.*$/, "")] = true; } });
    classes.forEach(function (n) { if (nm[n.id]) return; do { k++; } while (used["C" + k]); nm[n.id] = "C" + k; used["C" + k] = true; });
    var bare = function (id) { return nm[id].replace(/~.*$/, ""); };
    classes.forEach(function (n) {
      var name = nm[n.id], label = String(n.label || "").trim(), own = className(n, "") === name;
      var head = "    class " + name + (own || !label ? "" : '["' + label.replace(/"/g, "'") + '"]');
      var body = [];
      if (n.stereo) body.push("        <<" + n.stereo + ">>");
      lines(n.attrs).concat(lines(n.methods)).forEach(function (l) { body.push("        " + l.trim()); });
      if (body.length) { out.push(head + " {"); out = out.concat(body); out.push("    }"); } else out.push(head);
    });
    g.edges.forEach(function (e) {
      var a = g.nodes.filter(function (n) { return n.id === e.from; })[0], b = g.nodes.filter(function (n) { return n.id === e.to; })[0];
      if (!a || !b) return;
      if (a.shape === "note" || b.shape === "note") return;
      var line = e.line === "dashed" ? ".." : "--";
      out.push("    " + bare(a.id) + (e.fromLabel ? ' "' + e.fromLabel.replace(/"/g, "'") + '"' : "") + " " + (CLASS_OUT_L[e.start] || "") + line + (CLASS_OUT_R[e.end] || "") +
               (e.toLabel ? ' "' + e.toLabel.replace(/"/g, "'") + '"' : "") + " " + bare(b.id) + (e.label ? " : " + String(e.label).replace(/\n/g, " ") : ""));
    });
    g.nodes.forEach(function (n) {
      if (n.shape !== "note") return;
      var link = g.edges.filter(function (e) { return (e.from === n.id && ids[e.to]) || (e.to === n.id && ids[e.from]); })[0];
      var text = String(n.label || "").replace(/"/g, "'").replace(/\n/g, "\\n");
      out.push(link ? '    note for ' + bare(link.from === n.id ? link.to : link.from) + ' "' + text + '"' : '    note "' + text + '"');
    });
    (g.extra || []).forEach(function (l) { out.push("    " + l); });
    return withFront(g, out);
  }
  var ER_OUT_L = { one: "||", zone: "|o", many: "}|", zmany: "}o" }, ER_OUT_R = { one: "||", zone: "o|", many: "|{", zmany: "o{" };
  function toER(g) {
    var out = ["erDiagram"], nm = {}, used = {}, k = 0;
    g.nodes.forEach(function (n) {
      var s = String(n.label || "").trim();
      if (/^[A-Za-z_][\w-]*$/.test(s) && !used[s]) { nm[n.id] = s; used[s] = true; }
    });
    g.nodes.forEach(function (n) { if (nm[n.id]) return; do { k++; } while (used["T" + k]); nm[n.id] = "T" + k; used["T" + k] = true; });
    g.nodes.forEach(function (n) {
      var name = nm[n.id], label = String(n.label || "").trim(), head = "    " + name + (label && label !== name ? '["' + label.replace(/"/g, "'") + '"]' : "");
      var cols = columns(n).map(function (c) {
        if (!c.type) return null;
        var name2 = c.name.replace(/[^\w\-\[\]()*]/g, "_");
        return "        " + c.type.replace(/[^\w\-\[\]()*]/g, "_") + " " + name2 + (c.keys ? " " + c.keys.split(" ").join(", ") : "") + (c.comment ? ' "' + c.comment.replace(/"/g, "'") + '"' : "");
      }).filter(Boolean);
      if (cols.length) { out.push(head + " {"); out = out.concat(cols); out.push("    }"); } else out.push(head);
    });
    g.edges.forEach(function (e) {
      if (!nm[e.from] || !nm[e.to]) return;
      out.push("    " + nm[e.from] + " " + (ER_OUT_L[e.start] || "||") + (e.line === "dashed" ? ".." : "--") + (ER_OUT_R[e.end] || "o{") + " " + nm[e.to] +
               ' : "' + String(e.label || "").replace(/"/g, "'").replace(/\n/g, " ") + '"');
    });
    (g.extra || []).forEach(function (l) { out.push("    " + l); });
    return withFront(g, out);
  }
  var WRITERS = { flowchart: toFlowchart, state: toState, "class": toClass, er: toER, drawing: toFlowchart };
  function toMermaid(kind, g) { return (WRITERS[kind] || toFlowchart)(g); }

  // ── Laying shapes out ─────────────────────────────────────────────────────
  /* A tidy layered layout (the way flowcharts are drawn): links point one way,
     each shape in a row by its distance from the start, rows ordered to cross
     as few links as possible. Groups (containers) are laid out inside first and
     then placed as one big shape. `dir` is TD, LR, BT or RL. */
  var GAP = { rank: 70, node: 46, pad: 24, head: 30 };
  function layout(g, dir) {
    dir = (dir || g.dir || "TD").toUpperCase();
    var across = dir === "LR" || dir === "RL", ids = {}, kids = childrenOf(g), virt = {}, chains = [], vseq = 0;
    g.nodes.forEach(function (n) { ids[n.id] = n; });
    g.edges.forEach(function (e) { delete e.pts; delete e.auto; });
    function box(id) { return ids[id] || virt[id]; }
    // which top shape of a group a shape is in (for links between groups)
    function under(n, scope) { var cur = n; while (cur && (cur.parent || "") !== scope) cur = cur.parent ? ids[cur.parent] : null; return cur; }
    function place(scope) {
      var list = kids[scope] || [];
      list.forEach(function (n) { if (n.shape === "container") place(n.id); });
      if (!list.length) return { w: 0, h: 0 };
      var idx = {}, out = {}, inn = {};
      list.forEach(function (n, i) { idx[n.id] = i; out[n.id] = []; inn[n.id] = []; });
      var seen = {};
      g.edges.forEach(function (e) {
        var a = ids[e.from], b = ids[e.to]; if (!a || !b) return;
        var x = under(a, scope), y = under(b, scope);
        if (e.note || !x || !y || x === y || seen[x.id + ">" + y.id]) return;          // notes are put beside their shape afterwards
        seen[x.id + ">" + y.id] = true;
        out[x.id].push(y.id); inn[y.id].push(x.id);
      });
      // turn links that close a loop around, so every link points forward
      var state = {}, order = [];
      function visit(id) {
        state[id] = 1;
        out[id].slice().forEach(function (to) {
          if (state[to] === 1) { out[id].splice(out[id].indexOf(to), 1); inn[to].splice(inn[to].indexOf(id), 1); out[to].push(id); inn[id].push(to); }
          else if (!state[to]) visit(to);
        });
        state[id] = 2; order.push(id);
      }
      var starts = list.filter(function (n) { return !inn[n.id].length; }).map(function (n) { return n.id; });
      starts.concat(list.map(function (n) { return n.id; })).forEach(function (id) { if (!state[id]) visit(id); });
      // rows: the longest way in from a start
      var rank = {};
      order.reverse().forEach(function (id) { rank[id] = inn[id].reduce(function (r, f) { return Math.max(r, (rank[f] == null ? 0 : rank[f]) + 1); }, 0); });
      // shapes on their own (no links) go side by side on a row of their own
      var noted = {};
      g.edges.forEach(function (e) { if (e.note && ids[e.from] && ids[e.to]) noted[e.from] = e.to; });
      var notes = list.filter(function (n) { return noted[n.id] && (ids[noted[n.id]].parent || "") === scope; });
      list = list.filter(function (n) { return notes.indexOf(n) < 0; });
      var loners = list.filter(function (n) { return !inn[n.id].length && !out[n.id].length; });
      var linked = list.filter(function (n) { return inn[n.id].length || out[n.id].length; });
      var rows = [];
      linked.forEach(function (n) { (rows[rank[n.id]] = rows[rank[n.id]] || []).push(n.id); });
      // a link that skips rows gets a waypoint in each row it crosses, so the shapes leave it a way through
      linked.forEach(function (n) {
        out[n.id].slice().forEach(function (to) {
          var span = rank[to] - rank[n.id];
          if (span < 2) return;
          var chain = [], prev = n.id;
          for (var r = rank[n.id] + 1; r < rank[to]; r++) {
            var v = "~" + (++vseq);
            virt[v] = { id: v, w: across ? 0 : 18, h: across ? 18 : 0, x: 0, y: 0 };
            out[v] = []; inn[v] = [];
            rows[r].push(v); chain.push(v);
            out[prev].push(v); inn[v].push(prev); prev = v;
          }
          out[prev].push(to); inn[to].push(prev);
          out[n.id].splice(out[n.id].indexOf(to), 1); inn[to].splice(inn[to].indexOf(n.id), 1);
          chains.push({ scope: scope, from: n.id, to: to, via: chain });
        });
      });
      rows = rows.filter(Boolean);
      if (loners.length) {
        var per = Math.max(2, Math.ceil(Math.sqrt(loners.length * (linked.length ? 1 : 1.6))));
        for (var c = 0; c < loners.length; c += per) rows.push(loners.slice(c, c + per).map(function (n) { return n.id; }));
      }
      // order inside rows: the average place of the shapes linked to it, a few sweeps up and down
      var pos = {};
      function number() { rows.forEach(function (r) { r.forEach(function (id, i) { pos[id] = i; }); }); }
      number();
      for (var sweep = 0; sweep < 6; sweep++) {
        var down = sweep % 2 === 0, seq = down ? rows.slice(1) : rows.slice(0, -1).reverse();
        seq.forEach(function (r) {
          var bc = {};
          r.forEach(function (id) {
            var nb = down ? inn[id] : out[id], s = 0, k = 0;
            nb.forEach(function (o) { if (pos[o] != null) { s += pos[o]; k++; } });
            bc[id] = k ? s / k : pos[id];
          });
          r.sort(function (a, b) { return bc[a] - bc[b] || pos[a] - pos[b]; });
          r.forEach(function (id, i) { pos[id] = i; });
        });
      }
      // notes go in their shape's row, on the side they were written on
      notes.forEach(function (n) {
        var t = noted[n.id];
        for (var ri = 0; ri < rows.length; ri++) {
          var at = rows[ri].indexOf(t);
          if (at >= 0) { rows[ri].splice(n.side === "left" ? at : at + 1, 0, n.id); return; }
        }
        rows.push([n.id]);
      });
      // sizes along (a) and across (b) the flow
      function along(n) { return across ? n.w : n.h; }
      function side(n) { return across ? n.h : n.w; }
      var rowSize = rows.map(function (r) { return Math.max.apply(null, r.map(function (id) { return along(box(id)); })); });
      var rowWidth = rows.map(function (r) { return r.reduce(function (s, id) { return s + side(box(id)) + (virt[id] ? -GAP.node / 2 : 0); }, 0) + GAP.node * (r.length - 1); });
      var widest = Math.max.apply(null, rowWidth), centre = {};
      rows.forEach(function (r, ri) {
        var at = (widest - rowWidth[ri]) / 2;
        r.forEach(function (id) { centre[id] = at + side(box(id)) / 2; at += side(box(id)) + GAP.node; });
      });
      // pull each shape towards the shapes it links to, keeping the order and the gaps
      for (var pass = 0; pass < 4; pass++) {
        rows.forEach(function (r, ri) {
          var want = r.map(function (id) {
            var nb = (pass % 2 ? out[id] : inn[id]).concat(pass % 2 ? inn[id] : out[id]), s = 0, k = 0;
            nb.forEach(function (o) { if (centre[o] != null) { s += centre[o]; k++; } });
            return k ? s / k : centre[id];
          });
          function gap(a, b) { return side(box(a)) / 2 + side(box(b)) / 2 + (virt[a] || virt[b] ? GAP.node / 2 : GAP.node); }
          for (var i = 0; i < r.length; i++) {
            var lo = i ? centre[r[i - 1]] + gap(r[i - 1], r[i]) : -Infinity;
            centre[r[i]] = Math.max(lo, want[i]);
          }
          for (var j = r.length - 2; j >= 0; j--) {
            var hi = centre[r[j + 1]] - gap(r[j], r[j + 1]);
            if (centre[r[j]] > hi) centre[r[j]] = hi;
          }
        });
      }
      var min = Infinity, max = -Infinity;
      list = list.concat(notes).concat(Object.keys(virt).filter(function (v) { return centre[v] != null && !virt[v].done; }).map(function (v) { return virt[v]; }));
      list.forEach(function (n) { if (centre[n.id] == null) return; min = Math.min(min, centre[n.id] - side(n) / 2); max = Math.max(max, centre[n.id] + side(n) / 2); });
      var at2 = 0, top = scope ? GAP.pad + GAP.head - 8 : 0, left = scope ? GAP.pad : 0;
      rows.forEach(function (r, ri) {
        r.forEach(function (id) {
          var n = box(id), a = at2 + (rowSize[ri] - along(n)) / 2, b = centre[id] - side(n) / 2 - min;
          if (across) { n.x = left + a; n.y = top + b; } else { n.x = left + b; n.y = top + a; }
          if (virt[id]) n.band = [(across ? left : top) + at2, (across ? left : top) + at2 + rowSize[ri]];     // a waypoint runs the row's full depth
        });
        at2 += rowSize[ri] + GAP.rank;
      });
      var totalAlong = at2 - GAP.rank, totalSide = max - min;
      if (dir === "BT" || dir === "RL") list.forEach(function (n) {
        var o = across ? left : top;
        if (across) n.x = left + totalAlong - (n.x - left) - n.w; else n.y = top + totalAlong - (n.y - top) - n.h;
        if (n.band) n.band = [2 * o + totalAlong - n.band[1], 2 * o + totalAlong - n.band[0]].reverse();
      });

      var w = across ? totalAlong : totalSide, h = across ? totalSide : totalAlong;
      if (scope) {
        var frame = ids[scope];
        frame.w = Math.max(160, Math.round(w + GAP.pad * 2)); frame.h = Math.max(100, Math.round(h + top + GAP.pad));
      }
      Object.keys(virt).forEach(function (v) { virt[v].done = true; });
      return { w: w, h: h };
    }
    place("");
    // the groups' insides were placed relative to the group: move them to the page
    function shift(scope, dx, dy) {
      (kids[scope] || []).forEach(function (n) { n.x = Math.round(n.x + dx); n.y = Math.round(n.y + dy); if (n.shape === "container") shift(n.id, n.x, n.y); });
    }
    (kids[""] || []).forEach(function (n) { n.x = Math.round(n.x + 40); n.y = Math.round(n.y + 40); if (n.shape === "container") shift(n.id, n.x, n.y); });
    // the long links bend through their waypoints (placed in their group's frame, now moved with it)
    chains.forEach(function (c) {
      var ox = c.scope ? ids[c.scope].x : 40, oy = c.scope ? ids[c.scope].y : 40;
      var pts = [];
      c.via.forEach(function (v) {
        var b = virt[v], cx = Math.round(b.x + b.w / 2 + ox), cy = Math.round(b.y + b.h / 2 + oy);
        // straight through the row (the way the flow goes), so it only bends in the gaps between rows
        b.band.forEach(function (at) { pts.push(across ? [Math.round(at + ox), cy] : [cx, Math.round(at + oy)]); });
      });
      g.edges.forEach(function (e) {
        if (e.from === c.from && e.to === c.to) { e.pts = pts; e.auto = true; }
        else if (e.from === c.to && e.to === c.from) { e.pts = pts.slice().reverse(); e.auto = true; }
      });
    });
    return g;
  }

  /* Text → a drawing, keeping where shapes were in an earlier drawing (by id). */
  function importText(kind, text, before) {
    var g = fromMermaid(kind, text), old = {}, byLabel = {}, twice = {};
    ((before && before.nodes) || []).forEach(function (n) {
      var key = n.shape + ":" + String(n.label || "").trim();
      if (byLabel[key]) twice[key] = true; byLabel[key] = n;
    });
    var taken = {};
    ((before && before.nodes) || []).forEach(function (n) { taken[n.id] = n; });
    g.nodes.forEach(function (n) {
      var key = n.shape + ":" + String(n.label || "").trim();
      if (taken[n.id] && taken[n.id].shape === n.shape) old[n.id] = taken[n.id];
      else if (byLabel[key] && !twice[key] && !g.nodes.some(function (m) { return m.id === byLabel[key].id; })) old[n.id] = byLabel[key];
    });
    layout(g, g.dir || "TD");
    var kept = g.nodes.filter(function (n) { return old[n.id]; });
    if (kept.length) {
      // shapes that were there keep their place (and size and colours); new ones go where the layout put them, beside the old
      var dx = 0, dy = 0, k = 0;
      kept.forEach(function (n) { dx += old[n.id].x - n.x; dy += old[n.id].y - n.y; k++; });
      dx = Math.round(dx / k); dy = Math.round(dy / k);
      g.nodes.forEach(function (n) {
        var o = old[n.id];
        if (o) {
          n.x = o.x; n.y = o.y;
          if (!ROWS[n.shape] && n.shape === o.shape) { n.w = o.w; n.h = o.h; }
          ["fill", "stroke", "size", "side"].forEach(function (key) { if (o[key] != null && n[key] == null) n[key] = o[key]; });
        } else { n.x += dx; n.y += dy; }
      });
      var oldEdges = {};
      ((before && before.edges) || []).forEach(function (e) { oldEdges[e.from + ">" + e.to] = e; });
      g.edges.forEach(function (e) { var o = oldEdges[e.from + ">" + e.to]; if (o && o.route) e.route = o.route; });
    }
    return g;
  }

  // ── draw.io files ────────────────────────────────────────────────────────
  var DRAWIO_SHAPE = {
    rect: "rounded=0;", rounded: "rounded=1;", stadium: "rounded=1;arcSize=50;", ellipse: "ellipse;", circle: "ellipse;aspect=fixed;",
    dcircle: "ellipse;shape=doubleEllipse;", diamond: "rhombus;", triangle: "triangle;direction=north;", hexagon: "shape=hexagon;perimeter=hexagonPerimeter2;fixedSize=1;",
    parallelogram: "shape=parallelogram;perimeter=parallelogramPerimeter;fixedSize=1;", parallelogram2: "shape=parallelogram;perimeter=parallelogramPerimeter;fixedSize=1;flipH=1;",
    trapezoid: "shape=trapezoid;perimeter=trapezoidPerimeter;fixedSize=1;", trapezoid2: "shape=trapezoid;perimeter=trapezoidPerimeter;fixedSize=1;flipV=1;",
    cylinder: "shape=cylinder3;boundedLbl=1;backgroundOutline=1;size=12;", document: "shape=document;boundedLbl=1;", cloud: "ellipse;shape=cloud;",
    actor: "shape=umlActor;verticalLabelPosition=bottom;verticalAlign=top;outlineConnect=0;", note: "shape=note;size=14;fillColor=#fff4bf;strokeColor=#e0b84c;",
    text: "text;strokeColor=none;fillColor=none;", container: "rounded=1;dashed=1;verticalAlign=top;align=left;spacingLeft=8;arcSize=4;fillColor=none;",
    subroutine: "shape=process;", flag: "shape=step;perimeter=stepPerimeter;fixedSize=1;flipH=1;", start: "ellipse;fillColor=#000000;", end: "ellipse;shape=endState;fillColor=#000000;",
    fork: "rounded=0;fillColor=#000000;strokeColor=none;", "class": "verticalAlign=top;align=left;overflow=fill;html=1;", entity: "verticalAlign=top;align=left;overflow=fill;html=1;rounded=1;arcSize=4;",
    image: "shape=image;imageAspect=1;aspect=fixed;",
  };
  var DRAWIO_MARK = { arrow: "classic", open: "open", triangle: "block;FILL=0", diamond: "diamond;FILL=1", odiamond: "diamond;FILL=0", circle: "oval;FILL=1",
                      cross: "cross", one: "ERmandOne", zone: "ERzeroToOne", many: "ERoneToMany", zmany: "ERzeroToMany", none: "none" };
  function xmlAttr(v) { return String(v == null ? "" : v).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/\n/g, "&#10;"); }
  function html(v) { return String(v == null ? "" : v).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }
  /* A drawing as a draw.io file (opens in draw.io / diagrams.net). `marks(e, end)` gives a link's end marks; `origin` makes picture links whole. */
  function toDrawio(g, marks, origin) {
    var cells = ['<mxCell id="0"/>', '<mxCell id="1" parent="0"/>'], ids = {}, k = 0;
    g.nodes.forEach(function (n) { ids[n.id] = "v" + (++k); });
    function style(n) {
      var st = (DRAWIO_SHAPE[n.shape] || DRAWIO_SHAPE.rect) + "whiteSpace=wrap;";
      if (n.shape === "image" && n.src) st += "image=" + (/^\//.test(n.src) ? (origin || "") + n.src : n.src) + ";";
      if (n.fill) st += "fillColor=" + (n.fill === "none" ? "none" : n.fill) + ";";
      if (n.stroke) st += "strokeColor=" + n.stroke + ";";
      if (n.size) st += "fontSize=" + n.size + ";";
      if (n.bold) st += "fontStyle=1;";
      return st;
    }
    function value(n) {
      if (n.shape === "class") {
        return (n.stereo ? '<p style="margin:0;text-align:center"><i>&laquo;' + html(n.stereo) + "&raquo;</i></p>" : "") + '<p style="margin:4px 0 0;text-align:center"><b>' + html(n.label) + '</b></p><hr size="1">' +
          '<p style="margin:0 0 0 4px">' + lines(n.attrs).map(html).join("<br>") + '</p><hr size="1"><p style="margin:0 0 0 4px">' + lines(n.methods).map(html).join("<br>") + "</p>";
      }
      if (n.shape === "entity") {
        return '<p style="margin:4px 0 0;text-align:center"><b>' + html(n.label) + '</b></p><hr size="1"><p style="margin:0 0 0 4px">' +
          columns(n).map(function (c) { return html([c.type, c.name, c.keys].filter(Boolean).join(" ")); }).join("<br>") + "</p>";
      }
      return n.label || "";
    }
    // groups first, so they sit behind
    g.nodes.slice().sort(function (a, b) { return (a.shape === "container" ? 0 : 1) - (b.shape === "container" ? 0 : 1); }).forEach(function (n) {
      cells.push('<mxCell id="' + ids[n.id] + '" value="' + xmlAttr(value(n)) + '" style="' + xmlAttr(style(n)) + '" vertex="1" parent="1">' +
                 '<mxGeometry x="' + Math.round(n.x) + '" y="' + Math.round(n.y) + '" width="' + Math.round(n.w) + '" height="' + Math.round(n.h) + '" as="geometry"/></mxCell>');
    });
    g.edges.forEach(function (e, i) {
      if (!ids[e.from] || !ids[e.to]) return;
      var m = marks ? marks(e) : { start: e.start || "none", end: e.end || "arrow" };
      var st = "html=1;rounded=1;endArrow=" + DRAWIO_MARK[m.end || "none"].replace(";FILL=", ";endFill=") + ";startArrow=" + DRAWIO_MARK[m.start || "none"].replace(";FILL=", ";startFill=") + ";";
      if (e.line === "dashed") st += "dashed=1;";
      if (e.line === "thick") st += "strokeWidth=3;";
      if (e.route === "elbow" && !e.pts) st += "edgeStyle=orthogonalEdgeStyle;";
      if (e.route === "curve") st += "curved=1;";
      var pts = (e.pts || []).map(function (q) { return '<mxPoint x="' + Math.round(q[0]) + '" y="' + Math.round(q[1]) + '"/>'; }).join("");
      cells.push('<mxCell id="e' + (i + 1) + '" value="' + xmlAttr(e.label || "") + '" style="' + xmlAttr(st) + '" edge="1" parent="1" source="' + ids[e.from] + '" target="' + ids[e.to] + '">' +
                 '<mxGeometry relative="1" as="geometry">' + (pts ? '<Array as="points">' + pts + "</Array>" : "") + "</mxGeometry></mxCell>");
    });
    return '<mxfile host="FinTrack" type="device"><diagram id="page1" name="Page-1"><mxGraphModel grid="1" gridSize="10" guides="1" connect="1" arrows="1" page="0">' +
           "<root>" + cells.join("") + "</root></mxGraphModel></diagram></mxfile>\n";
  }

  root.WorkDrawModel = {
    LIBRARY: LIBRARY, ROWS: ROWS, ROUND: ROUND, TIGHT: TIGHT, FONT: FONT, ROW_H: ROW_H, HEAD_H: HEAD_H,
    libraryItem: libraryItem, shapesOf: shapesOf, textWidth: textWidth, wrap: wrap, lines: lines, textBox: textBox, columns: columns,
    rowsHeight: rowsHeight, fitSize: fitSize, fromMermaid: fromMermaid, toMermaid: toMermaid, layout: layout, importText: importText, toDrawio: toDrawio,
    KINDS: Object.keys(PARSERS),
  };
  if (typeof module !== "undefined" && module.exports) module.exports = root.WorkDrawModel;
})(typeof window !== "undefined" ? window : globalThis);
