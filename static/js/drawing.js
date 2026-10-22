/* Drag-and-drop drawings (Productivity), the way draw.io works: shapes from
   the left, dragged into place with guides that line them up, resized from
   any side, linked by dragging from the blue arrows that show on a shape
   (a click on one adds a linked copy), text typed right on the shape, and
   the look changed on the right.

   Used by "Free drawing" diagrams, and by flowcharts, state, class and
   database diagrams in their drag-and-drop mode — those keep their Mermaid
   text in step with the drawing (WorkDrawModel turns one into the other).
   Loaded after diagrams.js and drawmodel.js. */
(function () {
  "use strict";
  var d = document;
  var DM = window.WorkDrawModel, WD = window.WorkDiagrams;
  if (!DM || !WD) return;
  var TEXT = WD.TEXT, esc = WD.esc, clone = WD.clone, toast = WD.toast, FONT = DM.FONT;
  var STROKES = ["#1f2a24", "#1c7ed6", "#2f9e44", "#e8590c", "#e03131", "#ae3ec9", "#0c8599", "#f08c00", "#868e96"];
  var FILLS = ["#ffffff", "#f1f3f5", "#dbe4ff", "#d3f9d8", "#fff3bf", "#ffe8cc", "#ffe3e3", "#f3d9fa", "#c5f6fa"];
  var SIZES = [12, 14, 18, 24];
  var GRID = 10;
  // the marks each kind of diagram can put at the ends of a link
  var MARKS = {
    flowchart: ["none", "arrow", "circle", "cross"],
    state: [], "class": [], er: ["one", "zone", "many", "zmany"],
    drawing: ["none", "arrow", "open", "triangle", "diamond", "odiamond", "circle", "cross", "one", "zone", "many", "zmany"],
  };
  var CLASS_LINKS = [
    ["association", "solid", "", "arrow"], ["inheritance", "solid", "", "triangle"], ["realization", "dashed", "", "triangle"],
    ["composition", "solid", "diamond", ""], ["aggregation", "solid", "odiamond", ""], ["dependency", "dashed", "", "arrow"],
    ["link", "solid", "", ""], ["dashedLink", "dashed", "", ""],
  ];
  var MAIN = { flowchart: "rect", state: "rounded", "class": "class", er: "entity", drawing: "rect" };
  var NO_CLONE = { start: 1, end: 1, fork: 1, text: 1, note: 1, container: 1 };

  /* Changes the format panel shows go through Alpine, so the panel keeps up. */
  function rx(o) { return window.Alpine && Alpine.reactive ? Alpine.reactive(o) : o; }
  function uid() { return "_" + Date.now().toString(36).slice(-5) + Math.random().toString(36).slice(2, 6); }
  function snapTo(v, on) { return on ? Math.round(v / GRID) * GRID : Math.round(v); }
  function isDark() { return d.documentElement.getAttribute("data-theme") === "dark"; }
  function lightText(fill) {      // dark words on a light fill
    var m = /^#([0-9a-f]{6})$/i.exec(fill || ""); if (!m) return false;
    var v = parseInt(m[1], 16), r = v >> 16 & 255, g = v >> 8 & 255, b = v & 255;
    return (r * 299 + g * 587 + b * 114) / 1000 > 150;
  }

  // ── Drawing one shape (SVG, in its own box from 0,0 to w,h) ──────────────
  /* `p`: the paint — fill, stroke, width — as CSS values. */
  function shapeSVG(n, p) {
    var w = n.w, h = n.h, f = 'fill="' + p.fill + '" stroke="' + p.stroke + '" stroke-width="' + p.sw + '"', o = 0.75, s, ry;
    function poly(pts) { return '<polygon points="' + pts.map(function (q) { return q[0].toFixed(1) + "," + q[1].toFixed(1); }).join(" ") + '" ' + f + ' stroke-linejoin="round"/>'; }
    switch (n.shape) {
      case "rounded": return '<rect x="' + o + '" y="' + o + '" width="' + (w - 2 * o) + '" height="' + (h - 2 * o) + '" rx="' + Math.min(12, h / 4) + '" ' + f + "/>";
      case "stadium": return '<rect x="' + o + '" y="' + o + '" width="' + (w - 2 * o) + '" height="' + (h - 2 * o) + '" rx="' + (h / 2 - o) + '" ' + f + "/>";
      case "ellipse": case "circle": return '<ellipse cx="' + w / 2 + '" cy="' + h / 2 + '" rx="' + (w / 2 - o) + '" ry="' + (h / 2 - o) + '" ' + f + "/>";
      case "dcircle": return '<ellipse cx="' + w / 2 + '" cy="' + h / 2 + '" rx="' + (w / 2 - o) + '" ry="' + (h / 2 - o) + '" ' + f + '/><ellipse cx="' + w / 2 + '" cy="' + h / 2 + '" rx="' + Math.max(1, w / 2 - 6) + '" ry="' + Math.max(1, h / 2 - 6) + '" fill="none" stroke="' + p.stroke + '" stroke-width="' + p.sw + '"/>';
      case "diamond": return poly([[w / 2, o], [w - o, h / 2], [w / 2, h - o], [o, h / 2]]);
      case "triangle": return poly([[w / 2, o], [w - o, h - o], [o, h - o]]);
      case "hexagon": s = Math.min(w / 4, h / 2); return poly([[s, o], [w - s, o], [w - o, h / 2], [w - s, h - o], [s, h - o], [o, h / 2]]);
      case "parallelogram": s = Math.min(h * 0.4, w / 4); return poly([[s, o], [w - o, o], [w - s, h - o], [o, h - o]]);
      case "parallelogram2": s = Math.min(h * 0.4, w / 4); return poly([[o, o], [w - s, o], [w - o, h - o], [s, h - o]]);
      case "trapezoid": s = Math.min(h * 0.4, w / 4); return poly([[s, o], [w - s, o], [w - o, h - o], [o, h - o]]);
      case "trapezoid2": s = Math.min(h * 0.4, w / 4); return poly([[o, o], [w - o, o], [w - s, h - o], [s, h - o]]);
      case "flag": s = Math.min(w / 5, 18); return poly([[o, o], [w - o, o], [w - o, h - o], [o, h - o], [s, h / 2]]);
      case "cylinder":
        ry = Math.min(h * 0.15, 14);
        return '<path d="M' + o + "," + ry + " A" + (w / 2 - o) + "," + ry + " 0 0 1 " + (w - o) + "," + ry + " V" + (h - ry) + " A" + (w / 2 - o) + "," + ry + " 0 0 1 " + o + "," + (h - ry) + ' Z" ' + f + "/>" +
          '<path d="M' + o + "," + ry + " A" + (w / 2 - o) + "," + ry + " 0 0 0 " + (w - o) + "," + ry + '" fill="none" stroke="' + p.stroke + '" stroke-width="' + p.sw + '"/>';
      case "document":
        s = Math.min(h * 0.12, 10);
        return '<path d="M' + o + "," + o + " H" + (w - o) + " V" + (h - s) + " C" + (w * 0.75) + "," + (h - 3 * s) + " " + (w * 0.25) + "," + (h + s) + " " + o + "," + (h - s) + ' Z" ' + f + ' stroke-linejoin="round"/>';
      case "subroutine":
        return '<rect x="' + o + '" y="' + o + '" width="' + (w - 2 * o) + '" height="' + (h - 2 * o) + '" ' + f + "/>" +
          '<path d="M8,' + o + " V" + (h - o) + " M" + (w - 8) + "," + o + " V" + (h - o) + '" stroke="' + p.stroke + '" stroke-width="' + p.sw + '"/>';
      case "cloud":
        return '<path transform="scale(' + (w / 100).toFixed(4) + "," + (h / 64).toFixed(4) + ')" vector-effect="non-scaling-stroke" d="M26,58 C10,58 4,46 10,37 C2,30 8,16 21,18 C24,6 42,2 51,11 C58,2 76,4 79,16 C93,15 99,29 91,38 C99,47 90,60 77,57 C70,64 54,64 48,57 C42,62 31,62 26,58 Z" ' + f + ' stroke-linejoin="round"/>';
      case "actor":
        var r = Math.min(w / 4, h / 7), cx = w / 2, by = h * 0.62;
        return '<g fill="none" stroke="' + p.stroke + '" stroke-width="' + Math.max(1.5, p.sw) + '" stroke-linecap="round"><circle cx="' + cx + '" cy="' + (r + 2) + '" r="' + r + '" fill="' + p.fill + '"/>' +
          '<path d="M' + cx + "," + (2 * r + 2) + " V" + by + " M" + (w * 0.12) + "," + (h * 0.36) + " H" + (w * 0.88) + " M" + cx + "," + by + " L" + (w * 0.15) + "," + (h - 2) + " M" + cx + "," + by + " L" + (w * 0.85) + "," + (h - 2) + '"/></g>';
      case "note":
        s = Math.min(14, w / 5, h / 4);
        return '<path d="M' + o + "," + o + " H" + (w - s) + " L" + (w - o) + "," + s + " V" + (h - o) + " H" + o + ' Z" ' + f + ' stroke-linejoin="round"/><path d="M' + (w - s) + "," + o + " V" + s + " H" + (w - o) + '" fill="none" stroke="' + p.stroke + '" stroke-width="' + p.sw + '"/>';
      case "text": return '<rect width="' + w + '" height="' + h + '" fill="' + (p.fill === "none" ? "transparent" : p.fill) + '" stroke="none"/>';
      case "container": return '<rect x="' + o + '" y="' + o + '" width="' + (w - 2 * o) + '" height="' + (h - 2 * o) + '" rx="10" fill="' + p.fill + '" stroke="' + p.stroke + '" stroke-width="' + p.sw + '" stroke-dasharray="7 5"/>';
      case "start": return '<circle cx="' + w / 2 + '" cy="' + h / 2 + '" r="' + (Math.min(w, h) / 2 - 1) + '" fill="' + p.stroke + '"/>';
      case "end": return '<circle cx="' + w / 2 + '" cy="' + h / 2 + '" r="' + (Math.min(w, h) / 2 - 1) + '" fill="' + p.fill + '" stroke="' + p.stroke + '" stroke-width="2"/><circle cx="' + w / 2 + '" cy="' + h / 2 + '" r="' + Math.max(2, Math.min(w, h) / 2 - 6) + '" fill="' + p.stroke + '"/>';
      case "fork": return '<rect width="' + w + '" height="' + h + '" rx="' + Math.min(3, h / 2) + '" fill="' + p.stroke + '"/>';
      case "class": case "entity":
        return '<rect x="' + o + '" y="' + o + '" width="' + (w - 2 * o) + '" height="' + (h - 2 * o) + '" rx="' + (n.shape === "entity" ? 6 : 2) + '" ' + f + "/>";
      default: return '<rect x="' + o + '" y="' + o + '" width="' + (w - 2 * o) + '" height="' + (h - 2 * o) + '" rx="2" ' + f + "/>";
    }
  }
  /* The paint for a shape: its own colours, or the page's (`screen`) or plain ones for a picture. */
  function paint(n, screen) {
    var sw = n.shape === "container" ? 1.5 : 1.6;
    var autoFill = n.shape === "note" ? (screen ? "var(--wdr-note)" : "#fff4bf") : n.shape === "container" ? (screen ? "var(--wdr-group)" : "#f8faf9") : n.shape === "text" ? "none" : (screen ? "var(--wdr-fill)" : "#ffffff");
    var autoStroke = n.shape === "note" ? (screen ? "var(--wdr-note-line)" : "#e0b84c") : (screen ? "var(--wdr-line)" : "#33413b");
    return { fill: n.fill || autoFill, stroke: n.stroke || autoStroke, sw: sw };
  }
  function textColor(n, screen) {
    if (n.fill && n.fill !== "none") return lightText(n.fill) ? "#1f2a24" : "#ffffff";
    if (n.shape === "note") return screen ? "var(--wdr-note-text)" : "#5c4a00";
    return screen ? "var(--text-primary)" : "#1f2a24";
  }

  /* Where a line towards (tx, ty) meets the edge of a shape. */
  function perimeter(n, tx, ty) {
    var cx = n.x + n.w / 2, cy = n.y + n.h / 2, dx = tx - cx, dy = ty - cy;
    if (!dx && !dy) return { x: cx, y: cy };
    var a = n.w / 2, b = n.h / 2, t;
    if (DM.ROUND[n.shape]) t = 1 / Math.sqrt((dx * dx) / (a * a) + (dy * dy) / (b * b));
    else if (n.shape === "diamond") t = 1 / (Math.abs(dx) / a + Math.abs(dy) / b);
    else t = Math.min(dx ? a / Math.abs(dx) : Infinity, dy ? b / Math.abs(dy) : Infinity);
    return { x: cx + dx * t, y: cy + dy * t };
  }
  function centre(n) { return { x: n.x + n.w / 2, y: n.y + n.h / 2 }; }
  /* A path through points, with its corners rounded. */
  function polyline(pts) {
    var dd = "M" + pts[0].x + "," + pts[0].y;
    for (var i = 1; i < pts.length - 1; i++) {
      var a = pts[i - 1], p = pts[i], c = pts[i + 1];
      var l1 = Math.hypot(p.x - a.x, p.y - a.y) || 1, l2 = Math.hypot(c.x - p.x, c.y - p.y) || 1, r = Math.min(14, l1 / 2, l2 / 2);
      dd += " L" + (p.x - (p.x - a.x) / l1 * r).toFixed(1) + "," + (p.y - (p.y - a.y) / l1 * r).toFixed(1) +
            " Q" + p.x + "," + p.y + " " + (p.x + (c.x - p.x) / l2 * r).toFixed(1) + "," + (p.y + (c.y - p.y) / l2 * r).toFixed(1);
    }
    var z = pts[pts.length - 1];
    return dd + " L" + z.x + "," + z.y;
  }
  /* A link's path between two shapes. `bend` pushes it sideways (for two links between the same shapes). */
  function route(e, a, b, bend) {
    if (a === b) {                       // a link back to itself: a loop at the top right
      var p1 = { x: a.x + a.w * 0.7, y: a.y }, p2 = { x: a.x + a.w, y: a.y + a.h * 0.3 };
      var c1 = { x: p1.x, y: a.y - 44 }, c2 = { x: a.x + a.w + 44, y: p2.y };
      return { d: "M" + p1.x + "," + p1.y + " C" + c1.x + "," + c1.y + " " + c2.x + "," + c2.y + " " + p2.x + "," + p2.y, a: p1, b: p2, fromA: c1, fromB: c2, mid: { x: a.x + a.w + 18, y: a.y - 18 } };
    }
    var ca = centre(a), cb = centre(b);
    if (e.pts && e.pts.length) {          // bends from a tidy-up: through its waypoints
      var via = e.pts.map(function (q) { return { x: q[0], y: q[1] }; }), s0 = perimeter(a, via[0].x, via[0].y), t0 = perimeter(b, via[via.length - 1].x, via[via.length - 1].y);
      var all = [s0].concat(via, [t0]), half = all[Math.floor(all.length / 2)], prev = all[Math.floor(all.length / 2) - 1];
      return { d: polyline(all), a: s0, b: t0, fromA: via[0], fromB: via[via.length - 1], mid: { x: (half.x + prev.x) / 2, y: (half.y + prev.y) / 2 } };
    }
    if (e.route === "elbow" || e.route === "curve") {
      var acrossX = Math.abs(cb.x - ca.x) - (a.w + b.w) / 2 > Math.abs(cb.y - ca.y) - (a.h + b.h) / 2, s, t, m1, m2;
      if (acrossX) { var sx = cb.x >= ca.x ? 1 : -1; s = { x: ca.x + sx * a.w / 2, y: ca.y }; t = { x: cb.x - sx * b.w / 2, y: cb.y }; m1 = { x: (s.x + t.x) / 2, y: s.y }; m2 = { x: (s.x + t.x) / 2, y: t.y }; }
      else { var sy = cb.y >= ca.y ? 1 : -1; s = { x: ca.x, y: ca.y + sy * a.h / 2 }; t = { x: cb.x, y: cb.y - sy * b.h / 2 }; m1 = { x: s.x, y: (s.y + t.y) / 2 }; m2 = { x: t.x, y: (s.y + t.y) / 2 }; }
      var dd = e.route === "curve" ? "M" + s.x + "," + s.y + " C" + m1.x + "," + m1.y + " " + m2.x + "," + m2.y + " " + t.x + "," + t.y
                                   : "M" + s.x + "," + s.y + " L" + m1.x + "," + m1.y + " L" + m2.x + "," + m2.y + " L" + t.x + "," + t.y;
      return { d: dd, a: s, b: t, fromA: m1, fromB: m2, mid: { x: (m1.x + m2.x) / 2, y: (m1.y + m2.y) / 2 } };
    }
    if (bend) {
      var mx = (ca.x + cb.x) / 2, my = (ca.y + cb.y) / 2, len = Math.hypot(cb.x - ca.x, cb.y - ca.y) || 1;
      var c = { x: mx - (cb.y - ca.y) / len * bend, y: my + (cb.x - ca.x) / len * bend };
      var q1 = perimeter(a, c.x, c.y), q2 = perimeter(b, c.x, c.y);
      return { d: "M" + q1.x + "," + q1.y + " Q" + c.x + "," + c.y + " " + q2.x + "," + q2.y, a: q1, b: q2, fromA: c, fromB: c,
               mid: { x: (q1.x + 2 * c.x + q2.x) / 4, y: (q1.y + 2 * c.y + q2.y) / 4 } };
    }
    var r1 = perimeter(a, cb.x, cb.y), r2 = perimeter(b, ca.x, ca.y);
    return { d: "M" + r1.x + "," + r1.y + " L" + r2.x + "," + r2.y, a: r1, b: r2, fromA: r2, fromB: r1, mid: { x: (r1.x + r2.x) / 2, y: (r1.y + r2.y) / 2 } };
  }
  /* The mark at a link's end: `p` is the tip, `q` a point back along the line. `bg` fills the hollow ones. */
  function mark(type, p, q, stroke, bg) {
    if (!type || type === "none") return "";
    var ang = Math.atan2(p.y - q.y, p.x - q.x), ux = Math.cos(ang), uy = Math.sin(ang), nx = -uy, ny = ux;
    function at(back, side) { return (p.x - ux * back + nx * side).toFixed(1) + "," + (p.y - uy * back + ny * side).toFixed(1); }
    var line = 'stroke="' + stroke + '" stroke-width="1.6"';
    switch (type) {
      case "arrow": return '<path d="M' + at(0, 0) + " L" + at(11, 5) + " L" + at(11, -5) + ' Z" fill="' + stroke + '" ' + line + ' stroke-linejoin="round"/>';
      case "open": return '<path d="M' + at(11, 6) + " L" + at(0, 0) + " L" + at(11, -6) + '" fill="none" ' + line + ' stroke-linecap="round"/>';
      case "triangle": return '<path d="M' + at(0, 0) + " L" + at(15, 8) + " L" + at(15, -8) + ' Z" fill="' + bg + '" ' + line + ' stroke-linejoin="round"/>';
      case "diamond": return '<path d="M' + at(0, 0) + " L" + at(9, 6) + " L" + at(18, 0) + " L" + at(9, -6) + ' Z" fill="' + stroke + '" ' + line + "/>";
      case "odiamond": return '<path d="M' + at(0, 0) + " L" + at(9, 6) + " L" + at(18, 0) + " L" + at(9, -6) + ' Z" fill="' + bg + '" ' + line + "/>";
      case "circle": return '<circle cx="' + (p.x - ux * 5).toFixed(1) + '" cy="' + (p.y - uy * 5).toFixed(1) + '" r="4.5" fill="' + bg + '" ' + line + "/>";
      case "cross": return '<path d="M' + at(3, 5) + " L" + at(13, -5) + " M" + at(3, -5) + " L" + at(13, 5) + '" ' + line + "/>";
      case "one": return '<path d="M' + at(8, 7) + " L" + at(8, -7) + " M" + at(14, 7) + " L" + at(14, -7) + '" ' + line + "/>";
      case "zone": return '<path d="M' + at(8, 7) + " L" + at(8, -7) + '" ' + line + '/><circle cx="' + (p.x - ux * 19).toFixed(1) + '" cy="' + (p.y - uy * 19).toFixed(1) + '" r="5" fill="' + bg + '" ' + line + "/>";
      case "many": return '<path d="M' + at(0, 7) + " L" + at(13, 0) + " L" + at(0, -7) + " M" + at(0, 0) + " L" + at(13, 0) + " M" + at(17, 7) + " L" + at(17, -7) + '" fill="none" ' + line + "/>";
      case "zmany": return '<path d="M' + at(0, 7) + " L" + at(13, 0) + " L" + at(0, -7) + " M" + at(0, 0) + " L" + at(13, 0) + '" fill="none" ' + line + '/><circle cx="' + (p.x - ux * 19).toFixed(1) + '" cy="' + (p.y - uy * 19).toFixed(1) + '" r="5" fill="' + bg + '" ' + line + "/>";
    }
    return "";
  }
  function dash(e) { return e.line === "dashed" ? ' stroke-dasharray="7 5"' : e.line === "dotted" ? ' stroke-dasharray="2 4"' : ""; }
  function lineWidth(e) { return e.line === "thick" ? 3.2 : 1.6; }
  /* Where a word at a link's end goes (a class link's "1" or "many"). */
  function endLabel(p, q, side) {
    var ang = Math.atan2(p.y - q.y, p.x - q.x);
    return { x: p.x - Math.cos(ang) * 22 - Math.sin(ang) * 12 * side, y: p.y - Math.sin(ang) * 22 + Math.cos(ang) * 12 * side };
  }

  /* Rows of a class or a table, as HTML (on the page) */
  function rowsHTML(n) {
    var out = '<div class="wdr-rows' + (n.shape === "entity" ? " is-table" : "") + '"><header class="wdr-rows-head">' +
      (n.stereo ? "<small>«" + esc(n.stereo) + "»</small>" : "") + '<b class="wdr-label">' + esc(n.label) + "</b></header>";
    if (n.shape === "entity") {
      out += "<table>" + DM.columns(n).map(function (c) {
        return "<tr><td>" + esc(c.type) + "</td><td>" + esc(c.name) + '</td><td class="is-key">' + esc(c.keys) + '</td><td class="is-note">' + esc(c.comment) + "</td></tr>";
      }).join("") + "</table>";
    } else {
      out += '<ul class="wdr-attrs">' + DM.lines(n.attrs).map(function (l) { return "<li>" + esc(l) + "</li>"; }).join("") + "</ul>" +
             '<ul class="wdr-methods">' + DM.lines(n.methods).map(function (l) { return "<li>" + esc(l) + "</li>"; }).join("") + "</ul>";
    }
    return out + "</div>";
  }

  document.addEventListener("alpine:init", function () {
    Alpine.data("drawBoard", function () {
      var M = null, els = {}, undos = [], redos = [], hover = null, hoverT = null, spaceDown = false;
      return {
        kind: "drawing", mermaid: false, sel: [], esel: null, node: null, edge: null, zoom: 100, view: null, grid: true, snap: true, empty: true,
        canUndo: false, canRedo: false, palette: [], groups: [], fills: FILLS, strokes: STROKES, sizes: SIZES, area: false, texts: TEXT,
        marks: [], classLinks: CLASS_LINKS, menu: false,
        get one() { return this.sel.length === 1; },
        get rowsNode() { return !!(this.node && DM.ROWS[this.node.shape]); },
        init: function () {
          var self = this, live = WD.live;
          this.kind = this.$el.getAttribute("data-kind") || "drawing";
          this.mermaid = this.kind !== "drawing";
          this.marks = MARKS[this.kind] || MARKS.drawing;
          try { this.grid = localStorage.getItem("wdr-grid") !== "0"; this.snap = localStorage.getItem("wdr-snap") !== "0"; } catch (e) { /* private window */ }
          if (this.mermaid) {
            var draw = live.data.draw;
            // the drawing as saved, unless the text was changed since: then the text is drawn again (shapes keep their places)
            if (draw && draw.nodes && draw.src === live.source) M = clone(draw);
            else {
              try { M = DM.importText(this.kind, live.source || "", draw); }
              catch (err) { M = { nodes: [], edges: [], extra: [], front: "", dir: "TD" }; }
              M.src = live.source;
            }
          } else M = clone({ nodes: live.data.nodes || [], edges: live.data.edges || [] });
          M.nodes = M.nodes || []; M.edges = M.edges || [];
          this.buildPalette();
          this.view = new WD.Viewport(this.$refs.canvas, this.$refs.world, function (k) { self.zoom = Math.round(k * 100); self.$refs.world.style.setProperty("--k", k); });
          this.editor = { svg: function () { return self.toSVG(); }, preview: function () { var o = self.toSVG(); return o ? o.svg : ""; },
                          text: function () { return DM.toMermaid(self.kind, M); }, resized: function () { self.fit(); } };
          this.pointers();
          this.render();
          this.$nextTick(function () { self.fit(); });
          if (this.mermaid && (!live.data.draw || live.data.mode !== "draw")) this.save(true);
        },
        buildPalette: function () {
          var lib = DM.LIBRARY[this.kind] || DM.LIBRARY.drawing, names = TEXT.shapes || {}, uml = { "class": 1, entity: 1, start: 1, end: 1, fork: 1 }, self = this;
          var items = lib.map(function (it) {
            var probe = { shape: it[1], w: 30, h: it[1] === "fork" ? 6 : it[1] === "actor" ? 30 : it[1] === "start" || it[1] === "end" || it[1] === "circle" || it[1] === "dcircle" ? 22 : 20, label: "" };
            if (probe.shape === "actor") probe.w = 18;
            var p = paint(probe, true);
            return { key: it[0], shape: it[1], name: names[it[0]] || it[0], svg: '<svg viewBox="-2 -2 ' + (probe.w + 4) + " " + (probe.h + 4) + '" width="' + (probe.w + 4) + '" height="' + (probe.h + 4) + '" aria-hidden="true">' + shapeSVG(probe, p) + "</svg>",
                     group: self.kind === "drawing" && uml[it[0]] ? "uml" : "basic" };
          });
          this.palette = items;
          this.groups = this.kind === "drawing" ? [["basic", TEXT.shapeGroups && TEXT.shapeGroups.basic], ["uml", TEXT.shapeGroups && TEXT.shapeGroups.uml]] : [["basic", ""]];
        },
        shapeName: function (n) {
          if (!n) return "";
          if (n.shape === "class" && n.stereo) { var st = { interface: "interface", abstract: "abstract", enumeration: "enum" }[n.stereo]; if (st) return (TEXT.shapes || {})[st] || n.shape; }
          for (var i = 0; i < this.palette.length; i++) if (this.palette[i].shape === n.shape) return this.palette[i].name;
          return (TEXT.shapes || {})[n.shape] || n.shape;
        },
        byId: function (id) { for (var i = 0; i < M.nodes.length; i++) if (M.nodes[i].id === id) return M.nodes[i]; return null; },
        edgeById: function (id) { for (var i = 0; i < M.edges.length; i++) if (M.edges[i].id === id) return M.edges[i]; return null; },

        /* ── keeping and undoing ── */
        snapshot: function () {
          undos.push(JSON.stringify({ n: M.nodes, e: M.edges, dir: M.dir })); if (undos.length > 150) undos.shift();
          redos = []; this.canUndo = true; this.canRedo = false;
        },
        restore: function (s) { var o = JSON.parse(s); M.nodes = o.n; M.edges = o.e; if (o.dir) M.dir = o.dir; this.pick([]); this.render(); this.save(); },
        undo: function () { if (!undos.length) return; redos.push(JSON.stringify({ n: M.nodes, e: M.edges, dir: M.dir })); this.restore(undos.pop()); this.canUndo = !!undos.length; this.canRedo = true; },
        redo: function () { if (!redos.length) return; undos.push(JSON.stringify({ n: M.nodes, e: M.edges, dir: M.dir })); this.restore(redos.pop()); this.canUndo = true; this.canRedo = !!redos.length; },
        save: function (quiet) {
          var live = WD.live;
          if (this.mermaid) {
            // the text follows the drawing — but only once something is changed (just opening it leaves the text as written)
            var src = quiet ? live.source : DM.toMermaid(this.kind, M);
            M.src = src; live.source = src;
            live.data.draw = { nodes: M.nodes, edges: M.edges, dir: M.dir || "", extra: M.extra || [], front: M.front || "", src: src };
            live.data.mode = "draw";
            this.queue(quiet ? { data: JSON.stringify(live.data) } : { data: JSON.stringify(live.data), source: src });
          } else {
            live.data = { nodes: M.nodes, edges: M.edges };
            this.queue({ data: JSON.stringify(live.data) });
          }
        },
        /* an inspector field changed: draw it now; one undo step for each picked thing */
        changed: function () {
          var key = (this.node || this.edge || {}).id || this.sel.join();
          if (key && this._snapFor !== key) { this.snapshot(); this._snapFor = key; }
          if (this.node && DM.ROWS[this.node.shape]) this.fitRows(this.node);
          this.render(); this.save();
        },
        fitRows: function (n) {
          n = rx(n);
          var s = DM.fitSize(n, [null, n.shape, n.shape === "entity" ? 200 : 170, 60]);
          n.h = s.h; if (n.w < s.w) n.w = s.w;
        },

        /* ── drawing ── */
        render: function () {
          var self = this, seen = {}, back = this.$refs.back, front = this.$refs.nodes, depth = {}, at = { back: 0, front: 0 };
          function deep(n) { if (depth[n.id] != null) return depth[n.id]; var p = n.parent && self.byId(n.parent); depth[n.id] = p && p !== n ? deep(p) + 1 : 0; return depth[n.id]; }
          var groups = M.nodes.filter(function (n) { return n.shape === "container"; }).sort(function (a, b) { return deep(a) - deep(b); });
          groups.concat(M.nodes.filter(function (n) { return n.shape !== "container"; })).forEach(function (n) {
            seen[n.id] = true;
            var el = els[n.id], layer = n.shape === "container" ? back : front;
            if (!el) { el = d.createElement("div"); el.setAttribute("data-id", n.id); els[n.id] = el; }
            var slot = layer === back ? "back" : "front", here = layer.children[at[slot]++];
            if (here !== el) layer.insertBefore(el, here || null);                            // z-order follows the list
            var sig = [n.shape, n.w, n.h, n.label, n.fill, n.stroke, n.size, n.attrs, n.methods, n.stereo, n.bold, isDark()].join("\u0001");
            if (el._sig !== sig) {
              el._sig = sig;
              var p = paint(n, true), inner = '<svg class="wdr-shape" width="' + n.w + '" height="' + n.h + '" overflow="visible" aria-hidden="true">' + shapeSVG(n, p) + "</svg>";
              if (DM.ROWS[n.shape]) inner += rowsHTML(n);
              else if (!DM.TIGHT[n.shape]) {
                var b = DM.textBox(n);
                inner += '<div class="wdr-text" style="left:' + b.x + "px;top:" + b.y + "px;width:" + b.w + "px;height:" + b.h + 'px"><div class="wdr-label">' + esc(n.label) + "</div></div>";
              }
              el.innerHTML = inner;
            }
            el.className = "wdr-node is-" + n.shape + (self.sel.indexOf(n.id) >= 0 ? " is-selected" : "") + (n.bold ? " is-bold" : "");
            el.style.cssText = "transform:translate(" + n.x + "px," + n.y + "px);width:" + n.w + "px;height:" + n.h + "px;--ink:" + textColor(n, true) + ";--fs:" + (n.size || 14) + "px";
          });
          Object.keys(els).forEach(function (id) { if (!seen[id]) { els[id].remove(); delete els[id]; } });
          this.links();
          this.ui();
          this.empty = !M.nodes.length;
        },
        links: function (extra) {
          if (!this.$refs.links) return;                  // switched to text meanwhile
          var self = this, out = [], pairs = {};
          M.edges.forEach(function (e) {
            var key = [e.from, e.to].sort().join(">");
            pairs[key] = (pairs[key] || 0) + 1; e._k = pairs[key];
          });
          M.edges.forEach(function (e) {
            var a = self.byId(e.from), b = self.byId(e.to); if (!a || !b) return;
            var key = [e.from, e.to].sort().join(">"), many = pairs[key], bend = many > 1 ? (e._k - (many + 1) / 2) * 34 * (e.from < e.to ? 1 : -1) : 0;
            var g = route(e, a, b, bend), on = self.esel === e.id, col = on ? "var(--accent)" : (e.color || "var(--wdr-line)");
            var startMark = self.endMark(e, "start"), endMark = self.endMark(e, "end");
            out.push('<g class="wdr-link' + (on ? " is-selected" : "") + '" data-edge="' + esc(e.id) + '">' +
              '<path class="wdr-hit" d="' + g.d + '"/>' +
              '<path d="' + g.d + '" fill="none" stroke="' + col + '" stroke-width="' + lineWidth(e) + '"' + dash(e) + ' stroke-linejoin="round"/>' +
              mark(endMark, g.b, g.fromB, col, "var(--surface)") + mark(startMark, g.a, g.fromA, col, "var(--surface)") +
              (e.label ? '<text class="wdr-elabel" x="' + g.mid.x + '" y="' + (g.mid.y + 4) + '">' + esc(e.label) + "</text>" : "") +
              (e.fromLabel ? (function () { var q = endLabel(g.a, g.fromA, 1); return '<text class="wdr-elabel is-end" x="' + q.x + '" y="' + q.y + '">' + esc(e.fromLabel) + "</text>"; })() : "") +
              (e.toLabel ? (function () { var q = endLabel(g.b, g.fromB, -1); return '<text class="wdr-elabel is-end" x="' + q.x + '" y="' + q.y + '">' + esc(e.toLabel) + "</text>"; })() : "") +
              "</g>");
          });
          if (extra) out.push(extra);
          this.$refs.links.innerHTML = out.join("");
        },
        /* the mark at one end of a link, with each kind's defaults */
        endMark: function (e, which) {
          var a = this.byId(e.from), b = this.byId(e.to);
          if (e.note || (a && a.shape === "note") || (b && b.shape === "note")) return "none";
          if (this.kind === "state") return which === "end" ? "arrow" : "none";
          var v = e[which];
          if (v === undefined) {
            if (this.kind === "er") return which === "end" ? "zmany" : "one";
            return which === "end" && this.kind !== "class" ? "arrow" : "none";
          }
          return v || "none";
        },
        /* the frame round what's picked, its handles, and the blue arrows */
        ui: function () {
          if (!this.$refs.ui) return;
          var self = this, out = [], one = this.sel.length === 1 ? this.byId(this.sel[0]) : null;
          this.sel.forEach(function (id) {
            var n = self.byId(id); if (!n) return;
            out.push('<div class="wdr-frame" style="transform:translate(' + n.x + "px," + n.y + "px);width:" + n.w + "px;height:" + n.h + 'px"></div>');
          });
          if (one && !this._editing) {
            var dirs = DM.ROWS[one.shape] ? ["e", "w"] : ["nw", "n", "ne", "e", "se", "s", "sw", "w"];
            dirs.forEach(function (dir) {
              var x = one.x + (dir.indexOf("w") >= 0 ? 0 : dir.indexOf("e") >= 0 ? one.w : one.w / 2), y = one.y + (dir.indexOf("n") >= 0 ? 0 : dir.indexOf("s") >= 0 ? one.h : one.h / 2);
              out.push('<i class="wdr-handle" data-handle="' + dir + '" style="left:' + x + "px;top:" + y + 'px"></i>');
            });
          }
          var h = hover && this.byId(hover);
          if (!h && one) h = one;
          if (h && !this._editing && !this._dragging && h.shape !== "container") {
            [["n", h.x + h.w / 2, h.y], ["e", h.x + h.w, h.y + h.h / 2], ["s", h.x + h.w / 2, h.y + h.h], ["w", h.x, h.y + h.h / 2]].forEach(function (a) {
              out.push('<button type="button" class="wdr-arrow" data-arrow="' + a[0] + '" data-for="' + esc(h.id) + '" style="left:' + a[1] + "px;top:" + a[2] + 'px" tabindex="-1" aria-label="' + esc(TEXT.addLinked || "Add") + '"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 2 L14 9 H10 V14 H6 V9 H2 Z"/></svg></button>');
            });
          }
          if (this.esel) {
            var e = this.edgeById(this.esel), a = e && this.byId(e.from), b = e && this.byId(e.to);
            if (a && b) {
              var g = route(e, a, b, 0);
              out.push('<i class="wdr-end" data-end="from" style="left:' + g.a.x + "px;top:" + g.a.y + 'px"></i><i class="wdr-end" data-end="to" style="left:' + g.b.x + "px;top:" + g.b.y + 'px"></i>');
            }
          }
          this.$refs.ui.innerHTML = out.join("");
        },
        bounds: function (list) {
          var b = { x1: Infinity, y1: Infinity, x2: -Infinity, y2: -Infinity };
          (list || M.nodes).forEach(function (n) { b.x1 = Math.min(b.x1, n.x); b.y1 = Math.min(b.y1, n.y); b.x2 = Math.max(b.x2, n.x + n.w); b.y2 = Math.max(b.y2, n.y + n.h); });
          return b;
        },
        fit: function () {
          if (M.nodes.length) this.view.fit(this.bounds(), 40, 1.2, this.$refs.canvas.clientWidth < 600 ? 0.4 : 0);
          else { var r = this.$refs.canvas.getBoundingClientRect(); this.view.k = 1; this.view.x = r.width / 2 - 75; this.view.y = r.height / 2 - 32; this.view.apply(); }
        },
        setGrid: function () { this.grid = !this.grid; try { localStorage.setItem("wdr-grid", this.grid ? "1" : "0"); } catch (e) { /* private window */ } },
        setSnap: function () { this.snap = !this.snap; try { localStorage.setItem("wdr-snap", this.snap ? "1" : "0"); } catch (e) { /* private window */ } },

        /* ── picking ── */
        pick: function (ids, edgeId) {
          this.sel = ids; this.esel = edgeId || null; this._snapFor = null;
          this.node = ids.length === 1 ? this.byId(ids[0]) : null;
          this.edge = edgeId ? this.edgeById(edgeId) : null;
          var self = this;
          Object.keys(els).forEach(function (id) { els[id].classList.toggle("is-selected", ids.indexOf(id) >= 0); });
          this.links(); this.ui();
          if (this.node) { var n = this.node; this.view.reveal({ x1: n.x, y1: n.y, x2: n.x + n.w, y2: n.y + n.h }); }
        },
        /* moved shapes: the bends a tidy-up gave their links no longer fit */
        unpin: function (ns) {
          var ids = {}; ns.forEach(function (n) { ids[n.id] = true; });
          M.edges.forEach(function (e) { if (e.pts && (ids[e.from] || ids[e.to])) delete e.pts; });
        },
        picked: function () { var self = this; return this.sel.map(function (id) { return self.byId(id); }).filter(Boolean); },
        /* a group's shapes, and theirs, all the way down */
        inside: function (id) {
          var out = [], self = this;
          M.nodes.forEach(function (n) { if (n.parent === id && n.id !== id) { out.push(n); out = out.concat(self.inside(n.id)); } });
          return out;
        },

        /* ── adding ── */
        make: function (key, x, y) {
          var it = DM.libraryItem(this.kind, key) || DM.libraryItem("drawing", key) || ["rect", "rect", 150, 64];
          var extra = it[4] || {}, n = { id: uid(), shape: it[1], w: it[2], h: it[3], label: this.defaultLabel(it), x: 0, y: 0 };
          Object.keys(extra).forEach(function (k) { n[k] = extra[k]; });
          if (n.shape === "class") { n.attrs = extra.stereo === "enumeration" ? "VALUE_ONE\nVALUE_TWO" : extra.stereo ? "" : "+id: int"; n.methods = extra.stereo === "enumeration" ? "" : "+run()"; this.fitRows(n); }
          if (n.shape === "entity") { n.attrs = "int id PK\nstring name"; this.fitRows(n); }
          n.x = snapTo(x - n.w / 2, this.snap); n.y = snapTo(y - n.h / 2, this.snap);
          return n;
        },
        defaultLabel: function (it) {
          if (DM.TIGHT[it[1]]) return "";
          if (it[1] === "class") return { interface: "Shape", abstract: "Base", enumeration: "Status" }[(it[4] || {}).stereo] || "MyClass";
          if (it[1] === "entity") return "TABLE";
          return (TEXT.starts || {})[it[0]] || (TEXT.shapes || {})[it[0]] || "";
        },
        add: function (key, x, y) {
          var n = this.make(key, x, y);
          this.snapshot();
          if (n.shape === "container") M.nodes.unshift(n); else M.nodes.push(n);
          this.adopt([n]);
          this.render(); this.pick([n.id]); this.save(); this.$refs.canvas.focus({ preventScroll: true });
          return n;
        },
        paletteClick: function (key) {
          if (this._paletteDragged) { this._paletteDragged = false; return; }
          var r = this.$refs.canvas.getBoundingClientRect(), c = this.view.toWorld(r.left + r.width / 2, r.top + r.height / 2), k = M.nodes.length % 6;
          this.add(key, c.x + k * 16, c.y + k * 16);
        },
        paletteDown: function (e, key) {
          if (e.button > 0) return;
          var self = this, sx = e.clientX, sy = e.clientY, ghost = null, svg = e.currentTarget.querySelector("svg");
          function move(ev) {
            if (!ghost && Math.hypot(ev.clientX - sx, ev.clientY - sy) < 8) return;
            if (!ghost) { ghost = d.createElement("div"); ghost.className = "wsb-ghost wdr-ghost"; ghost.innerHTML = svg ? svg.outerHTML : ""; d.body.appendChild(ghost); self._paletteDragged = true; }
            ghost.style.transform = "translate(" + (ev.clientX - 22) + "px," + (ev.clientY - 22) + "px)";
          }
          function up(ev) {
            d.removeEventListener("pointermove", move); d.removeEventListener("pointerup", up); d.removeEventListener("pointercancel", up);
            if (!ghost) return;
            ghost.remove();
            var r = self.$refs.canvas.getBoundingClientRect();
            if (ev.clientX >= r.left && ev.clientX <= r.right && ev.clientY >= r.top && ev.clientY <= r.bottom) { var p = self.view.toWorld(ev.clientX, ev.clientY); self.add(key, p.x, p.y); }
            setTimeout(function () { self._paletteDragged = false; }, 50);
          }
          d.addEventListener("pointermove", move); d.addEventListener("pointerup", up); d.addEventListener("pointercancel", up);
        },
        /* a shape like `n` for the blue arrows: the same, or the kind's main shape after a start, an end, a note… */
        copyOf: function (n, x, y) {
          var shape = NO_CLONE[n.shape] || (this.kind === "state" && n.shape === "diamond") ? MAIN[this.kind] : n.shape;
          var it = null, lib = DM.LIBRARY[this.kind] || DM.LIBRARY.drawing;
          for (var i = 0; i < lib.length; i++) if (lib[i][1] === shape) { it = lib[i]; break; }
          var c = this.make(it ? it[0] : "rect", x, y);
          if (shape === n.shape && !DM.ROWS[shape]) { c.w = n.w; c.h = n.h; c.fill = n.fill; c.stroke = n.stroke; c.size = n.size; c.x = snapTo(x - c.w / 2, this.snap); c.y = snapTo(y - c.h / 2, this.snap); }
          if (!DM.ROWS[shape]) c.label = "";
          if (n.parent) c.parent = n.parent;
          ["fill", "stroke", "size"].forEach(function (k) { if (c[k] == null) delete c[k]; });
          return c;
        },
        /* a click on a blue arrow: a linked copy that way */
        addLinked: function (id, dir) {
          var n = this.byId(id); if (!n) return;
          var probe = this.copyOf(n, 0, 0), gap = 70;
          var cx = n.x + n.w / 2 + (dir === "e" ? n.w / 2 + gap + probe.w / 2 : dir === "w" ? -(n.w / 2 + gap + probe.w / 2) : 0);
          var cy = n.y + n.h / 2 + (dir === "s" ? n.h / 2 + gap + probe.h / 2 : dir === "n" ? -(n.h / 2 + gap + probe.h / 2) : 0);
          var c = this.copyOf(n, cx, cy);
          this.snapshot();
          M.nodes.push(c);
          this.link(n.id, c.id, true);
          this.render(); this.pick([c.id]); this.save();
          if (!DM.TIGHT[c.shape]) this.editText(c.id);
        },
        newEdge: function (from, to) {
          var e = { id: uid(), from: from, to: to, line: "solid" }, a = this.byId(from), b = this.byId(to);
          if (this.kind === "er") { e.start = "one"; e.end = "zmany"; e.label = ""; }
          else if (this.kind === "class") e.end = "arrow";
          if ((a && a.shape === "note") || (b && b.shape === "note")) { e.note = true; e.line = "dashed"; e.end = "none"; }
          if (this._lastRoute) e.route = this._lastRoute;
          return e;
        },
        link: function (from, to, quiet) {
          if (!from || !to) return null;
          if (from === to && this.kind !== "state" && this.kind !== "flowchart" && this.kind !== "drawing") return null;
          if (!quiet) this.snapshot();
          var e = this.newEdge(from, to);
          M.edges.push(e);
          if (!quiet) { this.render(); this.pick([], e.id); this.save(); }
          return e;
        },

        /* ── changing ── */
        removeSelected: function () {
          if (!this.sel.length && !this.esel) return;
          this.snapshot();
          var gone = this.sel, self = this;
          if (gone.length) {
            // a group goes; what was in it stays (in the group around it)
            gone.forEach(function (id) { var g = self.byId(id); if (g && g.shape === "container") M.nodes.forEach(function (n) { if (n.parent === id) { if (g.parent) n.parent = g.parent; else delete n.parent; } }); });
            M.nodes = M.nodes.filter(function (n) { return gone.indexOf(n.id) < 0; });
            M.edges = M.edges.filter(function (e) { return gone.indexOf(e.from) < 0 && gone.indexOf(e.to) < 0; });
          } else { var eid = this.esel; M.edges = M.edges.filter(function (e) { return e.id !== eid; }); }
          this.pick([]); this.render(); this.save(); this.$refs.canvas.focus({ preventScroll: true });
        },
        duplicate: function () {
          var ns = this.picked(); if (!ns.length) return;
          this.paste({ nodes: clone(ns.concat(this.allInside(ns))), edges: clone(this.edgesWithin(ns)) }, 20);
        },
        allInside: function (ns) {
          var self = this, ids = {}, out = [];
          ns.forEach(function (n) { ids[n.id] = true; });
          ns.forEach(function (n) { if (n.shape === "container") self.inside(n.id).forEach(function (k) { if (!ids[k.id]) { ids[k.id] = true; out.push(k); } }); });
          return out;
        },
        edgesWithin: function (ns) {
          var ids = {}; ns.concat(this.allInside(ns)).forEach(function (n) { ids[n.id] = true; });
          return M.edges.filter(function (e) { return ids[e.from] && ids[e.to]; });
        },
        copy: function (cut) {
          var ns = this.picked(); if (!ns.length) return;
          var clip = { kind: this.kind, nodes: clone(ns.concat(this.allInside(ns))), edges: clone(this.edgesWithin(ns)) };
          this._clip = clip;
          try { localStorage.setItem("wdr-clip", JSON.stringify(clip)); } catch (e) { /* private window */ }
          if (cut) this.removeSelected(); else toast(TEXT.copiedParts);
        },
        paste: function (clip, offset) {
          var fromClip = !clip;
          if (!clip) { clip = this._clip; try { clip = JSON.parse(localStorage.getItem("wdr-clip") || "null") || clip; } catch (e) { /* the one in memory */ } }
          if (!clip || !clip.nodes || !clip.nodes.length) return;
          var allowed = DM.shapesOf(this.kind), main = MAIN[this.kind], self = this;
          var b = this.bounds(clip.nodes), at = fromClip && this._pointer ? this.view.toWorld(this._pointer.x, this._pointer.y) : { x: b.x1 + (offset || 30), y: b.y1 + (offset || 30) };
          var dx = snapTo(at.x - b.x1, this.snap), dy = snapTo(at.y - b.y1, this.snap), map = {}, made = [];
          this.snapshot();
          clip.nodes.forEach(function (n) { map[n.id] = uid(); });
          clip.nodes.forEach(function (n) {
            var c = clone(n); c.id = map[n.id]; c.x += dx; c.y += dy;
            if (c.parent) { if (map[c.parent]) c.parent = map[c.parent]; else delete c.parent; }
            if (allowed.indexOf(c.shape) < 0) { c.shape = main; if (DM.ROWS[main]) self.fitRows(c); }
            made.push(c.id);
            if (c.shape === "container") M.nodes.unshift(c); else M.nodes.push(c);
          });
          clip.edges.forEach(function (e) {
            var c = clone(e); c.id = uid(); c.from = map[e.from]; c.to = map[e.to];
            if (c.pts) c.pts = c.pts.map(function (q) { return [q[0] + dx, q[1] + dy]; });
            if (c.from && c.to) M.edges.push(c);
          });
          var top = made.filter(function (id) { var n = self.byId(id); return !n.parent || made.indexOf(n.parent) < 0; });
          this.render(); this.pick(top); this.save();
          if (fromClip) toast(TEXT.pasted);
        },
        reverse: function () { if (!this.edge) return; this.snapshot(); var e = this.edge, t = e.from; e.from = e.to; e.to = t; t = e.start; e.start = e.end; e.end = t; t = e.fromLabel; e.fromLabel = e.toLabel; e.toLabel = t; ["start", "end", "fromLabel", "toLabel"].forEach(function (k) { if (e[k] === undefined) delete e[k]; }); this.render(); this.save(); },
        setEdge: function (key, value) {
          if (!this.edge) return;
          this.snapshot(); this.edge[key] = value;
          if (key === "route") this._lastRoute = value || undefined;
          if (!value && key === "route") delete this.edge.route;
          this.render(); this.save();
        },
        classLink: function (preset) {
          if (!this.edge) return;
          this.snapshot(); this.edge.line = preset[1]; this.edge.start = preset[2]; this.edge.end = preset[3];
          this.render(); this.save();
        },
        classLinkOf: function () {
          var e = this.edge; if (!e) return "";
          for (var i = 0; i < CLASS_LINKS.length; i++) { var c = CLASS_LINKS[i]; if ((e.line || "solid") === c[1] && (e.start || "") === c[2] && (e.end || "") === c[3]) return c[0]; }
          return "";
        },
        style: function (key, value) {
          var ns = this.picked(); if (!ns.length) return;
          this.snapshot();
          ns.forEach(function (n) { n = rx(n); if (value === "" || value == null) delete n[key]; else n[key] = value; });
          this.render(); this.save();
        },
        reshape: function (shape) {
          var ns = this.picked(); if (!ns.length) return;
          var self = this; this.snapshot();
          ns.forEach(function (n) {
            n = rx(n);
            if (DM.ROWS[n.shape] !== DM.ROWS[shape]) return;          // a class stays a class, a box a box
            n.shape = shape;
            if (shape === "circle" || shape === "dcircle") n.w = n.h = Math.max(n.w, n.h);
            if (DM.TIGHT[shape]) { var it = DM.LIBRARY.drawing.filter(function (x) { return x[1] === shape; })[0]; if (it) { n.w = it[2]; n.h = it[3]; } }
            if (DM.ROWS[shape]) self.fitRows(n);
          });
          this.render(); this.save();
        },
        front: function (toBack) {
          var ns = this.picked(); if (!ns.length) return;
          this.snapshot();
          M.nodes = M.nodes.filter(function (n) { return ns.indexOf(n) < 0; });
          M.nodes = toBack ? ns.concat(M.nodes) : M.nodes.concat(ns);
          this.render(); this.save();
        },
        align: function (how) {
          var ns = this.picked(); if (ns.length < 2) return;
          var b = this.bounds(ns), self = this;
          this.snapshot(); this.unpin(ns.concat(this.allInside(ns)));
          ns.forEach(function (n) {
            var ox = n.x, oy = n.y;
            if (how === "left") n.x = b.x1; else if (how === "right") n.x = b.x2 - n.w; else if (how === "hcenter") n.x = Math.round((b.x1 + b.x2) / 2 - n.w / 2);
            else if (how === "top") n.y = b.y1; else if (how === "bottom") n.y = b.y2 - n.h; else if (how === "vmiddle") n.y = Math.round((b.y1 + b.y2) / 2 - n.h / 2);
            if (n.shape === "container") self.inside(n.id).forEach(function (k) { k.x += n.x - ox; k.y += n.y - oy; });
          });
          this.render(); this.save();
        },
        distribute: function (axis) {
          var ns = this.picked(); if (ns.length < 3) return;
          var pos = axis === "x" ? function (n) { return n.x + n.w / 2; } : function (n) { return n.y + n.h / 2; };
          ns.sort(function (a, b) { return pos(a) - pos(b); });
          var first = pos(ns[0]), step = (pos(ns[ns.length - 1]) - first) / (ns.length - 1);
          this.snapshot(); this.unpin(ns);
          ns.forEach(function (n, i) { var c = Math.round(first + step * i); if (axis === "x") n.x = c - n.w / 2; else n.y = c - n.h / 2; });
          this.render(); this.save();
        },
        sameSize: function () {
          var ns = this.picked(); if (ns.length < 2) return;
          this.snapshot(); this.unpin(ns); var w = ns[0].w, h = ns[0].h; ns.forEach(function (n) { n.w = w; if (!DM.ROWS[n.shape]) n.h = h; });
          this.render(); this.save();
        },
        /* put the picked shapes in a group (a container round them) — or take a group apart */
        group: function () {
          var ns = this.picked(); if (!ns.length) return;
          if (DM.shapesOf(this.kind).indexOf("container") < 0) return;
          var b = this.bounds(ns), parent = ns[0].parent, pad = 24;
          var g = { id: uid(), shape: "container", label: (TEXT.shapes || {}).container || "Group", x: b.x1 - pad, y: b.y1 - pad - 22, w: b.x2 - b.x1 + pad * 2, h: b.y2 - b.y1 + pad * 2 + 22 };
          if (parent && ns.every(function (n) { return n.parent === parent; })) g.parent = parent;
          this.snapshot();
          M.nodes.unshift(g);
          ns.forEach(function (n) { n.parent = g.id; });
          this.render(); this.pick([g.id]); this.save();
        },
        ungroup: function () {
          var gs = this.picked().filter(function (n) { return n.shape === "container"; }); if (!gs.length) return;
          var kids = [];
          gs.forEach(function (g) { M.nodes.forEach(function (n) { if (n.parent === g.id) kids.push(n.id); }); });
          this.sel = gs.map(function (g) { return g.id; });
          this.removeSelected();
          this.pick(kids);
        },
        /* after a move or a drop: a shape whose middle is in a group belongs to it (the smallest one) */
        adopt: function (ns) {
          var self = this;
          ns.forEach(function (n) {
            if (DM.TIGHT[n.shape] && n.shape !== "start" && n.shape !== "end" && n.shape !== "fork") return;
            var c = centre(n), mine = self.inside(n.id).map(function (k) { return k.id; }), best = null;
            M.nodes.forEach(function (g) {
              if (g.shape !== "container" || g === n || mine.indexOf(g.id) >= 0) return;
              if (c.x > g.x && c.x < g.x + g.w && c.y > g.y && c.y < g.y + g.h && (!best || g.w * g.h < best.w * best.h)) best = g;
            });
            if (best) n.parent = best.id; else delete n.parent;
          });
        },
        tidy: function (dir) {
          if (!M.nodes.length) return;
          this.snapshot();
          if (dir) M.dir = dir;
          DM.layout(M, M.dir || "TD");
          this.render(); this.save(); this.fit(); this.menu = false;
        },

        /* ── words on shapes and links ── */
        editText: function (id, first) {
          var el = els[id], n = this.byId(id); if (!el || !n || DM.TIGHT[n.shape]) return;
          var t = el.querySelector(".wdr-label"); if (!t) return;
          var self = this, before = n.label || "";
          this._editing = id; this.ui();
          try { t.contentEditable = "plaintext-only"; } catch (err) { t.contentEditable = "true"; }
          if (t.contentEditable !== "plaintext-only") t.contentEditable = "true";
          el.classList.add("is-editing");
          if (first != null) t.textContent = first;
          t.focus();
          var r = d.createRange(); r.selectNodeContents(t); if (first != null) r.collapse(false);
          var s = window.getSelection(); s.removeAllRanges(); s.addRange(r);
          function done(keep) {
            t.removeEventListener("keydown", onKey); t.removeEventListener("blur", onBlur);
            t.contentEditable = "false"; el.classList.remove("is-editing"); self._editing = null;
            var v = keep ? (t.innerText || "").replace(/\n+$/, "").replace(/ /g, " ").slice(0, 2000) : before;
            if (DM.ROWS[n.shape]) v = v.replace(/\s+/g, n.shape === "entity" ? "_" : " ").trim();
            if (v !== before) {
              self.snapshot(); rx(n).label = v;
              if (DM.ROWS[n.shape]) self.fitRows(n);
              else { var need = DM.fitSize({ shape: n.shape, label: v, size: n.size, w: n.w, h: n.h }, [null, n.shape, n.w, n.h]); if (need.h > n.h) n.h = need.h; }
              self.save();
            }
            el._sig = null; self.render(); self.pick([id]);
          }
          function onKey(e) {
            e.stopPropagation();
            if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); done(true); self.$refs.canvas.focus({ preventScroll: true }); }
            else if (e.key === "Escape") { e.preventDefault(); done(false); self.$refs.canvas.focus({ preventScroll: true }); }
          }
          function onBlur() { done(true); }
          t.addEventListener("keydown", onKey); t.addEventListener("blur", onBlur);
        },
        editEdge: function (id) {
          var e = this.edgeById(id), a = e && this.byId(e.from), b = e && this.byId(e.to); if (!a || !b) return;
          var self = this, g = route(e, a, b, 0), box = d.createElement("input");
          box.className = "form-input input-compact wdr-edit"; box.value = e.label || ""; box.maxLength = 200;
          box.style.left = g.mid.x + "px"; box.style.top = g.mid.y + "px";
          box.setAttribute("aria-label", TEXT.linkLabel || "Label");
          this.$refs.world.appendChild(box); box.focus(); box.select();
          var gone = false;
          function done(keep) {
            if (gone) return; gone = true;
            var v = box.value.trim(); box.remove();
            if (keep && v !== (e.label || "")) { self.snapshot(); if (v) e.label = v; else if (self.kind === "er") e.label = ""; else delete e.label; self.render(); self.save(); }
            self.pick([], id); self.$refs.canvas.focus({ preventScroll: true });
          }
          box.addEventListener("keydown", function (ev) { ev.stopPropagation(); if (ev.key === "Enter") { ev.preventDefault(); done(true); } else if (ev.key === "Escape") { ev.preventDefault(); done(false); } });
          box.addEventListener("blur", function () { done(true); });
          box.addEventListener("pointerdown", function (ev) { ev.stopPropagation(); });
        },

        /* ── keys ── */
        key: function (e) {
          if (/^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName) || e.target.isContentEditable) return;
          var k = e.key, mod = e.ctrlKey || e.metaKey, done = true, self = this;
          if (k === " ") { spaceDown = true; this.$refs.canvas.classList.add("is-space"); e.preventDefault(); return; }
          if (mod && (k === "z" || k === "Z")) { if (e.shiftKey) this.redo(); else this.undo(); }
          else if (mod && k === "y") this.redo();
          else if (mod && k === "d") this.duplicate();
          else if (mod && (k === "c" || k === "x") && this.sel.length && !String(window.getSelection())) this.copy(k === "x");
          else if (mod && k === "v") this.paste();
          else if (mod && k === "a") this.pick(M.nodes.map(function (n) { return n.id; }));
          else if (mod && (k === "g" || k === "G")) { if (e.shiftKey) this.ungroup(); else this.group(); }
          else if (mod && e.shiftKey && (k === "f" || k === "F")) this.front(false);
          else if (mod && e.shiftKey && (k === "b" || k === "B")) this.front(true);
          else if (mod) done = false;
          else if (k === "Delete" || k === "Backspace") this.removeSelected();
          else if (k === "Escape") { this.pick([]); this.area = false; }
          else if ((k === "Enter" || k === "F2") && this.node) this.editText(this.node.id);
          else if ((k === "Enter" || k === "F2") && this.edge) this.editEdge(this.edge.id);
          else if (k === "0") this.fit(); else if (k === "+" || k === "=") this.view.zoomBy(1.2); else if (k === "-") this.view.zoomBy(1 / 1.2);
          else if (/^Arrow/.test(k) && this.sel.length) {
            var step = e.shiftKey ? 1 : GRID, dx = k === "ArrowLeft" ? -step : k === "ArrowRight" ? step : 0, dy = k === "ArrowUp" ? -step : k === "ArrowDown" ? step : 0;
            if (!this._nudging) { this.snapshot(); this._nudging = true; }
            clearTimeout(this._nudgeT); this._nudgeT = setTimeout(function () { self._nudging = false; }, 600);
            var moving = this.picked(); moving = moving.concat(this.allInside(moving));
            this.unpin(moving);
            moving.forEach(function (n) { n.x += dx; n.y += dy; });
            this.render(); this.save();
          }
          else if (this.node && k.length === 1 && !e.altKey && !DM.TIGHT[this.node.shape]) { this.editText(this.node.id, k); }    // just type: it replaces the words
          else done = false;
          if (done) { e.preventDefault(); e.stopPropagation(); }
        },
        keyUp: function (e) { if (e.key === " ") { spaceDown = false; this.$refs.canvas.classList.remove("is-space"); } },

        /* ── the mouse and fingers ── */
        guides: function (moving, dx, dy) {
          // line the moving box up with the others' edges and middles (draw.io's guides)
          var b = this.bounds(moving), ids = {}, k = this.view.k, tol = 6 / k, best = { x: null, y: null };
          moving.forEach(function (n) { ids[n.id] = true; });
          var box = { x1: b.x1 + dx, x2: b.x2 + dx, y1: b.y1 + dy, y2: b.y2 + dy };
          var xs = [box.x1, (box.x1 + box.x2) / 2, box.x2], ys = [box.y1, (box.y1 + box.y2) / 2, box.y2];
          M.nodes.forEach(function (n) {
            if (ids[n.id]) return;
            [n.x, n.x + n.w / 2, n.x + n.w].forEach(function (gx) { xs.forEach(function (x) { var dd = gx - x; if (Math.abs(dd) <= tol && (best.x === null || Math.abs(dd) < Math.abs(best.x.d))) best.x = { d: dd, at: gx, n: n }; }); });
            [n.y, n.y + n.h / 2, n.y + n.h].forEach(function (gy) { ys.forEach(function (y) { var dd = gy - y; if (Math.abs(dd) <= tol && (best.y === null || Math.abs(dd) < Math.abs(best.y.d))) best.y = { d: dd, at: gy, n: n }; }); });
          });
          var lines = [];
          if (best.x) { var n1 = best.x.n; lines.push('<line x1="' + best.x.at + '" y1="' + Math.min(n1.y, box.y1) + '" x2="' + best.x.at + '" y2="' + Math.max(n1.y + n1.h, box.y2) + '"/>'); }
          if (best.y) { var n2 = best.y.n; lines.push('<line x1="' + Math.min(n2.x, box.x1) + '" y1="' + best.y.at + '" x2="' + Math.max(n2.x + n2.w, box.x2) + '" y2="' + best.y.at + '"/>'); }
          this.$refs.guides.innerHTML = lines.join("");
          return { dx: best.x ? best.x.d : null, dy: best.y ? best.y.d : null };
        },
        pointers: function () {
          var self = this, c = this.$refs.canvas, act = null, lastTap = { id: null, t: 0 };
          c.addEventListener("pointerdown", function (e) {
            if (e.target.isContentEditable || e.target.classList.contains("wdr-edit")) return;
            var nodeEl = e.target.closest(".wdr-node"), id = nodeEl && nodeEl.getAttribute("data-id");
            var handle = e.target.closest(".wdr-handle"), arrow = e.target.closest(".wdr-arrow"), end = e.target.closest(".wdr-end"), linkEl = e.target.closest(".wdr-link");
            c.focus({ preventScroll: true });
            if (e.button === 1 || (e.button === 0 && spaceDown) || e.button === 2) { act = { kind: "pan" }; self.view.down(e); e.preventDefault(); return; }
            if (handle && self.node) {
              var n0 = self.node; self.snapshot(); self._dragging = true; self.unpin([n0]);
              act = { kind: "resize", dir: handle.getAttribute("data-handle"), n: n0, x: e.clientX, y: e.clientY, box: { x: n0.x, y: n0.y, w: n0.w, h: n0.h } };
              c.setPointerCapture(e.pointerId); e.preventDefault(); return;
            }
            if (arrow) {
              act = { kind: "arrow", from: arrow.getAttribute("data-for"), dir: arrow.getAttribute("data-arrow"), x: e.clientX, y: e.clientY, moved: false };
              c.setPointerCapture(e.pointerId); e.preventDefault(); return;
            }
            if (end && self.edge) { act = { kind: "reconnect", e: self.edge, which: end.getAttribute("data-end") }; self._dragging = true; c.setPointerCapture(e.pointerId); e.preventDefault(); return; }
            if (id && e.isPrimary) {
              var picked = self.sel.indexOf(id) >= 0 ? self.sel.slice() : (e.shiftKey || e.ctrlKey || e.metaKey ? self.sel.concat([id]) : [id]);
              if ((e.shiftKey || e.ctrlKey || e.metaKey) && self.sel.indexOf(id) >= 0) picked = self.sel.filter(function (x) { return x !== id; });
              if (picked.join() !== self.sel.join() || self.esel) self.pick(picked);
              var moving = self.picked(); moving = moving.concat(self.allInside(moving));
              act = { kind: "move", id: id, x: e.clientX, y: e.clientY, moved: false, start: moving.map(function (n) { return { n: n, x: n.x, y: n.y }; }), list: moving };
              c.setPointerCapture(e.pointerId); e.preventDefault();
              return;
            }
            if (linkEl) {
              var eid = linkEl.getAttribute("data-edge"), now = Date.now();
              self.pick([], eid); e.preventDefault();
              if (lastTap.id === "e:" + eid && now - lastTap.t < 450) self.editEdge(eid);
              lastTap = { id: "e:" + eid, t: now };
              return;
            }
            // the background: a mouse drags a box to pick shapes; a finger moves the page (or picks, with the area tool on)
            if ((e.pointerType === "mouse" || self.area || e.shiftKey) && e.isPrimary) {
              var r0 = c.getBoundingClientRect();
              act = { kind: "box", x: e.clientX, y: e.clientY, add: e.shiftKey, left: r0.left, top: r0.top };
              c.setPointerCapture(e.pointerId); e.preventDefault(); return;
            }
            act = { kind: "pan" };
            self.view.down(e);
          });
          c.addEventListener("contextmenu", function (e) { e.preventDefault(); });
          c.addEventListener("pointermove", function (e) {
            self._pointer = { x: e.clientX, y: e.clientY };
            if (!act) {
              // the blue arrows follow the mouse from shape to shape
              if (e.pointerType !== "mouse") return;
              var over = e.target.closest(".wdr-node"), oid = over && over.getAttribute("data-id");
              if (e.target.closest(".wdr-arrow")) { clearTimeout(hoverT); return; }
              if (oid !== hover) {
                clearTimeout(hoverT);
                if (oid) { hover = oid; self.ui(); }
                else hoverT = setTimeout(function () { hover = null; self.ui(); }, 380);
              }
              return;
            }
            if (act.kind === "pan") { self.view.move(e); return; }
            if (act.kind === "box") {
              var bx = self.$refs.box; bx.hidden = false;
              bx.style.left = Math.min(act.x, e.clientX) - act.left + "px"; bx.style.top = Math.min(act.y, e.clientY) - act.top + "px";
              bx.style.width = Math.abs(e.clientX - act.x) + "px"; bx.style.height = Math.abs(e.clientY - act.y) + "px";
              act.to = { x: e.clientX, y: e.clientY }; return;
            }
            var p = self.view.toWorld(e.clientX, e.clientY), k = self.view.k;
            if (act.kind === "move") {
              var dx = (e.clientX - act.x) / k, dy = (e.clientY - act.y) / k;
              if (!act.moved && Math.abs(dx) + Math.abs(dy) < 4 / k) return;
              if (!act.moved) { act.moved = true; self.snapshot(); self._dragging = true; hover = null; self.unpin(act.list); }
              var snapOn = self.snap && !e.altKey, lead = act.start[0];
              // snap the first picked shape to the grid, then let the guides pull everything into line
              var sdx = snapOn ? snapTo(lead.x + dx, true) - lead.x : dx, sdy = snapOn ? snapTo(lead.y + dy, true) - lead.y : dy;
              var origin = act.start.map(function (s) { return { id: s.n.id, x: s.x, y: s.y, w: s.n.w, h: s.n.h }; });
              var gd = e.altKey ? { dx: null, dy: null } : self.guides(origin, dx, dy);
              if (gd.dx !== null) sdx = dx + gd.dx;
              if (gd.dy !== null) sdy = dy + gd.dy;
              act.start.forEach(function (s) { s.n.x = Math.round(s.x + sdx); s.n.y = Math.round(s.y + sdy); });
              // the group it would drop into
              var lead2 = act.start[0].n, cc = centre(lead2), target = null, mine = act.list.map(function (n) { return n.id; });
              M.nodes.forEach(function (g) { if (g.shape === "container" && mine.indexOf(g.id) < 0 && cc.x > g.x && cc.x < g.x + g.w && cc.y > g.y && cc.y < g.y + g.h && (!target || g.w * g.h < target.w * target.h)) target = g; });
              Object.keys(els).forEach(function (kk) { els[kk].classList.toggle("is-drop", !!target && kk === target.id); });
              self.render();
            } else if (act.kind === "resize") {
              var b = act.box, n = act.n, ddx = (e.clientX - act.x) / k, ddy = (e.clientY - act.y) / k, dir = act.dir, x1 = b.x, y1 = b.y, x2 = b.x + b.w, y2 = b.y + b.h;
              if (dir.indexOf("w") >= 0) x1 = Math.min(x2 - 12, b.x + ddx);
              if (dir.indexOf("e") >= 0) x2 = Math.max(x1 + 12, b.x + b.w + ddx);
              if (dir.indexOf("n") >= 0) y1 = Math.min(y2 - 6, b.y + ddy);
              if (dir.indexOf("s") >= 0) y2 = Math.max(y1 + 6, b.y + b.h + ddy);
              if (e.shiftKey && dir.length === 2) {            // keep the proportions
                var ratio = b.w / b.h, nw = x2 - x1, nh = y2 - y1;
                if (nw / nh > ratio) nh = nw / ratio; else nw = nh * ratio;
                if (dir.indexOf("w") >= 0) x1 = x2 - nw; else x2 = x1 + nw;
                if (dir.indexOf("n") >= 0) y1 = y2 - nh; else y2 = y1 + nh;
              }
              var so = self.snap && !e.altKey;
              n.x = snapTo(x1, so && dir.indexOf("w") >= 0 ? true : false); n.y = snapTo(y1, so && dir.indexOf("n") >= 0);
              n.w = Math.max(12, snapTo(x2, so && dir.indexOf("e") >= 0) - n.x); n.h = Math.max(6, snapTo(y2, so && dir.indexOf("s") >= 0) - n.y);
              if (DM.ROWS[n.shape]) { n.y = b.y; n.h = b.h; }
              self.render();
            } else if (act.kind === "arrow" || act.kind === "reconnect") {
              if (act.kind === "arrow" && !act.moved && Math.hypot(e.clientX - act.x, e.clientY - act.y) < 6) return;
              act.moved = true; self._dragging = true;
              var under = d.elementFromPoint(e.clientX, e.clientY), t = under && under.closest(".wdr-node"), tid = t && t.getAttribute("data-id");
              var fixed = act.kind === "arrow" ? act.from : (act.which === "from" ? act.e.to : act.e.from);
              Object.keys(els).forEach(function (kk) { els[kk].classList.toggle("is-target", kk === tid); });
              act.to = tid;
              var a = self.byId(fixed), s = perimeter(a, p.x, p.y);
              self.links('<line class="wdr-temp" x1="' + s.x + '" y1="' + s.y + '" x2="' + p.x + '" y2="' + p.y + '"/>');
              self.$refs.ui.innerHTML = "";
            }
          });
          function end(e) {
            if (!act) return;
            var a = act; act = null; self._dragging = false;
            self.$refs.guides.innerHTML = "";
            Object.keys(els).forEach(function (kk) { els[kk].classList.remove("is-drop", "is-target"); });
            if (a.kind === "pan") { if (!self.view.up(e)) { if (self.sel.length || self.esel) self.pick([]); } return; }
            if (a.kind === "box") {
              self.$refs.box.hidden = true;
              if (!a.to) { if (!a.add) self.pick([]); return; }
              var p1 = self.view.toWorld(Math.min(a.x, a.to.x), Math.min(a.y, a.to.y)), p2 = self.view.toWorld(Math.max(a.x, a.to.x), Math.max(a.y, a.to.y));
              var inside = M.nodes.filter(function (n) { return n.x >= p1.x && n.y >= p1.y && n.x + n.w <= p2.x && n.y + n.h <= p2.y; }).map(function (n) { return n.id; });
              self.pick(a.add ? self.sel.concat(inside.filter(function (id) { return self.sel.indexOf(id) < 0; })) : inside);
              return;
            }
            if (a.kind === "move") {
              if (a.moved) { self.adopt(a.start.map(function (s) { return s.n; }).filter(function (n) { return self.sel.indexOf(n.id) >= 0; })); self.render(); self.save(); }
              else {
                var now = Date.now();
                if (lastTap.id === a.id && now - lastTap.t < 450) self.editText(a.id);
                lastTap = { id: a.id, t: now };
                self.ui();
              }
              return;
            }
            if (a.kind === "resize") { self.render(); self.save(); return; }
            if (a.kind === "arrow") {
              if (!a.moved) { self.addLinked(a.from, a.dir); return; }
              if (a.to && a.to !== a.from) { self.link(a.from, a.to); return; }
              if (a.to === a.from) { self.links(); self.ui(); return; }
              // let go on the empty page: a new shape there, linked
              var src = self.byId(a.from), at = self.view.toWorld(e.clientX, e.clientY), cp = self.copyOf(src, at.x, at.y);
              self.snapshot(); M.nodes.push(cp); self.link(src.id, cp.id, true); self.adopt([cp]);
              self.render(); self.pick([cp.id]); self.save();
              if (!DM.TIGHT[cp.shape]) self.editText(cp.id);
              return;
            }
            if (a.kind === "reconnect") {
              if (a.to) { self.snapshot(); a.e[a.which] = a.to; delete a.e.pts; self.render(); self.save(); }
              else self.links();
              self.pick([], a.e.id);
            }
          }
          c.addEventListener("pointerup", end); c.addEventListener("pointercancel", end);
          c.addEventListener("dblclick", function (e) {
            var n = e.target.closest(".wdr-node");
            if (n) { self.editText(n.getAttribute("data-id")); return; }
            if (e.target.closest(".wdr-link") || e.target.closest(".wdr-ui > *")) return;
            var p = self.view.toWorld(e.clientX, e.clientY), lib = DM.LIBRARY[self.kind] || DM.LIBRARY.drawing, main = MAIN[self.kind], key = lib[0][0];
            for (var i = 0; i < lib.length; i++) if (lib[i][1] === main) { key = lib[i][0]; break; }
            var made = self.add(key, p.x, p.y);
            if (!DM.TIGHT[made.shape]) self.editText(made.id);
          });
          c.addEventListener("pointerleave", function () { self._pointer = null; clearTimeout(hoverT); hoverT = setTimeout(function () { hover = null; self.ui(); }, 380); });
          window.addEventListener("keyup", function (e) { self.keyUp(e); });
          window.addEventListener("blur", function () { spaceDown = false; c.classList.remove("is-space"); });
        },

        /* ── the picture (export, and the list) ── */
        toSVG: function () {
          if (!M.nodes.length) return null;
          var self = this, b = this.bounds(), pad = 30, out = [];
          M.nodes.forEach(function (n) { if (n.shape === "actor" && n.label) { b.y2 = Math.max(b.y2, n.y + n.h + 24); b.x1 = Math.min(b.x1, n.x - 30); b.x2 = Math.max(b.x2, n.x + n.w + 30); } });
          M.edges.forEach(function (e) {
            if (!e.label && !e.fromLabel && !e.toLabel) return;
            var a = self.byId(e.from), bb = self.byId(e.to); if (!a || !bb) return;
            var g = route(e, a, bb, 0);
            b.x1 = Math.min(b.x1, g.mid.x - 60); b.x2 = Math.max(b.x2, g.mid.x + 60); b.y1 = Math.min(b.y1, g.mid.y - 20);
          });
          var w = Math.ceil(b.x2 - b.x1 + pad * 2), h = Math.ceil(b.y2 - b.y1 + pad * 2), ox = pad - b.x1, oy = pad - b.y1;
          function words(n) {
            if (DM.TIGHT[n.shape]) return "";
            var col = textColor(n, false), fs = n.size || 14;
            if (n.shape === "class" || n.shape === "entity") {
              var o = [], y = n.y + 20, lh = DM.ROW_H;
              if (n.stereo) { o.push('<text x="' + (n.x + n.w / 2) + '" y="' + (y - 4) + '" font-size="11" text-anchor="middle" fill="' + col + '">«' + esc(n.stereo) + "»</text>"); y += 12; }
              o.push('<text x="' + (n.x + n.w / 2) + '" y="' + y + '" font-size="14" font-weight="700" text-anchor="middle" fill="' + col + '">' + esc(n.label) + "</text>");
              var line = y + 10;
              o.push('<line x1="' + n.x + '" y1="' + line + '" x2="' + (n.x + n.w) + '" y2="' + line + '" stroke="' + paint(n, false).stroke + '" stroke-width="1.2"/>');
              if (n.shape === "entity") {
                DM.columns(n).forEach(function (cc, i) {
                  var ty = line + 15 + i * lh;
                  o.push('<text x="' + (n.x + 10) + '" y="' + ty + '" font-size="12" fill="' + col + '" opacity="0.75">' + esc(cc.type) + "</text>");
                  o.push('<text x="' + (n.x + 10 + n.w * 0.32) + '" y="' + ty + '" font-size="12.5" fill="' + col + '">' + esc(cc.name) + "</text>");
                  if (cc.keys) o.push('<text x="' + (n.x + n.w - 10) + '" y="' + ty + '" font-size="11" font-weight="700" text-anchor="end" fill="' + col + '">' + esc(cc.keys) + "</text>");
                });
              } else {
                var attrs = DM.lines(n.attrs), meths = DM.lines(n.methods), ty2 = line + 15;
                attrs.forEach(function (l, i) { o.push('<text x="' + (n.x + 10) + '" y="' + (ty2 + i * lh) + '" font-size="12.5" fill="' + col + '">' + esc(l) + "</text>"); });
                var line2 = line + Math.max(1, attrs.length) * lh + 4;
                o.push('<line x1="' + n.x + '" y1="' + line2 + '" x2="' + (n.x + n.w) + '" y2="' + line2 + '" stroke="' + paint(n, false).stroke + '" stroke-width="1.2"/>');
                meths.forEach(function (l, i) { o.push('<text x="' + (n.x + 10) + '" y="' + (line2 + 15 + i * lh) + '" font-size="12.5" fill="' + col + '">' + esc(l) + "</text>"); });
              }
              return o.join("");
            }
            var bx = DM.textBox(n), rows = DM.wrap(n.label, bx.w, fs, 500), lh2 = fs * 1.3;
            if (n.shape === "container") return '<text x="' + (n.x + 12) + '" y="' + (n.y + 20) + '" font-size="13" font-weight="700" fill="' + col + '">' + esc(n.label) + "</text>";
            if (n.shape === "actor") return '<text x="' + (n.x + n.w / 2) + '" y="' + (n.y + n.h + 16) + '" font-size="' + fs + '" text-anchor="middle" fill="' + col + '">' + esc(n.label) + "</text>";
            var top = n.shape === "note" ? n.y + bx.y + fs : n.y + bx.y + (bx.h - rows.length * lh2) / 2 + fs * 0.95, anchor = n.shape === "note" ? "start" : "middle", tx = n.shape === "note" ? n.x + bx.x + 2 : n.x + bx.x + bx.w / 2;
            return rows.map(function (l, i) { return '<text x="' + tx + '" y="' + (top + i * lh2) + '" font-size="' + fs + '" font-weight="' + (n.bold ? 700 : 500) + '" text-anchor="' + anchor + '" fill="' + col + '">' + esc(l) + "</text>"; }).join("");
          }
          M.nodes.filter(function (n) { return n.shape === "container"; }).forEach(function (n) { out.push('<g transform="translate(' + n.x + "," + n.y + ')">' + shapeSVG(n, paint(n, false)) + "</g>" + words(n)); });
          var pairs = {};
          M.edges.forEach(function (e) { var key = [e.from, e.to].sort().join(">"); pairs[key] = (pairs[key] || 0) + 1; e._k = pairs[key]; });
          M.edges.forEach(function (e) {
            var a = self.byId(e.from), bb = self.byId(e.to); if (!a || !bb) return;
            var key = [e.from, e.to].sort().join(">"), many = pairs[key], bend = many > 1 ? (e._k - (many + 1) / 2) * 34 * (e.from < e.to ? 1 : -1) : 0;
            var g = route(e, a, bb, bend), col = e.color || "#4b5852";
            out.push('<path d="' + g.d + '" fill="none" stroke="' + col + '" stroke-width="' + lineWidth(e) + '"' + dash(e) + ' stroke-linejoin="round"/>');
            out.push(mark(self.endMark(e, "end"), g.b, g.fromB, col, "#ffffff") + mark(self.endMark(e, "start"), g.a, g.fromA, col, "#ffffff"));
            var lab = function (txt, x, y) { return '<text x="' + x + '" y="' + y + '" font-size="12" text-anchor="middle" fill="#33413b" stroke="#ffffff" stroke-width="4" paint-order="stroke" stroke-linejoin="round">' + esc(txt) + "</text>"; };
            if (e.label) out.push(lab(e.label, g.mid.x, g.mid.y + 4));
            if (e.fromLabel) { var q1 = endLabel(g.a, g.fromA, 1); out.push(lab(e.fromLabel, q1.x, q1.y)); }
            if (e.toLabel) { var q2 = endLabel(g.b, g.fromB, -1); out.push(lab(e.toLabel, q2.x, q2.y)); }
          });
          M.nodes.filter(function (n) { return n.shape !== "container"; }).forEach(function (n) { out.push('<g transform="translate(' + n.x + "," + n.y + ')">' + shapeSVG(n, paint(n, false)) + "</g>" + words(n)); });
          var svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ' + w + " " + h + '" width="' + w + '" height="' + h + '" font-family="' + esc(FONT) + '">' +
            '<rect width="100%" height="100%" fill="#ffffff"/><g transform="translate(' + ox + "," + oy + ')">' + out.join("") + "</g></svg>";
          return { svg: svg, w: w, h: h };
        },
      };
    });
  });
})();
