/* Learning roadmaps (Productivity), as roadmap.sh shows them — and as freely arranged as a whiteboard:
   - every box sits anywhere: drag it (or several: Shift-click, Shift-drag a frame), drag its right edge to
     make it wider, drag from one of its dots to another box to join them — or into empty space for a new
     topic joined to it; double-click empty space to add a box, double-click a box to rename it;
   - Tab adds a topic under the chosen box (as in mind-map apps), D / L / S / U set it Done, Learning,
     Skipped, To learn; the round check on a box ticks it off;
   - drag empty space, the wheel or the arrow keys move around; Ctrl+wheel or a pinch zooms; 1 fits it all;
   - Ctrl+Z / Ctrl+Shift+Z undo and redo everything, Delete removes, Ctrl+D copies, right-click for the rest;
   - a box's panel: its description, links to learn from, and its tasks (add one, put it on Today).
   The whole canvas is saved a moment after each change (Work.api, kept on the device when offline).
   Also here: the list page's import (paste or choose JSON, checked as you go) and the AI prompt. */
(function () {
  "use strict";
  var d = document;
  function json(id) { try { return JSON.parse(d.getElementById(id).textContent); } catch (e) { return {}; } }
  var TEXT = json("path-text");
  var GRID = 8, MIN_K = 0.15, MAX_K = 2.5;
  function t(key, vars) {
    var s = TEXT[key] || key;
    if (vars) Object.keys(vars).forEach(function (k) { s = s.split("%(" + k + ")s").join(vars[k]); });
    return s;
  }
  function toast(msg, tone, act) { if (window.Work && Work.toast) Work.toast(msg, tone, act); }
  function typing(e) { var el = e.target; return !!(el && el.closest && el.closest("input, textarea, select, [contenteditable=true]")); }
  function keep(key, value) {
    try { if (value === undefined) return JSON.parse(localStorage.getItem(key)); localStorage.setItem(key, JSON.stringify(value)); } catch (e) { return null; }
  }
  function csrf() {
    var el = d.querySelector("[name=csrfmiddlewaretoken]"); if (el) return el.value;
    var m = d.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/); return m ? decodeURIComponent(m[1]) : "";
  }
  function uid() { return "n" + Date.now().toString(36).slice(-4) + Math.random().toString(36).slice(2, 6); }
  function snap(v) { return Math.round(v / GRID) * GRID; }
  function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }
  function r1(v) { return Math.round(v * 10) / 10; }
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  var URL_RE = /^https?:\/\/\S+$/i;

  document.addEventListener("alpine:init", function () {

    /* ── The list page: import (paste or a file, checked as you type) and the prompt for an AI ── */
    /* Both roadmap list pages (Roadmaps and Learning roadmaps): the import box takes either kind and the
       AI prompt can be for either; `kind` is the one this page starts with. */
    Alpine.data("pathsList", function (prompts, importUrl, kind, copiedText) {
      if (typeof prompts === "string") prompts = { learning: prompts };
      return {
        importOpen: false, tab: "paste", text: "", fileName: "", file: null, info: null, error: "", checking: false, busy: false,
        topic: "", level: "", time: "", aiOpen: false, newOpen: false, aiKind: kind || "learning", q: "",
        init: function () {
          var self = this;
          if (location.hash === "#import") this.openImport();
          if (location.hash === "#ai") { this.openImport(); this.aiOpen = true; }
          this.$watch("text", function () { self.later(); });
        },
        match: function (text) { var q = this.q.trim().toLowerCase(); return !q || text.toLowerCase().indexOf(q) >= 0; },
        anyMatch: function () {
          var self = this;
          return Array.prototype.some.call(this.$root.querySelectorAll(".lpl-tpl[data-find]"), function (el) { return self.match(el.dataset.find); });
        },
        openImport: function () { this.importOpen = true; var self = this; this.$nextTick(function () { self.$refs.paste && self.$refs.paste.focus(); }); },
        form: function (check) {
          var f = new FormData();
          f.append("csrfmiddlewaretoken", csrf());
          if (this.tab === "file" && this.file) f.append("file", this.file); else f.append("text", this.text);
          if (check) f.append("check", "1");
          return f;
        },
        later: function () { var self = this; clearTimeout(this._t); this._t = setTimeout(function () { self.check(); }, 400); },
        pick: function (e) { var f = e.target.files && e.target.files[0]; this.file = f || null; this.fileName = f ? f.name : ""; this.check(); },
        drop: function (e) { var f = e.dataTransfer.files && e.dataTransfer.files[0]; if (!f) return; this.tab = "file"; this.file = f; this.fileName = f.name; this.check(); },
        ready: function () { return this.tab === "file" ? !!this.file : !!this.text.trim(); },
        check: function () {
          var self = this;
          this.info = null; this.error = "";
          if (!this.ready()) return;
          this.checking = true;
          fetch(importUrl, { method: "POST", body: this.form(true), credentials: "same-origin", headers: { "X-Requested-With": "fetch" } })
            .then(function (r) { return r.json(); })
            .then(function (res) { self.checking = false; if (res.ok) self.info = res.info; else self.error = res.error; })
            .catch(function () { self.checking = false; });
        },
        create: function () {
          var self = this;
          if (!this.ready() || this.busy) return;
          this.busy = true;
          fetch(importUrl, { method: "POST", body: this.form(false), credentials: "same-origin", headers: { "X-Requested-With": "fetch" } })
            .then(function (r) { return r.json(); })
            .then(function (res) { self.busy = false; if (res.ok) location.href = res.url; else self.error = res.error; })
            .catch(function () { self.busy = false; });
        },
        get aiPrompt() {
          var prompt = prompts[this.aiKind] || prompts.learning;
          return prompt.split("{topic}").join(this.topic.trim() || "…").split("{level}").join(this.level.trim() || "…")
            .split("{time}").join(this.time.trim() || "…").split("{{").join("{").split("}}").join("}");
        },
        copy: function (text) {
          var done = function () { toast(copiedText || t("copied")); };
          if (navigator.clipboard) navigator.clipboard.writeText(text).then(done); else { var a = d.createElement("textarea"); a.value = text; d.body.appendChild(a); a.select(); d.execCommand("copy"); a.remove(); done(); }
        },
      };
    });

    /* ── One roadmap: the canvas ─────────────────────────────────────────────────────── */
    Alpine.data("pathPage", function (init) {
      var SIZES = init.sizes, KEY = "lp:" + init.path.id + ":";
      var ui = keep(KEY + "ui") || {};
      return {
        path: init.path, nodes: init.nodes, edges: init.edges, urls: init.urls, texts: TEXT,
        view: { x: 0, y: 0, k: 1 }, sel: {}, selEdge: null, panel: null, editing: null, editText: "",
        menu: null, box: null, link: null, locked: !!ui.locked, q: "", hitAt: -1, state: "saved", hist: [], fut: [],
        tip: !keep("lp:tipSeen"), space: false, pts: {}, pinch: null,
        detail: { tasks: [] }, loading: false, taskText: "", findOpen: false, search: "", found: [],
        resTitle: "", resUrl: "", resType: "docs", descEdit: false, aiOpen: false, timer: null, inflight: null,

        init: function () {
          var self = this, params = new URLSearchParams(location.search);
          this.$nextTick(function () {
            var v = keep(KEY + "view");
            if (v && v.k) self.view = v; else self.fit(true);
            if (params.get("node") && self.node(params.get("node"))) { self.centerOn(params.get("node")); self.select(params.get("node")); self.open(params.get("node")); }
            else if (params.get("continue")) self.next();
          });
          window.addEventListener("keydown", function (e) { self.key(e); });
          window.addEventListener("keyup", function (e) { if (e.key === " ") self.space = false; });
          window.addEventListener("beforeunload", function (e) { if (self.timer) { self.flush(); e.preventDefault(); } });
          this.$watch("locked", function () { keep(KEY + "ui", { locked: self.locked }); });
        },

        /* ── Boxes ─────────────────────────────────────────────────── */
        node: function (key) { for (var i = 0; i < this.nodes.length; i++) if (this.nodes[i].key === key) return this.nodes[i]; return null; },
        get byKey() { var m = {}; this.nodes.forEach(function (n) { m[n.key] = n; }); return m; },
        isSub: function (n, map) { var p = (map || this.byKey)[n.parent]; return n.kind === "topic" && !!p && p.kind === "topic"; },
        size: function (n, map) {
          var s = SIZES[this.isSub(n, map) ? "sub" : n.kind] || SIZES.topic;
          return [n.w || s[0], s[1]];
        },
        boxStyle: function (n) { var s = this.size(n); return "left:" + n.x + "px;top:" + n.y + "px;width:" + s[0] + "px;height:" + s[1] + "px"; },
        boxClass: function (n) {
          var q = this.q.trim().toLowerCase(), hit = q && (n.title + " " + n.description).toLowerCase().indexOf(q) >= 0;
          return { "is-sel": !!this.sel[n.key], "is-sub": this.isSub(n), "is-optional": n.optional, "is-hit": !!hit, "is-dim": !!q && !hit,
                   "is-open": this.panel === n.key, "is-editing": this.editing === n.key };
        },
        get selKeys() { var s = this.sel; return this.nodes.filter(function (n) { return s[n.key]; }).map(function (n) { return n.key; }); },
        select: function (key, add) { var s = add ? Object.assign({}, this.sel) : {}; s[key] = true; this.sel = s; this.selEdge = null; },

        /* ── Lines ─────────────────────────────────────────────────── */
        curve: function (a, b, map) {
          var sa = this.size(a, map), sb = this.size(b, map);
          var ax = a.x + sa[0] / 2, ay = a.y + sa[1] / 2, bx = b.x + sb[0] / 2, by = b.y + sb[1] / 2;
          var apart = b.x > a.x + sa[0] + 8 || b.x + sb[0] < a.x - 8, below = b.y > a.y + sa[1] + 4 || b.y + sb[1] < a.y - 4;
          if (apart && (!below || Math.abs(bx - ax) > Math.abs(by - ay))) {         // side by side: from side to side
            var right = bx > ax, x1 = right ? a.x + sa[0] : a.x, x2 = right ? b.x : b.x + sb[0], c = Math.max(Math.abs(x2 - x1) / 2, 24) * (right ? 1 : -1);
            return "M" + r1(x1) + " " + r1(ay) + " C" + r1(x1 + c) + " " + r1(ay) + " " + r1(x2 - c) + " " + r1(by) + " " + r1(x2) + " " + r1(by);
          }
          var down = by >= ay, y1 = down ? a.y + sa[1] : a.y, y2 = down ? b.y : b.y + sb[1], c2 = Math.max(Math.abs(y2 - y1) / 2, 18) * (down ? 1 : -1);
          return "M" + r1(ax) + " " + r1(y1) + " C" + r1(ax) + " " + r1(y1 + c2) + " " + r1(bx) + " " + r1(y2 - c2) + " " + r1(bx) + " " + r1(y2);
        },
        get edgesSvg() {          // (Alpine can't loop inside an <svg>, so the paths are written out)
          var map = this.byKey, self = this, out = "";
          this.edges.forEach(function (e, i) {
            var a = map[e.from], b = map[e.to];
            if (!a || !b) return;
            var p = self.curve(a, b, map), done = a.status === "done" && b.status === "done";
            out += '<path class="lp-edge' + (e.style === "dashed" ? " is-dashed" : "") + (done ? " is-done" : "") + (self.selEdge === i ? " is-sel" : "") + '" d="' + p + '"/>' +
                   '<path class="lp-edge-hit" data-edge="' + i + '" d="' + p + '"><title>' + esc(a.title + " → " + b.title) + "</title></path>";
          });
          if (this.link) out += '<path class="lp-edge is-temp" d="' + this.link + '"/>';
          return out;
        },
        addEdge: function (from, to) {
          if (from === to || this.edges.some(function (e) { return (e.from === from && e.to === to) || (e.from === to && e.to === from); })) return;
          var a = this.node(from), b = this.node(to);
          if (!a || !b) return;
          this.remember();
          var spine = function (n) { return !n.parent && (n.kind === "step" || n.kind === "checkpoint"); };
          this.edges.push({ from: from, to: to, style: spine(a) && spine(b) ? "solid" : "dashed" });
          if (!b.parent && b.kind === "topic" && a.kind !== "note") b.parent = from;      // joined from a box: it hangs under it
          this.changed();
        },
        edgeStyle: function (i, style) { if (!this.edges[i]) return; this.remember(); this.edges[i].style = style; this.edges = this.edges.slice(); this.changed(); },
        dropEdge: function (i) {
          var e = this.edges[i]; if (!e) return;
          this.remember();
          var b = this.node(e.to); if (b && b.parent === e.from) b.parent = "";
          this.edges.splice(i, 1); this.selEdge = null; this.changed();
        },

        /* ── Where things are on screen ────────────────────────────── */
        get worldStyle() { return "transform:translate(" + this.view.x + "px," + this.view.y + "px) scale(" + this.view.k + ")"; },
        get gridStyle() {
          var s = 24 * this.view.k;
          return "background-size:" + s + "px " + s + "px;background-position:" + this.view.x + "px " + this.view.y + "px";
        },
        rect: function () { return this.$refs.canvas.getBoundingClientRect(); },
        toWorld: function (cx, cy) { var r = this.rect(); return { x: (cx - r.left - this.view.x) / this.view.k, y: (cy - r.top - this.view.y) / this.view.k }; },
        setView: function (v) { this.view = v; var self = this; clearTimeout(this._vt); this._vt = setTimeout(function () { keep(KEY + "view", self.view); }, 300); },
        zoomAt: function (cx, cy, f) {
          var r = this.rect(), k = clamp(this.view.k * f, MIN_K, MAX_K), px = cx - r.left, py = cy - r.top;
          var wx = (px - this.view.x) / this.view.k, wy = (py - this.view.y) / this.view.k;
          this.setView({ k: k, x: px - wx * k, y: py - wy * k });
        },
        zoomBy: function (f) { var r = this.rect(); this.zoomAt(r.left + r.width / 2, r.top + r.height / 2, f); },
        get zoomPct() { return Math.round(this.view.k * 100) + "%"; },
        bounds: function (keys) {
          var self = this, map = this.byKey, list = keys ? keys.map(function (k) { return map[k]; }).filter(Boolean) : this.nodes;
          if (!list.length) return null;
          var b = { x1: Infinity, y1: Infinity, x2: -Infinity, y2: -Infinity };
          list.forEach(function (n) { var s = self.size(n, map); b.x1 = Math.min(b.x1, n.x); b.y1 = Math.min(b.y1, n.y); b.x2 = Math.max(b.x2, n.x + s[0]); b.y2 = Math.max(b.y2, n.y + s[1]); });
          return b;
        },
        fit: function (quiet, keys) {
          var r = this.rect(), b = this.bounds(keys);
          if (!b) { this.setView({ x: r.width / 2, y: 80, k: 1 }); return; }
          var pad = 48, k;
          if (quiet) {           // opening it: readable, its width on screen, from the top (scroll down for the rest), as roadmap.sh does
            k = clamp((r.width - pad * 2) / (b.x2 - b.x1), 0.55, 1);
            if ((b.y2 - b.y1) * k <= r.height - pad * 2) k = clamp(Math.min(k, (r.height - pad * 2) / (b.y2 - b.y1)), 0.55, 1);
          } else k = clamp(Math.min((r.width - pad * 2) / (b.x2 - b.x1), (r.height - pad * 2) / (b.y2 - b.y1), 1.1), MIN_K, MAX_K);
          var tall = (b.y2 - b.y1) * k > r.height - pad * 2;
          this.setView({ k: k, x: r.width / 2 - (b.x1 + b.x2) / 2 * k, y: tall ? pad + 24 - b.y1 * k : r.height / 2 - (b.y1 + b.y2) / 2 * k });
        },
        centerOn: function (key) {
          var n = this.node(key); if (!n) return;
          var r = this.rect(), s = this.size(n), k = Math.max(this.view.k, 0.7);
          var panelW = this.panel || key ? Math.min(420, r.width * 0.45) : 0;
          this.setView({ k: k, x: (r.width - panelW) / 2 - (n.x + s[0] / 2) * k, y: r.height / 2 - (n.y + s[1] / 2) * k });
        },

        /* ── Pointer: drag boxes, pan, frame-select, join, resize ──── */
        down: function (e) {
          if (this.editing && !e.target.closest(".lp-edit")) this.commitEdit();
          if (e.button === 2) return;
          this.menu = null;
          var tg = e.target;
          if (tg.closest(".lp-check, .lp-edit, .lp-float, .lp-menu")) return;
          this.pts[e.pointerId] = { x: e.clientX, y: e.clientY };
          if (Object.keys(this.pts).length === 2) { this.startPinch(); return; }
          var edge = tg.closest("[data-edge]");
          if (edge) { this.selEdge = +edge.getAttribute("data-edge"); this.sel = {}; e.preventDefault(); return; }
          this.selEdge = null;
          var port = tg.closest(".lp-port"), rz = tg.closest(".lp-resize"), el = tg.closest(".lp-node");
          if (e.button === 1 || this.space) return this.drag(e, "pan");
          if (port && el) return this.drag(e, "link", el.getAttribute("data-key"));
          if (rz && el && !this.locked) return this.drag(e, "resize", el.getAttribute("data-key"));
          if (el) return this.drag(e, "node", el.getAttribute("data-key"));
          return this.drag(e, e.shiftKey ? "box" : "pan");
        },
        trackPointer: function (e) {
          if (!this.pts[e.pointerId]) return;
          this.pts[e.pointerId] = { x: e.clientX, y: e.clientY };
          if (this.pinch) this.pinchMove();
        },
        lift: function (e) { delete this.pts[e.pointerId]; if (Object.keys(this.pts).length < 2) this.pinch = null; },
        startPinch: function () {
          var p = Object.values(this.pts);
          this.pinch = { d: Math.hypot(p[0].x - p[1].x, p[0].y - p[1].y) || 1, cx: (p[0].x + p[1].x) / 2, cy: (p[0].y + p[1].y) / 2, view: Object.assign({}, this.view) };
        },
        pinchMove: function () {
          var p = Object.values(this.pts); if (p.length < 2) return;
          var pc = this.pinch, dist = Math.hypot(p[0].x - p[1].x, p[0].y - p[1].y), cx = (p[0].x + p[1].x) / 2, cy = (p[0].y + p[1].y) / 2;
          var r = this.rect(), k = clamp(pc.view.k * dist / pc.d, MIN_K, MAX_K);
          var wx = (pc.cx - r.left - pc.view.x) / pc.view.k, wy = (pc.cy - r.top - pc.view.y) / pc.view.k;
          this.setView({ k: k, x: cx - r.left - wx * k, y: cy - r.top - wy * k });
        },
        drag: function (e, mode, key) {
          var self = this, x0 = e.clientX, y0 = e.clientY, moved = false, v0 = Object.assign({}, this.view), starts = [], w0 = 0, was = key ? !!this.sel[key] : false;
          e.preventDefault();
          if (mode === "node") {
            if (e.shiftKey) { if (!was) this.select(key, true); }
            else if (!was) this.select(key);
          }
          function begin() {
            if (mode === "node" && !self.locked) {
              self.remember();
              starts = self.selKeys.map(function (k) { var n = self.node(k); return { n: n, x: n.x, y: n.y }; });
            }
            if (mode === "resize") { self.remember(); w0 = self.size(self.node(key))[0]; }
          }
          function move(ev) {
            if (ev.pointerId !== e.pointerId || self.pinch) return;
            var dx = ev.clientX - x0, dy = ev.clientY - y0, k = self.view.k;
            if (!moved) { if (Math.abs(dx) + Math.abs(dy) < 4) return; moved = true; begin(); }
            if (mode === "pan") self.setView({ x: v0.x + dx, y: v0.y + dy, k: v0.k });
            else if (mode === "node" && !self.locked) {
              starts.forEach(function (s) { var nx = s.x + dx / k, ny = s.y + dy / k; s.n.x = ev.altKey ? r1(nx) : snap(nx); s.n.y = ev.altKey ? r1(ny) : snap(ny); });
            } else if (mode === "resize") { self.node(key).w = clamp(snap(w0 + dx / k), 96, 640); }
            else if (mode === "box") {
              var a = self.toWorld(x0, y0), b = self.toWorld(ev.clientX, ev.clientY);
              self.box = { x: Math.min(a.x, b.x), y: Math.min(a.y, b.y), w: Math.abs(a.x - b.x), h: Math.abs(a.y - b.y) };
            } else if (mode === "link") {
              var n = self.node(key), p = self.toWorld(ev.clientX, ev.clientY);
              self.link = self.curve(n, { x: p.x - 1, y: p.y - 1, kind: "note", w: 2 });
            }
          }
          function up(ev) {
            if (ev.pointerId !== e.pointerId) return;
            d.removeEventListener("pointermove", move); d.removeEventListener("pointerup", up); d.removeEventListener("pointercancel", up);
            if (mode === "pan" && !moved && !self.pinch) { self.sel = {}; self.selEdge = null; if (self.panel) self.close(); }
            if (mode === "node") {
              if (!moved) {
                if (e.shiftKey) { if (was) { var s = Object.assign({}, self.sel); delete s[key]; self.sel = s; } }
                else { self.select(key); self.open(key); }
              } else if (!self.locked) self.changed();
            }
            if (mode === "resize" && moved) self.changed();
            if (mode === "box") {
              var bx = self.box, picked = e.shiftKey ? Object.assign({}, self.sel) : {};
              if (bx) self.nodes.forEach(function (n) { var sz = self.size(n); if (n.x < bx.x + bx.w && n.x + sz[0] > bx.x && n.y < bx.y + bx.h && n.y + sz[1] > bx.y) picked[n.key] = true; });
              self.sel = picked; self.box = null;
            }
            if (mode === "link") {
              self.link = null;
              if (!moved) return;
              var over = d.elementFromPoint(ev.clientX, ev.clientY), to = over && over.closest(".lp-node");
              if (to && to.getAttribute("data-key") !== key) self.addEdge(key, to.getAttribute("data-key"));
              else if (!to && over && over.closest(".lp-canvas")) { var p = self.toWorld(ev.clientX, ev.clientY); self.addChild(key, p); }
            }
          }
          d.addEventListener("pointermove", move); d.addEventListener("pointerup", up); d.addEventListener("pointercancel", up);
        },
        wheel: function (e) {
          if (e.ctrlKey || e.metaKey) this.zoomAt(e.clientX, e.clientY, Math.exp(-e.deltaY * (e.deltaMode ? 0.05 : 0.0018)));
          else this.setView({ x: this.view.x - (e.shiftKey ? e.deltaY : e.deltaX), y: this.view.y - (e.shiftKey ? 0 : e.deltaY), k: this.view.k });
        },
        dbl: function (e) {
          if (e.target.closest(".lp-float, .lp-menu, .lp-check")) return;
          var el = e.target.closest(".lp-node");
          if (el) { this.startEdit(el.getAttribute("data-key")); return; }
          if (e.target.closest("[data-edge]")) return;
          var p = this.toWorld(e.clientX, e.clientY);
          this.addNode("topic", { x: p.x - SIZES.topic[0] / 2, y: p.y - SIZES.topic[1] / 2 });
        },
        context: function (e) {
          var el = e.target.closest(".lp-node"), edge = e.target.closest("[data-edge]"), r = this.rect(), p = this.toWorld(e.clientX, e.clientY);
          var key = el ? el.getAttribute("data-key") : null;
          if (key && !this.sel[key]) this.select(key);
          if (edge) this.selEdge = +edge.getAttribute("data-edge");
          this.menu = { x: Math.min(e.clientX - r.left, r.width - 230), y: Math.min(e.clientY - r.top, r.height - 330), key: key,
                        edge: edge ? +edge.getAttribute("data-edge") : null, wx: p.x, wy: p.y };
        },

        /* ── Undo, redo, saving ───────────────────────────────────── */
        snapshot: function () {
          return JSON.stringify({ nodes: this.nodes.map(function (n) { var c = Object.assign({}, n); delete c.tasks; return c; }), edges: this.edges });
        },
        remember: function () { this.hist.push(this.snapshot()); if (this.hist.length > 100) this.hist.shift(); this.fut = []; },
        restore: function (s) {
          var o = JSON.parse(s), tasks = {};
          this.nodes.forEach(function (n) { tasks[n.key] = n.tasks; });
          o.nodes.forEach(function (n) { n.tasks = tasks[n.key] || { open: 0, done: 0 }; });
          this.nodes = o.nodes; this.edges = o.edges;
          var self = this, s2 = {}; Object.keys(this.sel).forEach(function (k) { if (self.node(k)) s2[k] = true; }); this.sel = s2;
          if (this.panel && !this.node(this.panel)) this.close();
          this.changed();
        },
        undo: function () { if (!this.hist.length) { toast(t("nothing"), "warn"); return; } this.fut.push(this.snapshot()); this.restore(this.hist.pop()); },
        redo: function () { if (!this.fut.length) return; this.hist.push(this.snapshot()); this.restore(this.fut.pop()); },
        undoToast: function (msg) { var self = this; toast(msg, "good", { label: t("undo"), run: function () { self.undo(); } }); },
        changed: function () { var self = this; this.state = "saving"; clearTimeout(this.timer); this.timer = setTimeout(function () { self.flush(); }, 600); },
        graph: function () {
          return { nodes: this.nodes.map(function (n) { return { key: n.key, kind: n.kind, title: n.title, description: n.description, x: n.x, y: n.y, w: n.w,
                                                                  status: n.status, optional: n.optional, color: n.color, resources: n.resources, parent: n.parent }; }),
                   edges: this.edges };
        },
        /* One save at a time: a change made while one is on its way is sent right after it (the canvas as it is then). */
        flush: function () {
          var self = this;
          clearTimeout(this.timer); this.timer = null;
          if (this.inflight) { this.again = true; return this.inflight; }
          this.again = false; this.state = "saving";
          this.inflight = Work.api(this.urls.api, { action: "save", graph: JSON.stringify(this.graph()), _ft_same: "lp" + this.path.id }).then(function (res) {
            self.inflight = null;
            if (self.again) return self.flush();
            if (self.timer) return res;
            var fine = res && (res.ok || res.queued);
            self.state = fine ? "saved" : "error";
            if (fine) self.retries = 0;
            else if (res && res.error) toast(res.error, "warn");
            else if ((self.retries = (self.retries || 0) + 1) <= 3) self.timer = setTimeout(function () { self.flush(); }, 1500 * self.retries);   // the server stumbled: try again
            return res;
          });
          return this.inflight;
        },
        saved: function () {            // everything on its way and saved (before asking the server about a box)
          var self = this;
          if (this.timer) return this.flush().then(function () { return self.saved(); });
          if (this.inflight) return this.inflight.then(function () { return self.saved(); });
          return Promise.resolve({ ok: true });
        },
        stateText: function () { return this.state === "saving" ? t("saving") : this.state === "error" ? t("notSaved") : t("saved"); },
        api: function (data) {
          var self = this;
          return this.saved().then(function () { return Work.api(self.urls.api, data); }).then(function (res) {
            res = res || {};
            if (!res.ok && !res.queued && res.error) toast(res.error, "warn");
            return res;
          });
        },

        /* ── Making and changing boxes ─────────────────────────────── */
        blank: function (kind, at, parent) {
          var title = kind === "step" ? t("newStep") : kind === "checkpoint" ? t("newCheckpoint") : kind === "note" ? t("newNote") : t("untitled");
          return { key: uid(), kind: kind, title: title, description: "", x: snap(at.x), y: snap(at.y), w: null, status: "todo", optional: false,
                   color: "", resources: [], parent: parent || "", tasks: { open: 0, done: 0 } };
        },
        viewCenter: function () { var r = this.rect(); return this.toWorld(r.left + r.width / 2, r.top + r.height / 2); },
        addNode: function (kind, at, quiet) {
          var one = this.selKeys.length === 1 ? this.node(this.selKeys[0]) : null;
          if (!at && one && kind === "topic") return this.addChild(one.key);
          if (!at && one && (kind === "step" || kind === "checkpoint") && !one.parent && (one.kind === "step" || one.kind === "checkpoint")) {
            return this.addStepAfter(one, kind);
          }
          var c = at || this.viewCenter(), s = SIZES[kind] || SIZES.topic;
          var n = this.blank(kind, at ? c : { x: c.x - s[0] / 2, y: c.y - s[1] / 2 });
          this.remember(); this.nodes.push(n); this.select(n.key); this.changed();
          if (!quiet) this.startEdit(n.key);
          return n;
        },
        addStepAfter: function (step, kind) {
          var sz = this.size(step), below = this.nodes.filter(function (n) { return !n.parent && n.y > step.y && (n.kind === "step" || n.kind === "checkpoint"); })
            .sort(function (a, b) { return a.y - b.y; })[0];
          var n = this.blank(kind || "step", { x: step.x, y: step.y + sz[1] + 64 });
          this.remember();
          if (below && below.y < n.y + 120) {          // make room: everything below moves down
            var gap = 48 + 64, self = this;
            this.nodes.forEach(function (x) { if (x.y >= below.y - 4) x.y = snap(x.y + gap); });
            this.edges = this.edges.filter(function (e) { return !(e.from === step.key && e.to === below.key); });
            this.edges.push({ from: n.key, to: below.key, style: "solid" });
            void self;
          }
          this.nodes.push(n);
          this.edges.push({ from: step.key, to: n.key, style: "solid" });
          this.select(n.key); this.changed(); this.startEdit(n.key);
          return n;
        },
        addChild: function (key, at) {
          var p = this.node(key); if (!p) return null;
          var ps = this.size(p), kids = this.nodes.filter(function (n) { return n.parent === key; }), kind = p.kind === "note" ? "note" : "topic";
          var cs = SIZES[p.kind === "topic" ? "sub" : kind], pos;
          if (at) pos = { x: at.x - cs[0] / 2, y: at.y - cs[1] / 2 };
          else {
            var side = kids.length ? (kids[kids.length - 1].x < p.x ? -1 : 1) : (p.x + ps[0] / 2 >= -8 ? 1 : -1);
            var last = kids.slice().sort(function (a, b) { return b.y - a.y; })[0];
            pos = { x: side > 0 ? p.x + ps[0] + (p.parent ? 40 : 70) : p.x - (p.parent ? 40 : 70) - cs[0], y: last ? last.y + cs[1] + 12 : p.y + (ps[1] - cs[1]) / 2 };
          }
          var n = this.blank(kind, pos, kind === "note" ? "" : key);
          this.remember();
          this.nodes.push(n);
          this.edges.push({ from: key, to: n.key, style: "dashed" });
          this.select(n.key); this.changed(); this.startEdit(n.key);
          return n;
        },
        deleteSel: function () {
          if (this.selEdge !== null && !this.selKeys.length) { this.dropEdge(this.selEdge); return; }
          var keys = this.selKeys; if (!keys.length) return;
          var gone = {}; keys.forEach(function (k) { gone[k] = true; });
          this.remember();
          this.nodes = this.nodes.filter(function (n) { return !gone[n.key]; });
          this.nodes.forEach(function (n) { if (gone[n.parent]) n.parent = ""; });
          this.edges = this.edges.filter(function (e) { return !gone[e.from] && !gone[e.to]; });
          if (this.panel && gone[this.panel]) this.close();
          this.sel = {}; this.changed();
          this.undoToast(keys.length === 1 ? t("deleted1") : t("deleted", { n: keys.length }));
        },
        duplicateSel: function () {
          var keys = this.selKeys; if (!keys.length) return;
          var self = this, map = {}, made = [];
          this.remember();
          keys.forEach(function (k) {
            var n = self.node(k), c = JSON.parse(JSON.stringify(n));
            c.key = uid(); c.x = snap(n.x + 32); c.y = snap(n.y + 32); c.status = "todo"; c.tasks = { open: 0, done: 0 };
            map[k] = c.key; made.push(c);
          });
          made.forEach(function (c) { c.parent = map[c.parent] || c.parent; });
          var extra = this.edges.filter(function (e) { return map[e.from] && map[e.to]; }).map(function (e) { return { from: map[e.from], to: map[e.to], style: e.style }; });
          this.nodes = this.nodes.concat(made); this.edges = this.edges.concat(extra);
          var s = {}; made.forEach(function (c) { s[c.key] = true; }); this.sel = s;
          this.changed();
        },
        setField: function (n, field, value) {
          if (!n || n[field] === value) return;
          this.remember(); n[field] = value; this.changed();
        },
        /* status: the round check, D / L / S / U, the panel, the right-click menu */
        setStatus: function (keys, status) {
          var self = this, list = keys.map(function (k) { return self.node(k); }).filter(Boolean);
          if (!list.length) return;
          if (list.every(function (n) { return n.status === status; }) && status !== "todo") status = "todo";      // the same key again: back
          this.remember();
          list.forEach(function (n) { if (n.kind !== "note") n.status = status; });
          this.changed();
          var one = list.length === 1 ? list[0] : null;
          if (one && status === "done" && one.tasks.open) {
            toast(t("openLeft", { n: one.tasks.open }), "warn", { label: t("finishThem"), run: function () { self.closeTasks(one); } });
          }
          if (status === "done" && this.progress.left === 0 && this.progress.total) toast(t("allFinished"));
        },
        check: function (n) { this.setStatus([n.key], n.status === "done" ? "todo" : "done"); },

        /* ── Renaming right on the box ─────────────────────────────── */
        startEdit: function (key) {
          var n = this.node(key); if (!n) return;
          this.editing = key; this.editText = n.title;
          this.reveal(key);
          this.$nextTick(function () { var el = d.querySelector(".lp-node.is-editing .lp-edit"); if (el) { el.focus(); el.select(); } });
        },
        reveal: function (key) {         // off screen (a new topic far to the side): move just enough to show it
          var n = this.node(key); if (!n) return;
          var r = this.rect(), s = this.size(n), k = this.view.k, m = 40, right = this.panel ? Math.min(448, r.width * 0.45) : 0;
          var x1 = n.x * k + this.view.x, y1 = n.y * k + this.view.y, x2 = x1 + s[0] * k, y2 = y1 + s[1] * k, dx = 0, dy = 0;
          if (x2 > r.width - right - m) dx = r.width - right - m - x2; if (x1 + dx < m) dx = m - x1;
          if (y2 > r.height - m) dy = r.height - m - y2; if (y1 + dy < m + 40) dy = m + 40 - y1;
          if (dx || dy) this.setView({ x: this.view.x + dx, y: this.view.y + dy, k: k });
        },
        commitEdit: function () {
          var key = this.editing; if (!key) return;
          this.editing = null;
          var n = this.node(key), text = this.editText.replace(/\s+/g, " ").trim().slice(0, 200);
          if (n && text && text !== n.title) { this.remember(); n.title = text; this.changed(); }
        },
        cancelEdit: function () { this.editing = null; },
        editKey: function (e) {
          if (e.key === "Enter") { e.preventDefault(); this.commitEdit(); }
          else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); this.cancelEdit(); }
          else if (e.key === "Tab") { e.preventDefault(); var k = this.editing; this.commitEdit(); if (e.shiftKey) { var n = this.node(k); if (n && n.parent) this.addChild(n.parent); } else this.addChild(k); }
        },

        /* ── Tidy up, lock ─────────────────────────────────────────── */
        tidy: function () {
          var self = this;
          this.api({ action: "tidy" }).then(function (res) {
            if (!res.ok || !res.places) return;
            self.remember();
            self.nodes.forEach(function (n) { var p = res.places[n.key]; if (p) { n.x = p[0]; n.y = p[1]; } });
            self.changed(); self.fit();
            self.undoToast(t("tidied"));
          });
        },
        toggleLock: function () { this.locked = !this.locked; toast(this.locked ? t("locked") : t("unlocked")); },

        /* ── How far along, what's next, finding ──────────────────── */
        get progress() {
          var c = { total: 0, done: 0, learning: 0, skipped: 0 };
          this.nodes.forEach(function (n) { if (n.kind === "note") return; c.total++; if (n.status === "done") c.done++; else if (n.status === "learning") c.learning++; else if (n.status === "skipped") c.skipped++; });
          c.left = c.total - c.done - c.skipped;
          c.pct = c.total - c.skipped ? Math.round(100 * c.done / (c.total - c.skipped)) : (c.total ? 100 : 0);
          return c;
        },
        get reading() {
          var map = this.byKey, kids = {}, out = [], seen = {};
          this.nodes.forEach(function (n) { if (map[n.parent] && n.parent !== n.key) (kids[n.parent] = kids[n.parent] || []).push(n); });
          var by = function (a, b) { return a.y - b.y || a.x - b.x; };
          function visit(n) { if (seen[n.key]) return; seen[n.key] = 1; out.push(n); (kids[n.key] || []).slice().sort(by).forEach(visit); }
          this.nodes.filter(function (n) { return !map[n.parent]; }).sort(by).forEach(visit);
          this.nodes.forEach(visit);
          return out;
        },
        get upNext() {
          var parents = {}; this.nodes.forEach(function (n) { if (n.parent) parents[n.parent] = 1; });
          var open = this.reading.filter(function (n) { return n.kind !== "note" && n.status !== "done" && n.status !== "skipped"; });
          return open.find(function (n) { return n.status === "learning"; })            // what you said you're learning, first
            || open.find(function (n) { return !(n.kind === "step" && parents[n.key]); }) || null;
        },
        next: function () {
          var n = this.upNext;
          if (!n) { toast(t("allFinished")); return; }
          this.select(n.key); this.open(n.key); this.centerOn(n.key);
        },
        get hits() { var q = this.q.trim().toLowerCase(); if (!q) return []; return this.reading.filter(function (n) { return (n.title + " " + n.description).toLowerCase().indexOf(q) >= 0; }); },
        hitText: function () { var n = this.hits.length; return this.q.trim() ? (n ? t("hits", { n: n }) : t("noHits")) : ""; },
        nextHit: function (back) {
          var h = this.hits; if (!h.length) return;
          this.hitAt = (this.hitAt + (back ? -1 : 1) + h.length) % h.length;
          this.select(h[this.hitAt].key); this.centerOn(h[this.hitAt].key);
        },

        /* ── The panel: one box ────────────────────────────────────── */
        get current() { return this.panel ? this.node(this.panel) : null; },
        open: function (key) {
          if (!this.node(key)) return;
          var self = this;
          this.panel = key; this.detail = { tasks: [] }; this.taskText = ""; this.findOpen = false; this.found = []; this.descEdit = false;
          this.resTitle = ""; this.resUrl = "";
          var u = new URL(location.href); u.searchParams.set("node", key); u.searchParams.delete("continue"); history.replaceState(null, "", u);
          if (this.node(key).kind === "note") return;
          this.loading = true;
          this.saved().then(function () {
            return fetch(self.urls.api + "?node=" + encodeURIComponent(key), { credentials: "same-origin", headers: { "X-Requested-With": "fetch" } });
          }).then(function (r) { return r && r.ok ? r.json() : null; })
            .then(function (res) { if (res && self.panel === key) self.detail = res; self.loading = false; })
            .catch(function () { self.loading = false; });
        },
        close: function () {
          this.panel = null;
          var u = new URL(location.href); u.searchParams.delete("node"); history.replaceState(null, "", u);
        },
        md: function (text) { return window.Work && Work.markdown ? Work.markdown(text || "") : esc(text || ""); },
        addResource: function (n) {
          var url = this.resUrl.trim();
          if (!URL_RE.test(url)) { toast(t("badUrl"), "warn"); return; }
          this.remember();
          n.resources = n.resources.concat([{ title: this.resTitle.trim() || url, url: url, type: this.resType }]);
          this.resTitle = ""; this.resUrl = ""; this.changed();
        },
        dropResource: function (n, i) { this.remember(); var r = n.resources.slice(); r.splice(i, 1); n.resources = r; this.changed(); },
        host: function (url) { try { return new URL(url).hostname.replace(/^www\./, ""); } catch (e) { return ""; } },
        /* its tasks */
        addTask: function (today) {
          var self = this, n = this.current; if (!n) return;
          var title = this.taskText.trim() || t("learn", { topic: n.title });
          this.api({ action: "task_add", node: n.key, title: title, today: today ? "1" : "" }).then(function (res) {
            if (!res.ok) return;
            self.detail.tasks.unshift(res.task); n.tasks.open++; self.taskText = "";
            if (res.status && res.status !== n.status) n.status = res.status;
            toast(today ? t("onToday") : t("taskAdded"));
          });
        },
        tickTask: function (tk) {
          var self = this, n = this.current, done = !tk.done; if (!n) return;
          tk.done = done;
          this.api({ action: "task_done", node: n.key, task: tk.id, done: done ? "1" : "" }).then(function (res) {
            if (!res.ok) { tk.done = !done; return; }
            n.tasks.open += done ? -1 : 1; n.tasks.done += done ? 1 : -1;
            if (done && !n.tasks.open && n.status !== "done") {
              toast(t("allDone"), "good", { label: t("markDone"), run: function () { self.setStatus([n.key], "done"); } });
            }
          });
        },
        unlinkTask: function (tk) {
          var self = this, n = this.current; if (!n) return;
          this.api({ action: "task_unlink", node: n.key, task: tk.id }).then(function (res) {
            if (!res.ok) return;
            self.detail.tasks = self.detail.tasks.filter(function (x) { return x.id !== tk.id; });
            if (tk.done) n.tasks.done--; else n.tasks.open--;
            toast(t("unlinked"));
          });
        },
        findTasks: function () {
          var self = this, n = this.current, q = this.search; if (!n) return;
          Work.ask(this.urls.api, { action: "task_search", node: n.key, q: q }).then(function (res) { if (res && res.ok && q === self.search) self.found = res.tasks; });
        },
        linkTask: function (tk) {
          var self = this, n = this.current; if (!n) return;
          this.api({ action: "task_link", node: n.key, task: tk.id }).then(function (res) {
            if (!res.ok) return;
            self.detail.tasks.unshift(res.task); n.tasks.open++;
            self.found = self.found.filter(function (x) { return x.id !== tk.id; }); toast(t("linked"));
          });
        },
        closeTasks: function (n) {
          var self = this;
          this.api({ action: "tasks_close", node: n.key }).then(function (res) {
            if (!res.ok) return;
            n.tasks = { open: 0, done: n.tasks.done + n.tasks.open };
            if (self.panel === n.key) self.detail.tasks.forEach(function (x) { x.done = true; });
          });
        },
        plan: function (count, today) {
          var self = this;
          this.api({ action: "plan", n: count, today: today ? "1" : "" }).then(function (res) {
            if (!res.ok) return;
            Object.keys(res.nodes || {}).forEach(function (k) { var n = self.node(k); if (n) n.tasks.open++; });
            toast(res.count ? t("planned", { n: res.count }) : t("plannedNone"), res.count ? "good" : "warn");
          });
        },

        /* ── The roadmap itself ────────────────────────────────────── */
        rename: function (fields) {
          Object.assign(this.path, fields);
          if (fields.title) d.title = fields.title + " | " + d.title.split(" | ").slice(1).join(" | ");
          this.api(Object.assign({ action: "rename" }, fields));
        },
        roadmap: function (action) {
          var self = this;
          if ((action === "delete" || action === "reset") && !this.sure) {
            FT.ask({ message: t(action === "delete" ? "deleteRoadmap" : "resetAsk"), danger: action === "delete", after: action === "delete" ? "back" : "gone" })
              .then(function (yes) { if (yes) { self.sure = true; self.roadmap(action); self.sure = false; } });
            return;
          }
          if (action === "reset") {
            this.remember(); this.nodes.forEach(function (n) { n.status = "todo"; }); this.changed(); this.undoToast(t("reset")); return;
          }
          this.api({ action: action }).then(function (res) {
            if (!res.ok) return;
            if (action === "archive") { self.path.archived = res.archived; toast(res.archived ? t("archived") : t("unarchived")); }
            else if (res.url) location.href = res.url;
          });
        },
        dismissTip: function () { this.tip = false; keep("lp:tipSeen", true); },

        /* ── Keys ──────────────────────────────────────────────────── */
        key: function (e) {
          if (e.key === " " && !typing(e)) { this.space = true; if (e.target === d.body || e.target.closest(".lp-canvas")) e.preventDefault(); }
          if (typing(e) || e.defaultPrevented) return;
          var mod = e.ctrlKey || e.metaKey, k = e.key, keys = this.selKeys, one = keys.length === 1 ? keys[0] : null;
          if (mod && (k === "z" || k === "Z")) { e.preventDefault(); if (e.shiftKey) this.redo(); else this.undo(); return; }
          if (mod && (k === "y" || k === "Y")) { e.preventDefault(); this.redo(); return; }
          if (mod && k === "a") { e.preventDefault(); var all = {}; this.nodes.forEach(function (n) { all[n.key] = true; }); this.sel = all; return; }
          if (mod && k === "d") { e.preventDefault(); this.duplicateSel(); return; }
          if (mod && k === "f") { e.preventDefault(); this.$refs.find && this.$refs.find.focus(); return; }
          if (mod || e.altKey) return;
          if (this.aiOpen) { if (k === "Escape") this.aiOpen = false; return; }
          if (k === "Escape") {
            if (this.menu) this.menu = null; else if (this.panel) this.close(); else { this.sel = {}; this.selEdge = null; }
            e.preventDefault(); return;
          }
          if (k === "Delete" || k === "Backspace") { if (keys.length || this.selEdge !== null) { e.preventDefault(); this.deleteSel(); } return; }
          var move = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[k];
          if (move) {
            e.preventDefault();
            if (keys.length && !this.locked) {
              var step = e.shiftKey ? GRID * 5 : GRID, self = this;
              this.remember(); keys.forEach(function (key) { var n = self.node(key); n.x += move[0] * step; n.y += move[1] * step; }); this.changed();
            } else this.setView({ x: this.view.x - move[0] * 80, y: this.view.y - move[1] * 80, k: this.view.k });
            return;
          }
          var map = { d: "done", l: "learning", s: "skipped", u: "todo" };
          if (map[k] && keys.length) { e.preventDefault(); this.setStatus(keys, map[k]); return; }
          if (k === "Enter" && one) { e.preventDefault(); this.open(one); return; }
          if (k === "F2" && one) { e.preventDefault(); this.startEdit(one); return; }
          if (k === "Tab" && one) { e.preventDefault(); if (e.shiftKey) { var n = this.node(one); if (n.parent) this.addChild(n.parent); } else this.addChild(one); return; }
          if (k === "n") { e.preventDefault(); this.addNode("topic"); return; }
          if (k === "c") { e.preventDefault(); this.next(); return; }
          if (k === "1") { e.preventDefault(); this.fit(); return; }
          if (k === "2" && keys.length) { e.preventDefault(); this.fit(false, keys); return; }
          if (k === "+" || k === "=") { e.preventDefault(); this.zoomBy(1.2); return; }
          if (k === "-") { e.preventDefault(); this.zoomBy(1 / 1.2); return; }
          if (k === "/") { e.preventDefault(); this.$refs.find && this.$refs.find.focus(); }
        },
      };
    });
  });
})();
