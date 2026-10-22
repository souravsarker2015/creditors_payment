/* Diagrams (Productivity): mind maps, system design boards and text
   (Mermaid) diagrams. Loaded on a diagram's page after work.js.

   Each editor keeps its drawing in a plain object (not Alpine-reactive, so a
   big map stays quick), draws it into the page itself, and hands the page
   component (diagramPage) what to save: the shapes or the text, plus an SVG
   picture for the list. The same picture is what "Export" downloads. */
(function () {
  "use strict";
  var d = document, root = d.documentElement;
  var REDUCED = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
  var TEXT = (function () { try { return JSON.parse(d.getElementById("diagram-text").textContent); } catch (e) { return {}; } })();
  var FONT = "system-ui, -apple-system, 'Segoe UI', Roboto, 'Noto Sans Bengali', sans-serif";
  var COLORS = ["#e8590c", "#1c7ed6", "#2f9e44", "#ae3ec9", "#f08c00", "#0c8599", "#e03131", "#5f3dc4", "#495057"];

  function uid(p) { return (p || "n") + Date.now().toString(36) + Math.random().toString(36).slice(2, 6); }
  function esc(s) { return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"); }
  function clone(o) { return JSON.parse(JSON.stringify(o)); }
  function toast(msg, tone, act) { if (window.Work && Work.toast) Work.toast(msg, tone, act); }
  function isDark() { return root.getAttribute("data-theme") === "dark"; }
  function slug(t) { return (t || "diagram").toLowerCase().replace(/[^\wঀ-৿]+/g, "-").replace(/^-|-$/g, "").slice(0, 60) || "diagram"; }

  function download(name, blob) {
    var a = d.createElement("a"); a.href = URL.createObjectURL(blob); a.download = name;
    d.body.appendChild(a); a.click(); setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 500);
  }
  /* An SVG drawing as a PNG picture, twice the size for sharp screens. */
  function svgToPng(svg, w, h) {
    return new Promise(function (resolve, reject) {
      var scale = Math.min(2, 8000 / Math.max(w, h, 1)), img = new Image();
      var url = URL.createObjectURL(new Blob([svg], { type: "image/svg+xml;charset=utf-8" }));
      img.onload = function () {
        var c = d.createElement("canvas"); c.width = Math.ceil(w * scale); c.height = Math.ceil(h * scale);
        var g = c.getContext("2d"); g.fillStyle = "#ffffff"; g.fillRect(0, 0, c.width, c.height);
        g.drawImage(img, 0, 0, c.width, c.height); URL.revokeObjectURL(url);
        c.toBlob(function (b) { b ? resolve(b) : reject(new Error("png")); }, "image/png");
      };
      img.onerror = function () { URL.revokeObjectURL(url); reject(new Error("svg")); };
      img.src = url;
    });
  }
  function svgSize(svg) {
    var m = /viewBox="\s*[-\d.]+[\s,]+[-\d.]+[\s,]+([\d.]+)[\s,]+([\d.]+)/.exec(svg) || [];
    return { w: parseFloat(m[1]) || 800, h: parseFloat(m[2]) || 600 };
  }
  /* Words broken into at most `max` lines about `width` wide (`perChar`: a rough letter width), "…" when cut. */
  function wrapText(text, width, perChar, max) {
    var fit = Math.max(4, Math.floor(width / perChar)), words = String(text || "").split(/\s+/), lines = [], line = "";
    words.forEach(function (w) {
      while (w.length > fit) { if (line) { lines.push(line); line = ""; } lines.push(w.slice(0, fit)); w = w.slice(fit); }
      if ((line + " " + w).trim().length > fit) { lines.push(line); line = w; } else line = (line + " " + w).trim();
    });
    if (line) lines.push(line);
    lines = lines.filter(function (l) { return l; });
    if (lines.length > max) { lines = lines.slice(0, max); lines[max - 1] = lines[max - 1].replace(/.?$/, "…"); }
    return lines;
  }
  /* Lines of text drawn in SVG, centred on (x, y0 + first line). */
  function svgLines(lines, x, y, size, lh, attrs) {
    return lines.map(function (l, i) { return '<text x="' + x + '" y="' + (y + i * lh) + '" font-size="' + size + '" ' + attrs + ">" + esc(l) + "</text>"; }).join("");
  }

  /* ── Pan and zoom: a "world" moved and scaled inside a canvas ─────────── */
  function Viewport(canvas, world, onChange) {
    this.c = canvas; this.w = world; this.x = 0; this.y = 0; this.k = 1; this.min = 0.15; this.max = 3;
    this.onChange = onChange || function () {}; this.ptrs = {}; this.pan = null; this.pinch = null;
    var self = this;
    canvas.addEventListener("wheel", function (e) {
      e.preventDefault();
      if (e.ctrlKey || e.metaKey) self.zoomAt(e.clientX, e.clientY, Math.exp(-e.deltaY * (e.deltaMode ? 0.05 : 0.0025)));
      else { self.x -= e.deltaX; self.y -= e.deltaY; self.apply(); }
    }, { passive: false });
    this.apply();
  }
  Viewport.prototype.apply = function () {
    this.w.style.transform = "translate(" + this.x + "px," + this.y + "px) scale(" + this.k + ")";
    // the dotted paper moves and scales with the drawing
    this.c.style.setProperty("--gx", this.x + "px"); this.c.style.setProperty("--gy", this.y + "px"); this.c.style.setProperty("--gk", this.k);
    this.onChange(this.k);
  };
  Viewport.prototype.zoomAt = function (cx, cy, f) {
    var r = this.c.getBoundingClientRect(), k = Math.max(this.min, Math.min(this.max, this.k * f));
    var px = cx - r.left, py = cy - r.top;
    this.x = px - (px - this.x) * (k / this.k); this.y = py - (py - this.y) * (k / this.k); this.k = k; this.apply();
  };
  Viewport.prototype.zoomBy = function (f) { var r = this.c.getBoundingClientRect(); this.zoomAt(r.left + r.width / 2, r.top + r.height / 2, f); };
  Viewport.prototype.toWorld = function (cx, cy) {
    var r = this.c.getBoundingClientRect(); return { x: (cx - r.left - this.x) / this.k, y: (cy - r.top - this.y) / this.k };
  };
  Viewport.prototype.fit = function (b, pad, maxK, minK) {
    var r = this.c.getBoundingClientRect(); pad = pad == null ? 40 : pad;
    if (!b || !isFinite(b.x1) || r.width < 10) return;
    var w = Math.max(b.x2 - b.x1, 1), h = Math.max(b.y2 - b.y1, 1);
    var k = Math.max(minK || 0, Math.min((r.width - pad * 2) / w, (r.height - pad * 2) / h, maxK || 1.25));
    this.k = Math.max(this.min, Math.min(this.max, k));
    this.x = (r.width - w * this.k) / 2 - b.x1 * this.k; this.y = (r.height - h * this.k) / 2 - b.y1 * this.k; this.apply();
  };
  /* Keep a world box on screen (after adding an idea near the edge). */
  Viewport.prototype.reveal = function (b, pad) {
    var r = this.c.getBoundingClientRect(); pad = pad || 30;
    var x1 = b.x1 * this.k + this.x, x2 = b.x2 * this.k + this.x, y1 = b.y1 * this.k + this.y, y2 = b.y2 * this.k + this.y;
    var dx = x1 < pad ? pad - x1 : x2 > r.width - pad ? r.width - pad - x2 : 0;
    var dy = y1 < pad ? pad - y1 : y2 > r.height - pad ? r.height - pad - y2 : 0;
    if (dx || dy) { this.x += dx; this.y += dy; this.apply(); }
  };
  /* Pointer gestures on the background: one finger or the mouse pans, two fingers pinch-zoom. */
  Viewport.prototype.down = function (e) {
    this.ptrs[e.pointerId] = { x: e.clientX, y: e.clientY };
    var ids = Object.keys(this.ptrs);
    if (ids.length === 1) this.pan = { x: e.clientX, y: e.clientY, ox: this.x, oy: this.y, moved: false };
    else if (ids.length === 2) {
      var a = this.ptrs[ids[0]], b = this.ptrs[ids[1]];
      this.pan = null; this.pinch = { dist: Math.hypot(a.x - b.x, a.y - b.y), k: this.k, cx: (a.x + b.x) / 2, cy: (a.y + b.y) / 2, ox: this.x, oy: this.y };
    }
    try { this.c.setPointerCapture(e.pointerId); } catch (err) { /* already gone */ }
  };
  Viewport.prototype.move = function (e) {
    if (!this.ptrs[e.pointerId]) return false;
    this.ptrs[e.pointerId] = { x: e.clientX, y: e.clientY };
    var ids = Object.keys(this.ptrs);
    if (this.pinch && ids.length >= 2) {
      var a = this.ptrs[ids[0]], b = this.ptrs[ids[1]], p = this.pinch, r = this.c.getBoundingClientRect();
      var k = Math.max(this.min, Math.min(this.max, p.k * Math.hypot(a.x - b.x, a.y - b.y) / (p.dist || 1)));
      var cx = (a.x + b.x) / 2, cy = (a.y + b.y) / 2, px = p.cx - r.left, py = p.cy - r.top;
      this.x = px - (px - p.ox) * (k / p.k) + (cx - p.cx); this.y = py - (py - p.oy) * (k / p.k) + (cy - p.cy); this.k = k; this.apply();
      return true;
    }
    if (this.pan) {
      var dx = e.clientX - this.pan.x, dy = e.clientY - this.pan.y;
      if (Math.abs(dx) + Math.abs(dy) > 3) this.pan.moved = true;
      this.x = this.pan.ox + dx; this.y = this.pan.oy + dy; this.apply();
      return true;
    }
    return false;
  };
  Viewport.prototype.up = function (e) {
    var moved = this.pan && this.pan.moved;
    delete this.ptrs[e.pointerId];
    if (Object.keys(this.ptrs).length < 2) this.pinch = null;
    if (!Object.keys(this.ptrs).length) this.pan = null;
    return moved;
  };

  /* What the editors share: the text and the drawing as they are now (a
     flowchart can be switched between dragging shapes and writing text). */
  var LIVE = (function () {
    try { var p = JSON.parse(d.getElementById("diagram-data").textContent); return { source: p.source || "", data: p.data || {} }; }
    catch (e) { return { source: "", data: {} }; }
  })();
  window.WorkDiagrams = { Viewport: Viewport, esc: esc, clone: clone, toast: toast, TEXT: TEXT, live: LIVE };

  /* ════════════════════════════════════════════════════════════════════════
     The page: title, project, notes, saving, export and the actions menu.
     ════════════════════════════════════════════════════════════════════════ */
  document.addEventListener("alpine:init", function () {
    Alpine.data("diagramPage", function (initial) {
      return {
        id: initial.id, title: initial.title, kind: initial.kind, notes: initial.notes || "", project: initial.project || "",
        state: "saved", savedAt: initial.saved, full: false, pinned: !!initial.pinned, editor: null, texts: TEXT,
        pending: {}, timer: null, inflight: null, again: false,
        histOpen: false, histLoading: false, versions: [], versionName: "", mode: initial.mode || "",
        init: function () {
          var self = this;
          window.addEventListener("beforeunload", function () { if (self.state === "dirty") self.saveNow(); });
          this.$watch("full", function () { setTimeout(function () { if (self.editor && self.editor.resized) self.editor.resized(); }, 30); });
          this.$el.addEventListener("keydown", function (e) { if ((e.ctrlKey || e.metaKey) && e.key === "s") { e.preventDefault(); self.saveNow(); } });
          // a diagram made from a template has no picture for the list yet: draw one once it's on screen
          if (!initial.hasPreview) setTimeout(function () { if (self.editor && self.editor.preview) { self.pending._picture = true; self.saveNow(); } }, 1500);
        },
        /* Drag and drop, or text (flowcharts, state, class and database diagrams) */
        setMode: function (to) {
          if (this.mode === to) return;
          var self = this;
          Promise.resolve(this.saveNow()).then(function () {
            self.mode = to; LIVE.data.mode = to;
            self.queue({ data: JSON.stringify(LIVE.data) });
          });
        },
        stateText: function () {
          return { saving: TEXT.saving, saved: this.savedAt ? TEXT.saved + " " + this.savedAt : "", offline: TEXT.offline, dirty: TEXT.editing, error: TEXT.error }[this.state];
        },
        /* Ask for a save: `fields` are merged and sent together a moment later. */
        queue: function (fields) {
          Object.assign(this.pending, fields || {}); this.state = "dirty";
          clearTimeout(this.timer); var self = this; this.timer = setTimeout(function () { self.saveNow(); }, 900);
        },
        saveNow: function () {
          var self = this;
          clearTimeout(this.timer);
          if (this.inflight) { this.again = true; return this.inflight; }
          var fields = this.pending; this.pending = {};
          var withPicture = ("data" in fields) || ("source" in fields) || fields._picture;
          delete fields._picture;
          if (!Object.keys(fields).length && !withPicture) { if (this.state === "dirty") this.state = "saved"; return Promise.resolve(); }
          this.state = "saving";
          var picture = withPicture && this.editor && this.editor.preview ? Promise.resolve(this.editor.preview()).catch(function () { return null; }) : Promise.resolve(null);
          this.inflight = picture.then(function (svg) {
            if (svg != null) fields.preview = svg;
            return Work.api("/work/api/diagrams/" + self.id + "/save/", fields);
          }).then(function (res) {
            self.inflight = null;
            if (!res || !res.ok) { self.state = "error"; if (res && res.error) toast(res.error, "warn"); return; }
            self.state = res.queued ? "offline" : "saved";
            if (res.saved) self.savedAt = res.saved;
            if (self.again || Object.keys(self.pending).length) { self.again = false; return self.saveNow(); }
          });
          return this.inflight;
        },
        /* Export */
        drawing: function () {
          var out = this.editor && this.editor.svg ? this.editor.svg() : null;
          return Promise.resolve(out).then(function (o) { if (!o || !o.svg) { toast(TEXT.nothing, "warn"); return null; } return o; });
        },
        exportSVG: function () {
          var self = this;
          this.drawing().then(function (o) { if (o) { download(slug(self.title) + ".svg", new Blob([o.svg], { type: "image/svg+xml" })); toast(TEXT.exported); } });
        },
        exportPNG: function () {
          var self = this;
          this.drawing().then(function (o) {
            if (!o) return;
            return svgToPng(o.svg, o.w, o.h).then(function (b) { download(slug(self.title) + ".png", b); toast(TEXT.exported); });
          }).catch(function () { toast(TEXT.error, "warn"); });
        },
        exportDrawio: function () {
          var xml = this.editor && this.editor.drawio ? this.editor.drawio() : "";
          if (!xml) { toast(TEXT.nothing, "warn"); return; }
          download(slug(this.title) + ".drawio", new Blob([xml], { type: "application/xml" })); toast(TEXT.exported);
        },
        copyText: function () {
          var text = this.editor && this.editor.text ? this.editor.text() : "";
          if (navigator.clipboard && text) navigator.clipboard.writeText(text).then(function () { toast(TEXT.copied, "good"); });
        },
        action: function (name, extra) {
          var self = this;
          if (name === "delete" && !confirm(TEXT.deleteConfirm || "Delete?")) return;
          return Promise.resolve(this.saveNow()).then(function () {
            return Work.api("/work/api/diagrams/" + self.id + "/", Object.assign({ action: name }, extra || {}));
          }).then(function (res) {
            if (!res || !res.ok) { if (res && res.error) toast(res.error, "warn"); return res; }
            if (name === "pin") { self.pinned = res.pinned; toast(res.pinned ? TEXT.pinned : TEXT.unpinned); }
            else if (name === "delete") { Work.undoable(TEXT.deleted, res.undo, function () { location.href = "/work/diagrams/" + self.id + "/"; }); setTimeout(function () { location.href = "/work/diagrams/"; }, 400); }
            else if (name === "archive") location.href = res.url;
            else if (res.url && name !== "tasks" && name !== "cards") location.href = res.url;
            return res;
          });
        },
        /* A mind map as flashcards, in a deck named after it */
        makeCards: function () {
          this.action("cards").then(function (res) {
            if (res && res.ok) toast(TEXT.cardsMade + ": " + res.count, "good", { label: TEXT.seeCards, run: function () { location.href = res.url; } });
          });
        },
        /* Earlier versions */
        openHistory: function (naming) {
          var self = this;
          this.histOpen = true; this.histLoading = true;
          if (naming) this.$nextTick(function () { self.$refs.vname && self.$refs.vname.focus(); });
          fetch("/work/api/diagrams/" + this.id + "/versions/", { credentials: "same-origin", headers: { Accept: "application/json" } })
            .then(function (r) { return r.json(); })
            .then(function (res) { self.versions = (res && res.versions) || []; })
            .catch(function () { self.versions = []; })
            .then(function () { self.histLoading = false; });
        },
        saveVersion: function () {
          var self = this, name = this.versionName.trim();
          this.action("version", { name: name }).then(function (res) {
            if (!res || !res.ok || !res.version) return;
            self.versions = [res.version].concat(self.versions.filter(function (v) { return v.id !== res.version.id; }));
            self.versionName = ""; toast(TEXT.versionSaved, "good");
          });
        },
        restore: function (v) {
          if (!confirm(TEXT.restoreConfirm)) return;
          this.action("restore", { version: v.id });       // the page reloads with it
        },
        forget: function (v) {
          var self = this;
          this.action("forget", { version: v.id }).then(function (res) {
            if (res && res.ok) self.versions = self.versions.filter(function (x) { return x.id !== v.id; });
          });
        },
      };
    });

    /* ══════════════════════════════════════════════════════════════════════
       Mind map
       ══════════════════════════════════════════════════════════════════════ */
    var MM = { HGAP: [0, 56, 40, 32], VGAP: [0, 18, 8, 6], PAD: [[12, 22], [8, 14], [4, 4]], FONT: [18, 15, 14], WEIGHT: [700, 600, 500], LH: 1.35 };
    function mmLevel(depth) { return Math.min(depth, 2); }

    Alpine.data("mindMap", function () {
      var M = null, byId = {}, parentOf = {}, els = {}, pos = {}, undoStack = [], redoStack = [];
      return {
        selected: "r", editingId: null, canUndo: false, canRedo: false, zoom: 100, importOpen: false, importText: "",
        colors: COLORS, isRoot: true, hasKids: false, folded: false, selColor: COLORS[0], view: null,
        layout: "map", isDone: false, doneCount: 0, total: 0, findOpen: false, findText: "", hits: [], hitAt: 0,
        init: function () {
          var self = this;
          M = clone(JSON.parse(d.getElementById("diagram-data").textContent).data || {});
          if (!M.root) M.root = { id: "r", text: TEXT.newIdea, children: [] };
          this.layout = ["map", "right", "down"].indexOf(M.layout) >= 0 ? M.layout : "map";
          this.$refs.canvas.setAttribute("data-layout", this.layout);   // now, so the first measuring sees the right styles
          this.view = new Viewport(this.$refs.canvas, this.$refs.world, function (k) { self.zoom = Math.round(k * 100); });
          this.editor = {
            svg: function () { return self.toSVG(); }, preview: function () { var o = self.toSVG(); return o ? o.svg : ""; },
            text: function () { return self.outline(); }, resized: function () { self.fit(); },
          };
          this.pointers();
          this.render(false);
          this.$nextTick(function () { self.fit(); self.select("r"); });
          window.addEventListener("resize", function () { self.draw(); });
        },
        /* model helpers */
        index: function () {
          byId = {}; parentOf = {};
          (function walk(n, p) { byId[n.id] = n; parentOf[n.id] = p; (n.children || []).forEach(function (k) { walk(k, n); }); })(M.root, null);
        },
        depth: function (id) { var n = 0, p = parentOf[id]; while (p) { n++; p = parentOf[p.id]; } return n; },
        branchColor: function (id) {
          var n = byId[id];
          while (n) { if (n.color) return n.color; var p = parentOf[n.id]; if (p && p.id === M.root.id) return COLORS[(p.children.indexOf(n)) % COLORS.length]; n = p; }
          return COLORS[0];
        },
        snapshot: function () { undoStack.push(JSON.stringify(M.root)); if (undoStack.length > 120) undoStack.shift(); redoStack = []; this.canUndo = true; this.canRedo = false; },
        undo: function () { if (!undoStack.length) return; redoStack.push(JSON.stringify(M.root)); M.root = JSON.parse(undoStack.pop()); this.afterHistory(); },
        redo: function () { if (!redoStack.length) return; undoStack.push(JSON.stringify(M.root)); M.root = JSON.parse(redoStack.pop()); this.afterHistory(); },
        afterHistory: function () { this.canUndo = !!undoStack.length; this.canRedo = !!redoStack.length; this.render(true); if (!byId[this.selected]) this.selected = "r"; this.select(this.selected); this.save(); },
        save: function () { this.queue({ data: JSON.stringify(M) }); },

        /* drawing */
        render: function (animate) {
          this.index();
          var host = this.$refs.nodes, seen = {}, self = this;
          (function walk(n, depth, hidden) {
            if (hidden) return;
            seen[n.id] = true;
            var el = els[n.id];
            if (!el) {
              el = d.createElement("div"); el.className = "wmm-node"; el.setAttribute("data-id", n.id);
              el.innerHTML = '<span class="wmm-text"></span><span class="wmm-prog"></span><button type="button" class="wmm-fold" tabindex="-1"></button>';
              host.appendChild(el); els[n.id] = el;
              if (!REDUCED && animate) el.classList.add("is-new");
            }
            el.setAttribute("data-depth", mmLevel(depth));
            el.style.setProperty("--c", self.branchColor(n.id));
            var t = el.firstChild; if (self.editingId !== n.id && t.textContent !== n.text) t.textContent = n.text;
            var kids = n.children || [], ticked = kids.filter(function (k) { return k.done; }).length;
            el.classList.toggle("is-done", !!n.done);
            el.children[1].textContent = ticked ? ticked + "/" + kids.length : "";
            el.children[1].classList.toggle("is-all", ticked > 0 && ticked === kids.length);
            el.classList.toggle("has-kids", kids.length > 0);
            el.classList.toggle("is-folded", !!n.collapsed && kids.length > 0);
            el.lastChild.textContent = n.collapsed && kids.length ? "+" + self.countUnder(n) : "";
            kids.forEach(function (k) { walk(k, depth + 1, n.collapsed); });
          })(M.root, 0, false);
          Object.keys(els).forEach(function (id) { if (!seen[id]) { els[id].remove(); delete els[id]; delete pos[id]; } });
          var all = 0, done = 0;
          (function count(n) { all++; if (n.done) done++; (n.children || []).forEach(count); })(M.root);
          this.total = all; this.doneCount = done;
          if (this.findOpen && this.findText) this.markHits();
          this.place();
          this.draw(animate);
        },
        countUnder: function (n) { return (n.children || []).reduce(function (s, k) { return s + 1 + this.countUnder(k); }.bind(this), 0); },
        place: function () {
          var self = this, size = {};
          Object.keys(els).forEach(function (id) { size[id] = { w: els[id].offsetWidth, h: els[id].offsetHeight }; });
          var target = {};
          function bh(n, depth) {
            var s = size[n.id], kids = n.collapsed ? [] : (n.children || []);
            if (!kids.length) return (n._bh = s.h);
            var gap = MM.VGAP[Math.min(depth + 1, 3)], sum = 0;
            kids.forEach(function (k) { sum += bh(k, depth + 1); }); sum += gap * (kids.length - 1);
            return (n._bh = Math.max(s.h, sum));
          }
          function place(n, x, cy, dir, depth) {
            var s = size[n.id]; target[n.id] = { x: dir > 0 ? x : x - s.w, y: cy - s.h / 2, w: s.w, h: s.h, dir: dir, depth: depth };
            var kids = n.collapsed ? [] : (n.children || []); if (!kids.length) return;
            var gap = MM.VGAP[Math.min(depth + 1, 3)], total = kids.reduce(function (a, k) { return a + k._bh; }, 0) + gap * (kids.length - 1);
            var y = cy - total / 2, nx = dir > 0 ? x + s.w + MM.HGAP[Math.min(depth + 1, 3)] : x - s.w - MM.HGAP[Math.min(depth + 1, 3)];
            kids.forEach(function (k) { place(k, nx, y + k._bh / 2, dir, depth + 1); y += k._bh + gap; });
          }
          var r = M.root, rs = size[r.id];
          if (this.layout === "down") { this._target = this.placeDown(size); return; }
          target[r.id] = { x: -rs.w / 2, y: -rs.h / 2, w: rs.w, h: rs.h, dir: 0, depth: 0 };
          var kids = r.collapsed ? [] : (r.children || []);
          kids.forEach(function (k) { bh(k, 1); });
          var half = this.layout === "right" ? kids.length : Math.ceil(kids.length / 2), right = kids.slice(0, half), left = kids.slice(half);
          [[right, 1], [left, -1]].forEach(function (pair) {
            var list = pair[0], dir = pair[1], gap = MM.VGAP[1];
            var total = list.reduce(function (a, k) { return a + k._bh; }, 0) + gap * Math.max(0, list.length - 1), y = -total / 2;
            var x = dir > 0 ? rs.w / 2 + MM.HGAP[1] : -rs.w / 2 - MM.HGAP[1];
            list.forEach(function (k) { place(k, x, y + k._bh / 2, dir, 1); y += k._bh + gap; });
          });
          this._target = target;
        },
        /* Org chart: each level a row, every idea centred over the ideas under it. */
        placeDown: function (size) {
          var HG = [0, 28, 16, 12], VG = 52, target = {}, rowH = [];
          function vis(n) { return n.collapsed ? [] : (n.children || []); }
          (function rows(n, depth) { rowH[depth] = Math.max(rowH[depth] || 0, size[n.id].h); vis(n).forEach(function (k) { rows(k, depth + 1); }); })(M.root, 0);
          var rowY = [0]; for (var i = 1; i < rowH.length; i++) rowY[i] = rowY[i - 1] + rowH[i - 1] + VG;
          function bw(n, depth) {
            var kids = vis(n), s = size[n.id]; if (!kids.length) return (n._bw = s.w);
            var sum = kids.reduce(function (a, k) { return a + bw(k, depth + 1); }, 0) + HG[Math.min(depth + 1, 3)] * (kids.length - 1);
            return (n._bw = Math.max(s.w, sum));
          }
          function put(n, cx, depth) {
            var s = size[n.id];
            target[n.id] = { x: cx - s.w / 2, y: rowY[depth] + (rowH[depth] - s.h) / 2 - rowH[0] / 2, w: s.w, h: s.h, dir: 1, down: true, depth: depth };
            var kids = vis(n); if (!kids.length) return;
            var gap = HG[Math.min(depth + 1, 3)], total = kids.reduce(function (a, k) { return a + k._bw; }, 0) + gap * (kids.length - 1), x = cx - total / 2;
            kids.forEach(function (k) { put(k, x + k._bw / 2, depth + 1); x += k._bw + gap; });
          }
          bw(M.root, 0); put(M.root, 0, 0);
          return target;
        },
        draw: function (animate) {
          var self = this, target = this._target || {}, from = {};
          Object.keys(target).forEach(function (id) { from[id] = pos[id] || (function () { var p = parentOf[id] && pos[parentOf[id].id]; return p ? { x: p.x + p.w / 2 - target[id].w / 2, y: p.y + p.h / 2 - target[id].h / 2 } : target[id]; })(); });
          cancelAnimationFrame(this._raf);
          var start = performance.now(), dur = animate && !REDUCED ? 220 : 0;
          function frame(now) {
            var t = dur ? Math.min(1, (now - start) / dur) : 1, e = 1 - Math.pow(1 - t, 3);
            Object.keys(target).forEach(function (id) {
              var a = from[id], b = target[id];
              pos[id] = { x: a.x + (b.x - a.x) * e, y: a.y + (b.y - a.y) * e, w: b.w, h: b.h, dir: b.dir, depth: b.depth };
              els[id].style.transform = "translate(" + pos[id].x + "px," + pos[id].y + "px)";
            });
            self.links();
            if (t < 1) self._raf = requestAnimationFrame(frame);
          }
          if (dur) this._raf = requestAnimationFrame(frame); else frame(start);
        },
        anchor: function (id, side) {      // where a link meets an idea: underline ends for small ideas, middle for big ones
          var p = pos[id], deep = p.depth >= 2;
          var y = deep ? p.y + p.h : p.y + p.h / 2;
          return { x: side > 0 ? p.x + p.w : p.x, y: y };
        },
        linkPath: function (pid, cid) {
          var c = pos[cid], dir = c.dir || 1;
          if (c.down) {                       // org chart: from under the parent to the top of the child
            var pp = pos[pid], ax = pp.x + pp.w / 2, ay = pp.y + pp.h, bx = c.x + c.w / 2, by = c.y, my = (ay + by) / 2;
            return "M" + ax + "," + ay + " C" + ax + "," + my + " " + bx + "," + my + " " + bx + "," + by;
          }
          var a = this.anchor(pid, dir), b = this.anchor(cid, -dir);
          if (pid === M.root.id) { var rp = pos[pid]; a = { x: rp.x + rp.w / 2 + dir * (rp.w / 2 - 8), y: rp.y + rp.h / 2 }; }
          var mx = (a.x + b.x) / 2;
          return "M" + a.x + "," + a.y + " C" + mx + "," + a.y + " " + mx + "," + b.y + " " + b.x + "," + b.y;
        },
        links: function () {
          var out = [], self = this;
          Object.keys(pos).forEach(function (id) {
            var p = parentOf[id]; if (!p || !pos[p.id] || !els[id]) return;
            var depth = pos[id].depth, w = depth === 1 ? 3 : 2;
            out.push('<path d="' + self.linkPath(p.id, id) + '" stroke="' + self.branchColor(id) + '" stroke-width="' + w + '" fill="none" stroke-linecap="round"/>');
          });
          this.$refs.links.innerHTML = out.join("");
        },
        bounds: function () {
          var b = { x1: Infinity, y1: Infinity, x2: -Infinity, y2: -Infinity };
          Object.keys(this._target || {}).forEach(function (id) { var p = this._target[id]; b.x1 = Math.min(b.x1, p.x); b.y1 = Math.min(b.y1, p.y); b.x2 = Math.max(b.x2, p.x + p.w); b.y2 = Math.max(b.y2, p.y + p.h); }, this);
          return b;
        },
        // on a phone, never so small the words can't be read: the centre stays in view, pan for the rest
        fit: function () { this.view.fit(this.bounds(), 40, 1.1, this.$refs.canvas.clientWidth < 600 ? 0.6 : 0); },

        /* picking and editing */
        select: function (id) {
          if (!byId[id]) id = "r";
          if (els[this.selected]) els[this.selected].classList.remove("is-selected");
          this.selected = id; var n = byId[id];
          if (els[id]) { els[id].classList.add("is-selected"); var p = this._target && this._target[id]; if (p) this.view.reveal({ x1: p.x, y1: p.y, x2: p.x + p.w, y2: p.y + p.h }); }
          this.isRoot = id === M.root.id; this.hasKids = !!(n.children && n.children.length); this.folded = !!n.collapsed; this.selColor = this.branchColor(id);
          this.isDone = !!n.done;
        },
        toggleDone: function () {
          var n = byId[this.selected]; if (!n || n.id === M.root.id) return;
          this.snapshot(); n.done = !n.done; if (!n.done) delete n.done;
          this.render(false); this.select(n.id); this.save();
          if (n.done && els[n.id] && !REDUCED) { els[n.id].classList.remove("is-ticked"); void els[n.id].offsetWidth; els[n.id].classList.add("is-ticked"); }
        },
        /* Alt+arrows: move the idea before or after its neighbour */
        moveSibling: function (step) {
          var me = byId[this.selected], p = parentOf[this.selected]; if (!p) return;
          var i = p.children.indexOf(me), j = i + step; if (j < 0 || j >= p.children.length) return;
          this.snapshot(); p.children.splice(i, 1); p.children.splice(j, 0, me);
          this.render(true); this.select(me.id); this.save();
        },
        setLayout: function (mode) {
          if (mode === this.layout) return;
          this.layout = mode; M.layout = mode; this.$refs.canvas.setAttribute("data-layout", mode);
          this.render(true); this.select(this.selected); this.save();
          var self = this; setTimeout(function () { self.fit(); }, 240);
        },
        /* Unfold everything, or fold every main branch */
        foldAll: function (fold) {
          this.snapshot();
          (function walk(n, depth) {
            if (fold && depth === 1 && n.children && n.children.length) n.collapsed = true; else delete n.collapsed;
            (n.children || []).forEach(function (k) { walk(k, depth + 1); });
          })(M.root, 0);
          this.render(true); this.select(byId[this.selected] && els[this.selected] ? this.selected : "r"); this.save();
          var self = this; setTimeout(function () { self.fit(); }, 240);
        },
        /* Find: ideas that match light up, the rest fade; Enter goes to the next one */
        openFind: function () {
          this.findOpen = true; var self = this;
          this.$nextTick(function () { self.$refs.find.focus(); self.$refs.find.select(); });
        },
        closeFind: function () {
          this.findOpen = false; this.findText = ""; this.hits = [];
          Object.keys(els).forEach(function (id) { els[id].classList.remove("is-match", "is-hit"); });
          this.$refs.canvas.focus({ preventScroll: true });
        },
        find: function () {
          var q = this.findText.trim().toLowerCase(), out = [];
          if (q) (function walk(n) { if (String(n.text).toLowerCase().indexOf(q) >= 0) out.push(n.id); (n.children || []).forEach(walk); })(M.root);
          this.hits = out; this.hitAt = 0; this.markHits();
          if (out.length) this.goHit();
        },
        markHits: function () {
          var on = {}, hit = this.hits[this.hitAt]; this.hits.forEach(function (id) { on[id] = true; });
          Object.keys(els).forEach(function (id) { els[id].classList.toggle("is-match", !!on[id]); els[id].classList.toggle("is-hit", id === hit); });
        },
        findNext: function (step) {
          if (!this.hits.length) return;
          this.hitAt = (this.hitAt + step + this.hits.length) % this.hits.length; this.goHit();
        },
        goHit: function () {
          var id = this.hits[this.hitAt], p = parentOf[id], opened = false;
          while (p) { if (p.collapsed) { delete p.collapsed; opened = true; } p = parentOf[p.id]; }
          if (opened) { this.render(true); this.save(); }
          this.markHits(); this.select(id);
        },
        newNode: function (text) { return { id: uid(), text: text == null ? TEXT.newIdea : text, children: [] }; },
        addChild: function () {
          var p = byId[this.selected]; if (!p) return;
          this.snapshot(); var n = this.newNode(); p.children = p.children || []; p.children.push(n); p.collapsed = false;
          this.render(true); this.select(n.id); this.save(); this.edit(true);
        },
        addSibling: function () {
          var me = byId[this.selected], p = parentOf[this.selected]; if (!p) return this.addChild();
          this.snapshot(); var n = this.newNode(); p.children.splice(p.children.indexOf(me) + 1, 0, n);
          this.render(true); this.select(n.id); this.save(); this.edit(true);
        },
        remove: function () {
          var me = byId[this.selected], p = parentOf[this.selected]; if (!p) return;
          this.snapshot(); var i = p.children.indexOf(me); p.children.splice(i, 1);
          var next = p.children[i] || p.children[i - 1] || p;
          this.render(true); this.select(next.id); this.save(); this.$refs.canvas.focus();
        },
        fold: function () {
          var n = byId[this.selected]; if (!n || !(n.children || []).length) return;
          this.snapshot(); n.collapsed = !n.collapsed; this.render(true); this.select(n.id); this.save();
        },
        setColor: function (c) { var n = byId[this.selected]; if (!n) return; this.snapshot(); n.color = c || undefined; if (!c) delete n.color; this.render(false); this.select(n.id); this.save(); },
        /* Type straight into the idea. `fresh`: a just-added idea, so its words are picked to be typed over. */
        edit: function (fresh, firstChar) {
          var id = this.selected, el = els[id]; if (!el) return;
          var self = this, t = el.firstChild, before = byId[id].text;
          this.editingId = id; el.classList.add("is-editing");
          try { t.contentEditable = "plaintext-only"; } catch (e) { t.contentEditable = "true"; }
          if (t.contentEditable !== "plaintext-only") t.contentEditable = "true";
          if (firstChar != null) t.textContent = firstChar;
          t.focus();
          var range = d.createRange(); range.selectNodeContents(t); if (!fresh || firstChar != null) range.collapse(false);
          var s = window.getSelection(); s.removeAllRanges(); s.addRange(range);
          function finish(keep) {
            t.removeEventListener("keydown", onKey); t.removeEventListener("blur", onBlur); t.removeEventListener("input", onInput);
            t.contentEditable = "false"; el.classList.remove("is-editing"); self.editingId = null;
            var text = keep ? t.textContent.replace(/ /g, " ").trim() : before;
            if (!text) text = before || TEXT.newIdea;
            t.textContent = text;
            if (text !== before) {
              self.snapshot(); byId[id].text = text;
              if (id === M.root.id && (self.title === before || self.title === TEXT.kindLabel)) { self.title = text.split("\n")[0].slice(0, 200); self.queue({ title: self.title }); }
              self.save();
            }
            self.render(false); self.select(id);
          }
          function onKey(e) {
            e.stopPropagation();
            if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); finish(true); self.$refs.canvas.focus(); }
            else if (e.key === "Escape") { e.preventDefault(); finish(false); self.$refs.canvas.focus(); }
            else if (e.key === "Tab") { e.preventDefault(); finish(true); self.addChild(); }
          }
          function onBlur() { finish(true); }
          function onInput() { self.place(); self.draw(false); }
          t.addEventListener("keydown", onKey); t.addEventListener("blur", onBlur); t.addEventListener("input", onInput);
        },
        nav: function (dir) {
          var id = this.selected, p = parentOf[id], n = byId[id], here = this._target[id] || { dir: 0 };
          if (this.layout === "down") {      // up the tree, down into it, along the row
            if (dir === "up") { if (p) this.select(p.id); }
            else if (dir === "down") { if (!n.collapsed && n.children && n.children.length) this.select(n.children[Math.floor((n.children.length - 1) / 2)].id); }
            else if (p) { var k = p.children.indexOf(n) + (dir === "left" ? -1 : 1); if (p.children[k]) this.select(p.children[k].id); }
            return;
          }
          if (dir === "up" || dir === "down") {
            if (!p) return;
            var sibs = p.children.filter(function (k) { return this._target[k.id] && this._target[k.id].dir === here.dir; }, this), i = sibs.indexOf(n);
            var next = sibs[i + (dir === "up" ? -1 : 1)]; if (next) this.select(next.id);
            return;
          }
          var want = dir === "right" ? 1 : -1;
          if (!p) {          // the centre: into the branches on that side
            var first = (n.children || []).find(function (k) { return this._target[k.id] && this._target[k.id].dir === want; }, this);
            if (first) this.select(first.id); return;
          }
          if (here.dir === want) { if (!n.collapsed && n.children && n.children.length) this.select(n.children[0].id); }
          else this.select(p.id);
        },
        key: function (e) {
          if (this.editingId || this.importOpen) return;
          var k = e.key, mod = e.ctrlKey || e.metaKey, done = true;
          var down = this.layout === "down";
          if (mod && (k === "z" || k === "Z")) { if (e.shiftKey) this.redo(); else this.undo(); }
          else if (mod && k === "y") this.redo();
          else if (mod && k === "Enter") this.toggleDone();
          else if (mod && (k === "f" || k === "F")) this.openFind();
          else if (mod) done = false;
          else if (e.altKey && (k === (down ? "ArrowLeft" : "ArrowUp") || k === (down ? "ArrowRight" : "ArrowDown"))) this.moveSibling(k === "ArrowUp" || k === "ArrowLeft" ? -1 : 1);
          else if (k === "Tab") this.addChild();
          else if (k === "Enter") this.addSibling();
          else if (k === "Delete" || k === "Backspace") this.remove();
          else if (k === " " || k === "F2") this.edit(false);
          else if (k === "/") this.fold();
          else if (k === "ArrowUp") this.nav("up"); else if (k === "ArrowDown") this.nav("down");
          else if (k === "ArrowLeft") this.nav("left"); else if (k === "ArrowRight") this.nav("right");
          else if (k === "0") this.fit(); else if (k === "+" || k === "=") this.view.zoomBy(1.2); else if (k === "-") this.view.zoomBy(1 / 1.2);
          else if (k.length === 1 && !e.altKey) this.edit(false, k);
          else done = false;
          if (done) { e.preventDefault(); e.stopPropagation(); }
        },

        /* mouse and touch: tap to pick, tap again or double-click to edit, drag an idea onto another to move it */
        pointers: function () {
          var self = this, c = this.$refs.canvas, drag = null, lastTap = { id: null, t: 0 };
          c.addEventListener("pointerdown", function (e) {
            if (self.editingId && e.target.closest(".is-editing")) return;
            var nodeEl = e.target.closest(".wmm-node");
            if (e.target.closest(".wmm-fold") && nodeEl) { self.select(nodeEl.getAttribute("data-id")); self.fold(); e.preventDefault(); return; }
            if (nodeEl && e.isPrimary && !self.view.pinch) {
              var id = nodeEl.getAttribute("data-id");
              drag = { id: id, x: e.clientX, y: e.clientY, moved: false, el: nodeEl, base: pos[id] };
              c.setPointerCapture(e.pointerId); e.preventDefault(); c.focus({ preventScroll: true });
              return;
            }
            c.focus({ preventScroll: true });
            self.view.down(e);
          });
          c.addEventListener("pointermove", function (e) {
            if (drag) {
              var dx = (e.clientX - drag.x) / self.view.k, dy = (e.clientY - drag.y) / self.view.k;
              if (!drag.moved && Math.abs(dx) + Math.abs(dy) < 6 / self.view.k) return;
              if (!drag.moved) {
                if (drag.id === M.root.id) { drag = null; return; }
                drag.moved = true; drag.el.classList.add("is-dragging");
              }
              drag.el.style.transform = "translate(" + (drag.base.x + dx) + "px," + (drag.base.y + dy) + "px)";
              drag.el.style.pointerEvents = "none";
              var under = d.elementFromPoint(e.clientX, e.clientY), t = under && under.closest(".wmm-node");
              var tid = t && t.getAttribute("data-id");
              if (drag.over && drag.over !== tid && els[drag.over]) els[drag.over].classList.remove("is-drop");
              drag.over = tid && tid !== drag.id && !self.isInside(tid, drag.id) ? tid : null;
              if (drag.over) els[drag.over].classList.add("is-drop");
              return;
            }
            self.view.move(e);
          });
          function end(e) {
            if (drag) {
              var dd = drag; drag = null;
              dd.el.classList.remove("is-dragging"); dd.el.style.pointerEvents = "";
              if (dd.over && els[dd.over]) els[dd.over].classList.remove("is-drop");
              if (dd.moved) {
                if (dd.over) { self.snapshot(); var n = byId[dd.id], p = parentOf[dd.id]; p.children.splice(p.children.indexOf(n), 1); var t = byId[dd.over]; t.children = t.children || []; t.children.push(n); t.collapsed = false; self.save(); }
                self.render(true); self.select(dd.id);
              } else {
                var now = Date.now();
                if (self.selected === dd.id && (now - lastTap.t < 400 || e.pointerType !== "mouse")) self.edit(false);
                else self.select(dd.id);
                lastTap = { id: dd.id, t: now };
              }
              return;
            }
            self.view.up(e);
          }
          c.addEventListener("pointerup", end); c.addEventListener("pointercancel", end);
          c.addEventListener("dblclick", function (e) { var n = e.target.closest(".wmm-node"); if (n && !self.editingId) { self.select(n.getAttribute("data-id")); self.edit(false); } });
        },
        isInside: function (id, ancestor) { var p = parentOf[id]; while (p) { if (p.id === ancestor) return true; p = parentOf[p.id]; } return false; },

        /* outline in and out */
        outline: function () {
          var lines = [];
          (function walk(n, depth) {
            var text = String(n.text).replace(/\s+/g, " ").trim();
            lines.push(depth === 0 ? "# " + text + "\n" : new Array(depth).join("  ") + "- " + (n.done ? "[x] " : "") + text);
            (n.children || []).forEach(function (k) { walk(k, depth + 1); });
          })(M.root, 0);
          return lines.join("\n") + "\n";
        },
        importOutline: function () {
          var raw = (this.importText || "").replace(/\t/g, "    ").split(/\r?\n/).filter(function (l) { return l.trim(); });
          if (!raw.length) { toast(TEXT.importEmpty, "warn"); return; }
          var title = null;
          if (/^\s*#{1,6}\s+/.test(raw[0])) title = raw.shift().replace(/^\s*#{1,6}\s+/, "").trim();
          var items = raw.map(function (l) {
            var ind = l.match(/^\s*/)[0].length;
            return { ind: ind, done: /^\s*[-*+]\s+\[[xX]\]/.test(l), text: l.replace(/^\s*([-*+]\s+(\[[ xX]\]\s+)?|\d+[.)]\s+|#{1,6}\s+)?/, "").trim() };
          }).filter(function (i) { return i.text; });
          var tops = items.filter(function (i) { return i.ind === Math.min.apply(null, items.map(function (x) { return x.ind; })); });
          if (!title && tops.length === 1) { title = tops[0].text; items.splice(items.indexOf(tops[0]), 1); }
          var rootNode = { id: "r", text: title || M.root.text, children: [] }, stack = [{ ind: -1, node: rootNode }];
          var self = this;
          items.forEach(function (i) {
            while (stack.length > 1 && stack[stack.length - 1].ind >= i.ind) stack.pop();
            var n = self.newNode(i.text); if (i.done) n.done = true; stack[stack.length - 1].node.children.push(n); stack.push({ ind: i.ind, node: n });
          });
          if (M.root.children && M.root.children.length && !confirm(TEXT.replaceMap)) return;
          this.snapshot(); M.root = rootNode; this.importOpen = false; this.importText = "";
          this.render(true); this.select("r"); this.save(); var me = this; setTimeout(function () { me.fit(); }, 260);
        },
        makeTasks: function () {
          var self = this;
          if (!this.selected) { toast(TEXT.pickIdea, "warn"); return; }
          this.action("tasks", { node: this.selected }).then(function (res) {
            if (res && res.ok) toast(TEXT.tasksMade + ": " + res.count, "good", { label: TEXT.seeTasks, run: function () { location.href = res.url; } });
          });
        },

        /* the picture, for export and the list */
        toSVG: function () {
          var t = this._target; if (!t || !Object.keys(t).length) return null;
          var b = this.bounds(), pad = 28, self = this, parts = [];
          var w = Math.ceil(b.x2 - b.x1 + pad * 2), h = Math.ceil(b.y2 - b.y1 + pad * 2), ox = pad - b.x1, oy = pad - b.y1;
          var savedPos = pos; pos = {}; Object.keys(t).forEach(function (id) { pos[id] = t[id]; });
          Object.keys(t).forEach(function (id) {
            var p = parentOf[id]; if (!p || !t[p.id]) return;
            parts.push('<path d="' + self.linkPath(p.id, id) + '" stroke="' + self.branchColor(id) + '" stroke-width="' + (t[id].depth === 1 ? 3 : 2) + '" fill="none" stroke-linecap="round"/>');
          });
          pos = savedPos;
          Object.keys(t).forEach(function (id) {
            var n = byId[id], p = t[id], lvl = mmLevel(p.depth), c = self.branchColor(id), pd = MM.PAD[lvl], fs = MM.FONT[lvl];
            var lines = String(n.text).split("\n"), lh = fs * MM.LH, ty = p.y + pd[0] + fs * 0.98;
            if (lvl === 0) parts.push('<rect x="' + p.x + '" y="' + p.y + '" width="' + p.w + '" height="' + p.h + '" rx="' + Math.min(p.h / 2, 26) + '" fill="#1f2a24"/>');
            else if (lvl === 1) parts.push('<rect x="' + p.x + '" y="' + p.y + '" width="' + p.w + '" height="' + p.h + '" rx="10" fill="' + c + '22" stroke="' + c + '" stroke-width="2"/>');
            else if (p.down) parts.push('<rect x="' + p.x + '" y="' + p.y + '" width="' + p.w + '" height="' + p.h + '" rx="8" fill="' + c + '12" stroke="' + c + '" stroke-width="1.5"/>');
            else parts.push('<line x1="' + p.x + '" y1="' + (p.y + p.h) + '" x2="' + (p.x + p.w) + '" y2="' + (p.y + p.h) + '" stroke="' + c + '" stroke-width="2"/>');
            var boxed = lvl < 2 || p.down, fill = lvl === 0 ? "#ffffff" : n.done ? "#6b7280" : "#1f2a24", anchor = boxed ? "middle" : "start", tx = boxed ? p.x + p.w / 2 : p.x + pd[1];
            if (lvl === 2 && p.down) ty = p.y + (p.h - lines.length * lh) / 2 + fs * 0.98;
            parts.push(svgLines(lines, tx, ty, fs, lh, 'font-weight="' + MM.WEIGHT[lvl] + '" fill="' + fill + '" text-anchor="' + anchor + '"' + (n.done ? ' text-decoration="line-through"' : "")));
          });
          var svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ' + w + " " + h + '" width="' + w + '" height="' + h + '" font-family="' + esc(FONT) + '">' +
            '<rect width="100%" height="100%" fill="#ffffff"/><g transform="translate(' + ox + "," + oy + ')">' + parts.join("") + "</g></svg>";
          return { svg: svg, w: w, h: h };
        },
      };
    });

    /* ══════════════════════════════════════════════════════════════════════
       System design board
       ══════════════════════════════════════════════════════════════════════ */
    // Pictures for each part (24×24, drawn with lines), and the colour family it belongs to.
    var P = {
      client: ["M15.75 6a3.75 3.75 0 1 1-7.5 0 3.75 3.75 0 0 1 7.5 0ZM4.5 20.1a7.5 7.5 0 0 1 15 0A17.9 17.9 0 0 1 12 21.75c-2.7 0-5.2-.6-7.5-1.65Z", "#495057"],
      mobile: ["M10.5 1.5H8.25A2.25 2.25 0 0 0 6 3.75v16.5a2.25 2.25 0 0 0 2.25 2.25h7.5A2.25 2.25 0 0 0 18 20.25V3.75a2.25 2.25 0 0 0-2.25-2.25H13.5m-3 0V3h3V1.5m-3 0h3m-3 18.75h3", "#495057"],
      web: ["M3.75 4.5h16.5a1.5 1.5 0 0 1 1.5 1.5v12a1.5 1.5 0 0 1-1.5 1.5H3.75a1.5 1.5 0 0 1-1.5-1.5V6a1.5 1.5 0 0 1 1.5-1.5ZM2.25 8.25h19.5M5.25 6.4h.01M7.5 6.4h.01", "#495057"],
      dns: ["M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Zm0 0c2.1-2.4 3.4-5.6 3.4-9S14.1 5.4 12 3m0 18c-2.1-2.4-3.4-5.6-3.4-9S9.9 5.4 12 3M3.6 9h16.8M3.6 15h16.8", "#1c7ed6"],
      cdn: ["M2.25 15a4.5 4.5 0 0 0 4.5 4.5H18a3.75 3.75 0 0 0 1.33-7.26 3 3 0 0 0-3.76-3.85A5.25 5.25 0 0 0 5.4 10.2 4.5 4.5 0 0 0 2.25 15Z", "#1c7ed6"],
      lb: ["M12 3v4.5m0 0-6.75 5.25M12 7.5l6.75 5.25M12 7.5v5.25M5.25 12.75V18m6.75-5.25V18m6.75-5.25V18M10.5 3h3M3.75 18h3m3.75 0h3m3.75 0h3", "#1c7ed6"],
      gateway: ["M9 12.75 11.25 15 15 9.75m-3-7.04A11.96 11.96 0 0 1 3.6 6 12 12 0 0 0 3 9.75c0 5.6 3.82 10.3 9 11.62 5.18-1.33 9-6.03 9-11.62 0-1.31-.21-2.57-.6-3.75h-.15c-3.2 0-6.1-1.25-8.25-3.29Z", "#1c7ed6"],
      service: ["M5.25 14.25h13.5m-13.5 0a3 3 0 0 1-3-3m3 3a3 3 0 1 0 0 6h13.5a3 3 0 1 0 0-6m-16.5-3a3 3 0 0 1 3-3h13.5a3 3 0 0 1 3 3m-19.5 0a4.5 4.5 0 0 1 .9-2.7L5.74 5.1a3.38 3.38 0 0 1 2.7-1.35h7.12c1.07 0 2.07.5 2.7 1.35l2.6 3.45c.58.78.9 1.73.9 2.7m0 0a3 3 0 0 1-3 3m0 3h.01m-3 0h.01", "#5f3dc4"],
      worker: ["M9.6 3.94c.09-.54.56-.94 1.11-.94h2.59c.55 0 1.02.4 1.11.94l.21 1.28c.07.42.38.76.77.93.07.03.14.07.22.11.36.2.8.26 1.2.11l1.22-.46a1.13 1.13 0 0 1 1.37.49l1.3 2.25c.27.47.16 1.07-.26 1.42l-1 .83c-.33.27-.5.69-.49 1.12v.26c0 .43.16.84.49 1.11l1 .83c.42.35.53.95.26 1.42l-1.3 2.25a1.13 1.13 0 0 1-1.37.49l-1.22-.46c-.41-.15-.84-.08-1.2.11l-.22.12c-.39.16-.7.5-.77.92l-.21 1.28c-.09.54-.56.94-1.11.94h-2.59c-.55 0-1.02-.4-1.11-.94l-.21-1.28a1.24 1.24 0 0 0-.77-.92 6 6 0 0 1-.22-.12c-.36-.2-.79-.26-1.2-.11l-1.22.46a1.13 1.13 0 0 1-1.37-.49l-1.3-2.25a1.13 1.13 0 0 1 .26-1.42l1-.83c.33-.27.5-.68.49-1.11v-.26c0-.43-.16-.85-.49-1.12l-1-.83a1.13 1.13 0 0 1-.26-1.42l1.3-2.25a1.13 1.13 0 0 1 1.37-.49l1.22.46c.4.15.84.09 1.2-.11l.22-.11c.39-.17.7-.51.77-.93l.21-1.28ZM15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z", "#5f3dc4"],
      function: ["M6 4.5h2.25l7.5 15H18M12 10.5 6.75 19.5", "#5f3dc4"],
      auth: ["M15.75 5.25a3 3 0 0 1 3 3m3 0a6 6 0 0 1-7.03 5.91c-.56-.1-1.16.03-1.56.43L10.5 17.25H8.25v2.25H6v2.25H2.25v-2.82c0-.6.24-1.17.66-1.59l6.6-6.6c.4-.4.52-1 .43-1.56A6 6 0 1 1 21.75 8.25Z", "#e8590c"],
      db: ["M20.25 6.38c0 2.27-3.69 4.12-8.25 4.12S3.75 8.65 3.75 6.38m16.5 0c0-2.28-3.69-4.13-8.25-4.13S3.75 4.1 3.75 6.38m16.5 0v11.24c0 2.28-3.69 4.13-8.25 4.13s-8.25-1.85-8.25-4.13V6.38m16.5 5.62c0 2.28-3.69 4.13-8.25 4.13S3.75 14.28 3.75 12", "#2f9e44"],
      nosql: ["M12 2.25 20.25 7v10L12 21.75 3.75 17V7L12 2.25Zm0 0v9.75m0 0 8.25-5M12 12 3.75 7", "#2f9e44"],
      cache: ["M3.75 13.5 14.25 2.25 12 10.5h8.25L9.75 21.75 12 13.5H3.75Z", "#e03131"],
      queue: ["M3 6.75h4.5v10.5H3zM9.75 6.75h4.5v10.5h-4.5zM16.5 6.75H21v10.5h-4.5z", "#ae3ec9"],
      stream: ["M3 7.5c3 0 3-2.25 6-2.25s3 2.25 6 2.25 3-2.25 6-2.25M3 13.5c3 0 3-2.25 6-2.25s3 2.25 6 2.25 3-2.25 6-2.25M3 19.5c3 0 3-2.25 6-2.25s3 2.25 6 2.25 3-2.25 6-2.25", "#ae3ec9"],
      storage: ["M20.25 7.5 19.63 18.08a2.25 2.25 0 0 1-2.25 2.12H6.62a2.25 2.25 0 0 1-2.25-2.12L3.75 7.5M10 11.25h4M3.38 7.5h17.25c.62 0 1.12-.5 1.12-1.12v-1.5c0-.63-.5-1.13-1.12-1.13H3.38c-.63 0-1.13.5-1.13 1.13v1.5c0 .62.5 1.12 1.13 1.12Z", "#0c8599"],
      search: ["m21 21-5.2-5.2m0 0A7.5 7.5 0 1 0 5.2 5.2a7.5 7.5 0 0 0 10.6 10.6Z", "#0c8599"],
      analytics: ["M3 13.13c0-.62.5-1.13 1.13-1.13h2.25c.62 0 1.12.5 1.12 1.13v6.75c0 .62-.5 1.12-1.12 1.12H4.13C3.5 21 3 20.5 3 19.88v-6.75Zm6.75-4.5c0-.63.5-1.13 1.13-1.13h2.25c.62 0 1.12.5 1.12 1.13v11.25c0 .62-.5 1.12-1.12 1.12h-2.25c-.63 0-1.13-.5-1.13-1.12V8.63ZM16.5 4.13c0-.63.5-1.13 1.13-1.13h2.25C20.5 3 21 3.5 21 4.13v15.75c0 .62-.5 1.12-1.12 1.12h-2.25c-.63 0-1.13-.5-1.13-1.12V4.13Z", "#0c8599"],
      external: ["M13.5 6H5.25A2.25 2.25 0 0 0 3 8.25v10.5A2.25 2.25 0 0 0 5.25 21h10.5A2.25 2.25 0 0 0 18 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25", "#f08c00"],
      monitor: ["M3.75 3v11.25A2.25 2.25 0 0 0 6 16.5h2.25M3.75 3h-1.5m1.5 0h16.5m0 0h1.5m-1.5 0v11.25A2.25 2.25 0 0 1 18 16.5h-2.25m-7.5 0h7.5m-7.5 0-1 3m8.5-3 1 3m0 0 .5 1.5m-.5-1.5h-9.5m0 0-.5 1.5M9 11.25v1.5M12 9v3.75m3-6v6.75", "#f08c00"],
      note: ["M16.86 4.49 18.55 2.8a1.88 1.88 0 1 1 2.65 2.65L10.58 16.07a4.5 4.5 0 0 1-1.9 1.13L6 18l.8-2.68a4.5 4.5 0 0 1 1.13-1.9l8.93-8.93Z", "#f08c00"],
      zone: ["M3.75 6A2.25 2.25 0 0 1 6 3.75h2.25M3.75 6v2.25m0 7.5V18A2.25 2.25 0 0 0 6 20.25h2.25m7.5 0H18A2.25 2.25 0 0 0 20.25 18v-2.25m0-7.5V6A2.25 2.25 0 0 0 18 3.75h-2.25", "#868e96"],
    };
    var DEF_SIZE = { zone: [320, 220], note: [200, 110], client: [140, 72], mobile: [140, 72] };
    function partColor(n) { return n.color || (P[n.type] || P.service)[1]; }
    function partIcon(type, size) {
      var p = (P[type] || P.service)[0];
      return '<svg viewBox="0 0 24 24" width="' + (size || 22) + '" height="' + (size || 22) + '" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="' + p + '"/></svg>';
    }
    /* Where the line between two boxes leaves the first box (its edge, towards the other's centre). */
    function edgePoint(a, b) {
      var ax = a.x + a.w / 2, ay = a.y + a.h / 2, bx = b.x + b.w / 2, by = b.y + b.h / 2, dx = bx - ax, dy = by - ay;
      if (!dx && !dy) return { x: ax, y: ay };
      var sx = dx ? (a.w / 2) / Math.abs(dx) : Infinity, sy = dy ? (a.h / 2) / Math.abs(dy) : Infinity, s = Math.min(sx, sy);
      return { x: ax + dx * s, y: ay + dy * s };
    }
    /* A link between two boxes as an SVG path: straight (centre to centre, cut at the edges),
       curved or with right angles (side to side). `endFrom`/`startTo` aim the arrowheads. */
    function linkShape(a, b, shape) {
      if (shape !== "curve" && shape !== "elbow") {
        var p1 = edgePoint(a, b), p2 = edgePoint(b, a);
        return { d: "M" + p1.x + "," + p1.y + " L" + p2.x + "," + p2.y, a: p1, b: p2, endFrom: p1, startTo: p2,
                 mid: { x: (p1.x + p2.x) / 2, y: (p1.y + p2.y) / 2 }, len: Math.hypot(p2.x - p1.x, p2.y - p1.y) };
      }
      var acx = a.x + a.w / 2, acy = a.y + a.h / 2, bcx = b.x + b.w / 2, bcy = b.y + b.h / 2, across = Math.abs(bcx - acx) >= Math.abs(bcy - acy), s, t;
      if (across) { var sx = bcx >= acx ? 1 : -1; s = { x: acx + sx * a.w / 2, y: acy }; t = { x: bcx - sx * b.w / 2, y: bcy }; }
      else { var sy = bcy >= acy ? 1 : -1; s = { x: acx, y: acy + sy * a.h / 2 }; t = { x: bcx, y: bcy - sy * b.h / 2 }; }
      var mx = (s.x + t.x) / 2, my = (s.y + t.y) / 2, mid = { x: mx, y: my }, d, c1, c2;
      if (shape === "curve") {
        c1 = across ? { x: mx, y: s.y } : { x: s.x, y: my }; c2 = across ? { x: mx, y: t.y } : { x: t.x, y: my };
        d = "M" + s.x + "," + s.y + " C" + c1.x + "," + c1.y + " " + c2.x + "," + c2.y + " " + t.x + "," + t.y;
      } else {
        c1 = across ? { x: mx, y: s.y } : { x: s.x, y: my }; c2 = across ? { x: mx, y: t.y } : { x: t.x, y: my };
        d = "M" + s.x + "," + s.y + " L" + c1.x + "," + c1.y + " L" + c2.x + "," + c2.y + " L" + t.x + "," + t.y;
      }
      return { d: d, a: s, b: t, endFrom: c2, startTo: c1, mid: mid, len: Math.abs(t.x - s.x) + Math.abs(t.y - s.y) };
    }
    function arrowHead(x, y, fromX, fromY, size) {
      var ang = Math.atan2(y - fromY, x - fromX), s = size || 10, a1 = ang + Math.PI * 0.85, a2 = ang - Math.PI * 0.85;
      return "M" + x + "," + y + " L" + (x + Math.cos(a1) * s) + "," + (y + Math.sin(a1) * s) + " L" + (x + Math.cos(a2) * s) + "," + (y + Math.sin(a2) * s) + " Z";
    }
    function fmtNum(n) {
      if (!isFinite(n)) return "—";
      var u = [[1e12, "T"], [1e9, "B"], [1e6, "M"], [1e3, "K"]];
      for (var i = 0; i < u.length; i++) if (Math.abs(n) >= u[i][0]) return (n / u[i][0]).toFixed(n / u[i][0] >= 100 ? 0 : 1).replace(/\.0$/, "") + u[i][1];
      return n >= 10 ? Math.round(n).toString() : n.toFixed(1).replace(/\.0$/, "");
    }
    function fmtBytes(kb) {
      if (!isFinite(kb)) return "—";
      var u = ["KB", "MB", "GB", "TB", "PB", "EB"], i = 0;
      while (kb >= 1000 && i < u.length - 1) { kb /= 1000; i++; }
      return (kb >= 100 ? Math.round(kb) : kb.toFixed(1).replace(/\.0$/, "")) + " " + u[i];
    }

    Alpine.data("sysBoard", function () {
      var B = null, nodeEls = {}, undoStack = [], redoStack = [];
      return {
        sel: [], edgeSel: null, node: null, edge: null, tab: "item", snap: true, zoom: 100, view: null, connecting: false, marquee: false, flow: false,
        canUndo: false, canRedo: false, colors: COLORS, est: {}, out: {}, count: { nodes: 0, edges: 0 }, empty: true,
        get oneNode() { return this.sel.length === 1; },
        init: function () {
          var self = this;
          B = clone(JSON.parse(d.getElementById("diagram-data").textContent).data || {});
          B.nodes = B.nodes || []; B.edges = B.edges || []; B.est = B.est || {};
          this.est = Object.assign({ dau: 1000000, rpu: 10, rw: 10, size: 1, peak: 3, years: 3, copies: 3 }, B.est);
          try { this.flow = localStorage.getItem("wsb-flow") === "1"; } catch (e) { /* private window */ }
          this.calc();
          this.$root.querySelectorAll("[data-part-icon]").forEach(function (el) { el.innerHTML = partIcon(el.getAttribute("data-part-icon"), 20); });
          this.view = new Viewport(this.$refs.canvas, this.$refs.world, function (k) { self.zoom = Math.round(k * 100); });
          this.editor = { svg: function () { return self.toSVG(); }, preview: function () { var o = self.toSVG(); return o ? o.svg : ""; },
                                text: function () { return self.mermaid(); }, resized: function () { self.fit(); } };
          this.pointers();
          this.render();
          this.$nextTick(function () { self.fit(); });
        },
        iconOf: function (t) { return partIcon(t, 18); },
        byId: function (id) { for (var i = 0; i < B.nodes.length; i++) if (B.nodes[i].id === id) return B.nodes[i]; return null; },
        snapshot: function () { undoStack.push(JSON.stringify({ n: B.nodes, e: B.edges })); if (undoStack.length > 120) undoStack.shift(); redoStack = []; this.canUndo = true; this.canRedo = false; },
        restore: function (s) { var o = JSON.parse(s); B.nodes = o.n; B.edges = o.e; this.pick([]); this.render(); this.save(); },
        undo: function () { if (!undoStack.length) return; redoStack.push(JSON.stringify({ n: B.nodes, e: B.edges })); this.restore(undoStack.pop()); this.canUndo = !!undoStack.length; this.canRedo = true; },
        redo: function () { if (!redoStack.length) return; undoStack.push(JSON.stringify({ n: B.nodes, e: B.edges })); this.restore(redoStack.pop()); this.canUndo = true; this.canRedo = !!redoStack.length; },
        save: function () { B.est = Object.assign({}, this.est); this.queue({ data: JSON.stringify(B) }); },
        /* An inspector field changed: redraw now; `commit` (on change) remembers it for undo. */
        changed: function () {
          var key = (this.node || this.edge || {}).id;
          if (key && this._snapFor !== key) { this.snapshot(); this._snapFor = key; }   // one undo step per picked part
          this.render(); this.save();
        },
        commit: function () { this.changed(); },
        retype: function () { this.changed(); },

        /* drawing */
        render: function () {
          var self = this, seen = {}, zones = this.$refs.zones, nodes = this.$refs.nodes;
          B.nodes.forEach(function (n) {
            seen[n.id] = true;
            var el = nodeEls[n.id], zone = n.type === "zone";
            if (!el || el._zone !== zone) {
              if (el) el.remove();
              el = d.createElement("div"); el._zone = zone; el.setAttribute("data-id", n.id);
              el.innerHTML = '<span class="wsb-ico"></span><span class="wsb-text"><b class="wsb-label"></b><small class="wsb-tech"></small></span>' +
                '<i class="wsb-port" data-port="n"></i><i class="wsb-port" data-port="e"></i><i class="wsb-port" data-port="s"></i><i class="wsb-port" data-port="w"></i><i class="wsb-resize"></i>';
              (zone ? zones : nodes).appendChild(el); nodeEls[n.id] = el;
              if (!REDUCED) { el.classList.add("is-new"); setTimeout(function () { el.classList.remove("is-new"); }, 300); }
            }
            el.className = "wsb-node" + (zone ? " is-zone" : "") + (n.type === "note" ? " is-note" : "") + (self.sel.indexOf(n.id) >= 0 ? " is-selected" : "");
            el.setAttribute("data-type", n.type);
            el.style.cssText = "transform:translate(" + n.x + "px," + n.y + "px);width:" + n.w + "px;height:" + n.h + "px;--c:" + partColor(n);
            var ico = el.querySelector(".wsb-ico"); if (ico._type !== n.type) { ico.innerHTML = zone || n.type === "note" ? "" : partIcon(n.type, 22); ico._type = n.type; }
            el.querySelector(".wsb-label").textContent = n.label || "";
            el.querySelector(".wsb-tech").textContent = n.type === "note" || zone ? "" : (n.tech || "");
          });
          Object.keys(nodeEls).forEach(function (id) { if (!seen[id]) { nodeEls[id].remove(); delete nodeEls[id]; } });
          this.links();
          this.count = { nodes: B.nodes.filter(function (n) { return n.type !== "zone" && n.type !== "note"; }).length, edges: B.edges.length };
          this.empty = !B.nodes.length;
        },
        edgeGeom: function (e) {
          var a = this.byId(e.from), b = this.byId(e.to); if (!a || !b) return null;
          return linkShape(a, b, e.shape);
        },
        links: function (extra) {
          var self = this, out = [], moving = this.flow && !REDUCED;
          B.edges.forEach(function (e) {
            var g = self.edgeGeom(e); if (!g) return;
            var on = self.edgeSel === e.id, col = on ? "var(--accent)" : "var(--wsb-line)", dashed = e.style === "dashed";
            out.push('<g class="wsb-link' + (on ? " is-selected" : "") + (dashed ? " is-async" : "") + '" data-edge="' + esc(e.id) + '">' +
              '<path class="wsb-hit" d="' + g.d + '"/>' +
              '<path class="wsb-line" d="' + g.d + '" fill="none" stroke="' + col + '" stroke-width="' + (on ? 2.5 : 1.8) + '"' + (dashed ? ' stroke-dasharray="7 5"' : "") + "/>" +
              (e.arrow !== "none" ? '<path d="' + arrowHead(g.b.x, g.b.y, g.endFrom.x, g.endFrom.y) + '" fill="' + col + '"/>' : "") +
              (e.arrow === "both" ? '<path d="' + arrowHead(g.a.x, g.a.y, g.startTo.x, g.startTo.y) + '" fill="' + col + '"/>' : "") +
              (moving ? self.dots(e, g) : "") +
              (e.label ? '<text x="' + g.mid.x + '" y="' + (g.mid.y - 6) + '" class="wsb-elabel">' + esc(e.label) + "</text>" : "") + "</g>");
          });
          if (extra) out.push(extra);
          this.$refs.links.innerHTML = out.join("");
        },
        /* "Show traffic": requests travel along each link (calls that wait in a steady stream,
           fire-and-forget messages as slower, spaced-out packets; both ways for ↔). */
        dots: function (e, g) {
          var len = Math.max(40, g.len), dashed = e.style === "dashed", speed = dashed ? 70 : 150, dur = (len / speed).toFixed(2), n = dashed ? 2 : 3, out = "";
          function one(i, back) {
            var begin = (-(dur / n) * i).toFixed(2);
            return '<circle class="wsb-dot' + (dashed ? " is-async" : "") + '" r="' + (dashed ? 4 : 3.2) + '"><animateMotion dur="' + dur + 's" begin="' + begin + 's" repeatCount="indefinite" path="' + g.d + '"' +
              (back ? ' keyPoints="1;0" keyTimes="0;1" calcMode="linear"' : "") + "/></circle>";
          }
          for (var i = 0; i < n; i++) { out += one(i, false); if (e.arrow === "both") out += one(i + 0.5, true); }
          return out;
        },
        toggleFlow: function () {
          this.flow = !this.flow; this.links();
          try { localStorage.setItem("wsb-flow", this.flow ? "1" : "0"); } catch (e) { /* private window */ }
        },
        setShape: function (shape) {
          if (!this.edge) return;
          this.snapshot(); this.edge.shape = shape === "straight" ? undefined : shape; if (!this.edge.shape) delete this.edge.shape;
          this._lastShape = shape; this.render(); this.save();
        },
        bounds: function () {
          var b = { x1: Infinity, y1: Infinity, x2: -Infinity, y2: -Infinity };
          B.nodes.forEach(function (n) { b.x1 = Math.min(b.x1, n.x); b.y1 = Math.min(b.y1, n.y); b.x2 = Math.max(b.x2, n.x + n.w); b.y2 = Math.max(b.y2, n.y + n.h); });
          return b;
        },
        fit: function () { if (B.nodes.length) this.view.fit(this.bounds(), 40, 1, this.$refs.canvas.clientWidth < 600 ? 0.55 : 0); else { var r = this.$refs.canvas.getBoundingClientRect(); this.view.k = 1; this.view.x = r.width / 2 - 80; this.view.y = r.height / 2 - 36; this.view.apply(); } },

        /* picking */
        pick: function (ids, edgeId) {
          this.sel = ids; this.edgeSel = edgeId || null; this._snapFor = null;
          this.node = ids.length === 1 ? this.byId(ids[0]) : null;
          this.edge = edgeId ? B.edges.filter(function (e) { return e.id === edgeId; })[0] || null : null;
          this.tab = "item";
          var self = this; Object.keys(nodeEls).forEach(function (id) { nodeEls[id].classList.toggle("is-selected", ids.indexOf(id) >= 0); });
          this.links();
          if (this.node) { var n = this.node; this.view.reveal({ x1: n.x, y1: n.y, x2: n.x + n.w, y2: n.y + n.h }); }
        },
        edgeTitle: function () {
          if (!this.edge) return ""; var a = this.byId(this.edge.from), b = this.byId(this.edge.to);
          return (a ? a.label : "?") + " → " + (b ? b.label : "?");
        },
        /* adding parts */
        place: function (type, x, y) {
          var s = DEF_SIZE[type] || [160, 72], g = this.snap ? 10 : 1;
          var n = { id: uid("p"), type: type, x: Math.round((x - s[0] / 2) / g) * g, y: Math.round((y - s[1] / 2) / g) * g, w: s[0], h: s[1],
                    label: (TEXT.parts || {})[type] || type, tech: "", note: "", color: "" };
          this.snapshot();
          if (type === "zone") B.nodes.unshift(n); else B.nodes.push(n);
          this.render(); this.pick([n.id]); this.save(); this.$refs.canvas.focus({ preventScroll: true });
          return n;
        },
        paletteClick: function (type) {
          if (this._paletteDragged) { this._paletteDragged = false; return; }
          var r = this.$refs.canvas.getBoundingClientRect(), c = this.view.toWorld(r.left + r.width / 2, r.top + r.height / 2);
          var k = B.nodes.length % 6; this.place(type, c.x + k * 14, c.y + k * 14);
        },
        /* drag a part from the palette onto the board */
        paletteDown: function (e, type) {
          if (e.button > 0) return;
          var self = this, sx = e.clientX, sy = e.clientY, ghost = null;
          function move(ev) {
            if (!ghost && Math.hypot(ev.clientX - sx, ev.clientY - sy) < 8) return;
            if (!ghost) { ghost = d.createElement("div"); ghost.className = "wsb-ghost"; ghost.innerHTML = partIcon(type, 22); d.body.appendChild(ghost); self._paletteDragged = true; }
            ghost.style.transform = "translate(" + (ev.clientX - 22) + "px," + (ev.clientY - 22) + "px)";
          }
          function up(ev) {
            d.removeEventListener("pointermove", move); d.removeEventListener("pointerup", up); d.removeEventListener("pointercancel", up);
            if (!ghost) return;
            ghost.remove();
            var r = self.$refs.canvas.getBoundingClientRect();
            if (ev.clientX >= r.left && ev.clientX <= r.right && ev.clientY >= r.top && ev.clientY <= r.bottom) {
              var p = self.view.toWorld(ev.clientX, ev.clientY); self.place(type, p.x, p.y);
            }
            setTimeout(function () { self._paletteDragged = false; }, 50);
          }
          d.addEventListener("pointermove", move); d.addEventListener("pointerup", up); d.addEventListener("pointercancel", up);
        },
        /* changing parts */
        removeSelected: function () {
          if (!this.sel.length && !this.edgeSel) return;
          this.snapshot();
          var gone = this.sel;
          if (gone.length) {
            B.nodes = B.nodes.filter(function (n) { return gone.indexOf(n.id) < 0; });
            B.edges = B.edges.filter(function (e) { return gone.indexOf(e.from) < 0 && gone.indexOf(e.to) < 0; });
          } else { var eid = this.edgeSel; B.edges = B.edges.filter(function (e) { return e.id !== eid; }); }
          this.pick([]); this.render(); this.save(); this.$refs.canvas.focus({ preventScroll: true });
        },
        duplicate: function () {
          if (!this.sel.length) return;
          this.snapshot(); var map = {}, made = [], self = this;
          this.sel.forEach(function (id) { var n = self.byId(id); if (!n) return; var c = clone(n); c.id = uid("p"); c.x += 30; c.y += 30; map[id] = c.id; B.nodes.push(c); made.push(c.id); });
          B.edges.slice().forEach(function (e) { if (map[e.from] && map[e.to]) { var c = clone(e); c.id = uid("e"); c.from = map[e.from]; c.to = map[e.to]; B.edges.push(c); } });
          this.render(); this.pick(made); this.save();
        },
        picked: function () { var self = this; return this.sel.map(function (id) { return self.byId(id); }).filter(Boolean); },
        align: function (how) {
          var ns = this.picked(); if (ns.length < 2) return;
          var x1 = Math.min.apply(null, ns.map(function (n) { return n.x; })), x2 = Math.max.apply(null, ns.map(function (n) { return n.x + n.w; }));
          var y1 = Math.min.apply(null, ns.map(function (n) { return n.y; })), y2 = Math.max.apply(null, ns.map(function (n) { return n.y + n.h; }));
          this.snapshot();
          ns.forEach(function (n) {
            if (how === "left") n.x = x1; else if (how === "right") n.x = x2 - n.w; else if (how === "hcenter") n.x = Math.round((x1 + x2) / 2 - n.w / 2);
            else if (how === "top") n.y = y1; else if (how === "bottom") n.y = y2 - n.h; else if (how === "vmiddle") n.y = Math.round((y1 + y2) / 2 - n.h / 2);
          });
          this.render(); this.save();
        },
        /* the first and last stay put; the others are spread so their centres are evenly apart */
        distribute: function (axis) {
          var ns = this.picked(); if (ns.length < 3) return;
          var pos = axis === "x" ? function (n) { return n.x + n.w / 2; } : function (n) { return n.y + n.h / 2; };
          ns.sort(function (a, b) { return pos(a) - pos(b); });
          var first = pos(ns[0]), step = (pos(ns[ns.length - 1]) - first) / (ns.length - 1);
          this.snapshot();
          ns.forEach(function (n, i) { var c = Math.round(first + step * i); if (axis === "x") n.x = c - n.w / 2; else n.y = c - n.h / 2; });
          this.render(); this.save();
        },
        sameSize: function () {
          var ns = this.picked().filter(function (n) { return n.type !== "zone"; }); if (ns.length < 2) return;
          this.snapshot(); var w = ns[0].w, h = ns[0].h; ns.forEach(function (n) { n.w = w; n.h = h; });
          this.render(); this.save();
        },
        /* Copy and paste — also into another board (kept in this browser) */
        copy: function (cut) {
          var ns = this.picked(); if (!ns.length) return;
          var ids = {}; ns.forEach(function (n) { ids[n.id] = true; });
          var clip = { nodes: clone(ns), edges: clone(B.edges.filter(function (e) { return ids[e.from] && ids[e.to]; })) };
          this._clip = clip;
          try { localStorage.setItem("wsb-clip", JSON.stringify(clip)); } catch (e) { /* private window */ }
          if (cut) this.removeSelected(); else toast(TEXT.copiedParts);
        },
        paste: function () {
          var clip = this._clip;
          try { clip = JSON.parse(localStorage.getItem("wsb-clip") || "null") || clip; } catch (e) { /* use the one in memory */ }
          if (!clip || !clip.nodes || !clip.nodes.length) return;
          var x1 = Math.min.apply(null, clip.nodes.map(function (n) { return n.x; })), y1 = Math.min.apply(null, clip.nodes.map(function (n) { return n.y; }));
          var at = this._pointer ? this.view.toWorld(this._pointer.x, this._pointer.y) : { x: x1 + 40, y: y1 + 40 };
          var g = this.snap ? 10 : 1, dx = Math.round((at.x - x1) / g) * g, dy = Math.round((at.y - y1) / g) * g, map = {}, made = [];
          this.snapshot();
          clip.nodes.forEach(function (n) { var c = clone(n); c.id = uid("p"); c.x += dx; c.y += dy; map[n.id] = c.id; made.push(c.id); if (c.type === "zone") B.nodes.unshift(c); else B.nodes.push(c); });
          clip.edges.forEach(function (e) { var c = clone(e); c.id = uid("e"); c.from = map[e.from]; c.to = map[e.to]; B.edges.push(c); });
          this.render(); this.pick(made); this.save(); toast(TEXT.pasted);
        },
        reverseEdge: function () { if (!this.edge) return; this.snapshot(); var t = this.edge.from; this.edge.from = this.edge.to; this.edge.to = t; this.render(); this.save(); },
        connect: function (from, to) {
          if (!from || !to || from === to) return;
          var exists = B.edges.some(function (e) { return (e.from === from && e.to === to); });
          if (exists) return;
          this.snapshot(); var e = { id: uid("e"), from: from, to: to, label: "", style: "solid", arrow: "end" };
          if (this._lastShape && this._lastShape !== "straight") e.shape = this._lastShape;
          B.edges.push(e); this.render(); this.pick([], e.id); this.save();
        },
        startConnect: function () { if (this.sel.length !== 1) return; this.connecting = this.sel[0]; this.$refs.canvas.focus({ preventScroll: true }); },
        key: function (e) {
          if (/^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName) || e.target.isContentEditable) return;
          var k = e.key, mod = e.ctrlKey || e.metaKey, done = true, self = this;
          if (mod && (k === "z" || k === "Z")) { if (e.shiftKey) this.redo(); else this.undo(); }
          else if (mod && k === "y") this.redo();
          else if (mod && k === "d") this.duplicate();
          else if (mod && (k === "c" || k === "x") && this.sel.length && !String(window.getSelection())) this.copy(k === "x");
          else if (mod && k === "v") this.paste();
          else if (mod && k === "a") this.pick(B.nodes.map(function (n) { return n.id; }));
          else if (mod) done = false;
          else if (k === "Delete" || k === "Backspace") this.removeSelected();
          else if (k === "Escape") { if (this.connecting) this.connecting = false; else this.pick([]); }
          else if (k === "Enter" && this.node) this.editLabel(this.node.id);
          else if (k === "0") this.fit(); else if (k === "+" || k === "=") this.view.zoomBy(1.2); else if (k === "-") this.view.zoomBy(1 / 1.2);
          else if (/^Arrow/.test(k) && this.sel.length) {
            var step = e.shiftKey ? 1 : 10, dx = k === "ArrowLeft" ? -step : k === "ArrowRight" ? step : 0, dy = k === "ArrowUp" ? -step : k === "ArrowDown" ? step : 0;
            if (!this._nudging) { this.snapshot(); this._nudging = true; }
            clearTimeout(this._nudgeT); this._nudgeT = setTimeout(function () { self._nudging = false; }, 600);
            this.sel.forEach(function (id) { var n = self.byId(id); n.x += dx; n.y += dy; });
            this.render(); this.save();
          }
          else done = false;
          if (done) { e.preventDefault(); e.stopPropagation(); }
        },
        /* rename right on the board */
        editLabel: function (id) {
          var el = nodeEls[id], n = this.byId(id); if (!el || !n) return;
          var self = this, t = el.querySelector(".wsb-label"), before = n.label;
          try { t.contentEditable = "plaintext-only"; } catch (err) { t.contentEditable = "true"; }
          if (t.contentEditable !== "plaintext-only") t.contentEditable = "true";
          el.classList.add("is-editing"); t.focus();
          var r = d.createRange(); r.selectNodeContents(t); var s = window.getSelection(); s.removeAllRanges(); s.addRange(r);
          function done(keep) {
            t.removeEventListener("keydown", onKey); t.removeEventListener("blur", onBlur);
            t.contentEditable = "false"; el.classList.remove("is-editing");
            var v = keep ? t.textContent.trim().slice(0, 120) : before;
            if (v && v !== before) { self.snapshot(); n.label = v; self.save(); }
            self.render(); self.pick([id]);
          }
          function onKey(e) { e.stopPropagation(); if (e.key === "Enter") { e.preventDefault(); done(true); self.$refs.canvas.focus(); } else if (e.key === "Escape") { e.preventDefault(); done(false); self.$refs.canvas.focus(); } }
          function onBlur() { done(true); }
          t.addEventListener("keydown", onKey); t.addEventListener("blur", onBlur);
        },

        /* mouse and touch on the board */
        pointers: function () {
          var self = this, c = this.$refs.canvas, act = null, lastTap = { id: null, t: 0 };
          c.addEventListener("pointerdown", function (e) {
            if (e.target.isContentEditable) return;
            var nodeEl = e.target.closest(".wsb-node"), id = nodeEl && nodeEl.getAttribute("data-id");
            var port = e.target.closest(".wsb-port"), resize = e.target.closest(".wsb-resize"), link = e.target.closest(".wsb-link");
            c.focus({ preventScroll: true });
            if (self.connecting) {            // "Connect to…": the next part tapped is the other end
              if (id) self.connect(self.connecting, id);
              self.connecting = false; e.preventDefault(); return;
            }
            if (port && id) { act = { kind: "link", from: id, pid: e.pointerId }; c.setPointerCapture(e.pointerId); e.preventDefault(); return; }
            if (resize && id) { var rn = self.byId(id); self.snapshot(); act = { kind: "resize", n: rn, x: e.clientX, y: e.clientY, w: rn.w, h: rn.h }; c.setPointerCapture(e.pointerId); e.preventDefault(); return; }
            if (id && e.isPrimary) {
              var picked = self.sel.indexOf(id) >= 0 ? self.sel.slice() : (e.shiftKey ? self.sel.concat([id]) : [id]);
              if (e.shiftKey && self.sel.indexOf(id) >= 0) picked = self.sel.filter(function (x) { return x !== id; });
              if (picked.join() !== self.sel.join() || self.edgeSel) self.pick(picked);
              // dragging a zone takes what's inside it along
              var moving = picked.slice();
              picked.forEach(function (pid) {
                var z = self.byId(pid); if (!z || z.type !== "zone") return;
                B.nodes.forEach(function (n) { if (n.id !== z.id && moving.indexOf(n.id) < 0 && n.x >= z.x && n.y >= z.y && n.x + n.w <= z.x + z.w && n.y + n.h <= z.y + z.h) moving.push(n.id); });
              });
              act = { kind: "move", id: id, x: e.clientX, y: e.clientY, moved: false, start: moving.map(function (m) { var n = self.byId(m); return { n: n, x: n.x, y: n.y }; }) };
              c.setPointerCapture(e.pointerId); e.preventDefault();
              return;
            }
            if (link) { self.pick([], link.getAttribute("data-edge")); e.preventDefault(); return; }
            if ((self.marquee || e.shiftKey) && e.isPrimary) {          // drag a box around parts to pick them
              var r0 = c.getBoundingClientRect();
              act = { kind: "box", x: e.clientX, y: e.clientY, add: e.shiftKey, left: r0.left, top: r0.top };
              c.setPointerCapture(e.pointerId); e.preventDefault(); return;
            }
            act = { kind: "pan" };
            self.view.down(e);
          });
          c.addEventListener("pointermove", function (e) {
            self._pointer = { x: e.clientX, y: e.clientY };
            if (!act) return;
            if (act.kind === "pan") { self.view.move(e); return; }
            if (act.kind === "box") {
              var bx = self.$refs.box; bx.hidden = false;
              bx.style.left = Math.min(act.x, e.clientX) - act.left + "px"; bx.style.top = Math.min(act.y, e.clientY) - act.top + "px";
              bx.style.width = Math.abs(e.clientX - act.x) + "px"; bx.style.height = Math.abs(e.clientY - act.y) + "px";
              act.to = { x: e.clientX, y: e.clientY }; return;
            }
            var p = self.view.toWorld(e.clientX, e.clientY);
            if (act.kind === "move") {
              var dx = (e.clientX - act.x) / self.view.k, dy = (e.clientY - act.y) / self.view.k;
              if (!act.moved && Math.abs(dx) + Math.abs(dy) < 4 / self.view.k) return;
              if (!act.moved) { act.moved = true; self.snapshot(); }
              var g = self.snap && !e.altKey ? 10 : 1;
              act.start.forEach(function (s) { s.n.x = Math.round((s.x + dx) / g) * g; s.n.y = Math.round((s.y + dy) / g) * g; });
              self.render();
            } else if (act.kind === "resize") {
              var gg = self.snap ? 10 : 1;
              act.n.w = Math.max(80, Math.round((act.w + (e.clientX - act.x) / self.view.k) / gg) * gg);
              act.n.h = Math.max(48, Math.round((act.h + (e.clientY - act.y) / self.view.k) / gg) * gg);
              self.render();
            } else if (act.kind === "link") {
              var a = self.byId(act.from), under = d.elementFromPoint(e.clientX, e.clientY), t = under && under.closest(".wsb-node");
              var tid = t && t.getAttribute("data-id");
              Object.keys(nodeEls).forEach(function (k) { nodeEls[k].classList.toggle("is-target", k === tid && k !== act.from); });
              act.to = tid !== act.from ? tid : null;
              var s = edgePoint(a, { x: p.x, y: p.y, w: 0, h: 0 });
              self.links('<line class="wsb-temp" x1="' + s.x + '" y1="' + s.y + '" x2="' + p.x + '" y2="' + p.y + '"/>');
            }
          });
          function end(e) {
            if (!act) return;
            var a = act; act = null;
            if (a.kind === "pan") { if (!self.view.up(e)) { if (self.sel.length || self.edgeSel) self.pick([]); } return; }
            if (a.kind === "box") {
              self.$refs.box.hidden = true;
              if (!a.to) { if (!a.add) self.pick([]); return; }
              var p1 = self.view.toWorld(Math.min(a.x, a.to.x), Math.min(a.y, a.to.y)), p2 = self.view.toWorld(Math.max(a.x, a.to.x), Math.max(a.y, a.to.y));
              var inside = B.nodes.filter(function (n) {
                var whole = n.x >= p1.x && n.y >= p1.y && n.x + n.w <= p2.x && n.y + n.h <= p2.y;
                var touch = n.x < p2.x && n.x + n.w > p1.x && n.y < p2.y && n.y + n.h > p1.y;
                return n.type === "zone" ? whole : touch;           // a zone only when it's wholly inside
              }).map(function (n) { return n.id; });
              self.pick(a.add ? self.sel.concat(inside.filter(function (id) { return self.sel.indexOf(id) < 0; })) : inside);
              return;
            }
            if (a.kind === "move") {
              if (a.moved) self.save();
              else {                      // a tap on the picked part: rename it (double tap with a mouse)
                var now = Date.now();
                if (lastTap.id === a.id && now - lastTap.t < 450) self.editLabel(a.id);
                lastTap = { id: a.id, t: now };
              }
            } else if (a.kind === "resize") self.save();
            else if (a.kind === "link") {
              Object.keys(nodeEls).forEach(function (k) { nodeEls[k].classList.remove("is-target"); });
              if (a.to) self.connect(a.from, a.to); else self.links();
            }
          }
          c.addEventListener("pointerup", end); c.addEventListener("pointercancel", end);
          c.addEventListener("dblclick", function (e) { var n = e.target.closest(".wsb-node"); if (n) self.editLabel(n.getAttribute("data-id")); });
          c.addEventListener("pointerleave", function () { self._pointer = null; });
        },

        /* back-of-the-envelope numbers */
        calc: function () {
          var e = this.est, n = function (v, def) { v = parseFloat(v); return isFinite(v) && v >= 0 ? v : def; };
          var dau = n(e.dau, 0), rpu = n(e.rpu, 0), rw = n(e.rw, 0), size = n(e.size, 0), peak = Math.max(1, n(e.peak, 1)), years = n(e.years, 0), copies = Math.max(1, n(e.copies, 1));
          var perDay = dau * rpu, qps = perDay / 86400, w = qps / (rw + 1), r = qps - w;
          var dayKb = w * 86400 * size;
          this.out = {
            qps: fmtNum(qps), peakQps: fmtNum(qps * peak), wqps: fmtNum(w), rqps: fmtNum(r),
            perDay: fmtBytes(dayKb), total: fmtBytes(dayKb * 365 * years * copies),
            inBw: fmtBytes(w * size) + "/s", outBw: fmtBytes(r * size) + "/s",
          };
        },
        estChanged: function () { this.calc(); this.save(); },
        estToNotes: function () {
          var o = this.out, e = this.est;
          var block = "\n## Estimates\n- " + fmtNum(e.dau) + " daily users × " + e.rpu + " requests = **" + o.qps + " requests/s** (peak " + o.peakQps + ")\n" +
            "- Writes " + o.wqps + "/s, reads " + o.rqps + "/s (" + e.rw + " reads per write)\n" +
            "- New data " + o.perDay + "/day → **" + o.total + "** over " + e.years + " years with " + e.copies + " copies\n" +
            "- Bandwidth in " + o.inBw + ", out " + o.outBw + "\n";
          this.notes = (this.notes || "").replace(/\s+$/, "") + "\n" + block; this.queue({ notes: this.notes }); this.tab = "notes";
        },

        /* text and picture */
        mermaid: function () {
          var lines = ["flowchart LR"], safe = function (s) { return String(s || "").replace(/"/g, "'"); }, self = this;
          B.nodes.forEach(function (n) {
            if (n.type === "zone" || n.type === "note") return;
            var label = safe(n.label) + (n.tech ? "<br/><small>" + safe(n.tech) + "</small>" : "");
            var shape = n.type === "db" || n.type === "nosql" ? ['[("', '")]'] : n.type === "queue" || n.type === "stream" ? ['[/"', '"/]'] : n.type === "client" || n.type === "mobile" ? ['(["', '"])'] : ['["', '"]'];
            lines.push("    " + n.id + shape[0] + label + shape[1]);
          });
          B.edges.forEach(function (e) {
            var arrow = e.style === "dashed" ? (e.arrow === "both" ? "<-.->" : e.arrow === "none" ? "-.-" : "-.->") : (e.arrow === "both" ? "<-->" : e.arrow === "none" ? "---" : "-->");
            var a = self.byId(e.from), b = self.byId(e.to);
            if (!a || !b || a.type === "zone" || b.type === "zone") return;
            lines.push("    " + e.from + " " + arrow + (e.label ? '|"' + safe(e.label) + '"|' : "") + " " + e.to);
          });
          return lines.join("\n") + "\n";
        },
        toSVG: function () {
          if (!B.nodes.length) return null;
          var b = this.bounds(), pad = 30, out = [], self = this;
          var w = Math.ceil(b.x2 - b.x1 + pad * 2), h = Math.ceil(b.y2 - b.y1 + pad * 2), ox = pad - b.x1, oy = pad - b.y1;
          B.nodes.forEach(function (n) {
            if (n.type !== "zone") return;
            var c = partColor(n);
            out.push('<rect x="' + n.x + '" y="' + n.y + '" width="' + n.w + '" height="' + n.h + '" rx="14" fill="' + c + '0f" stroke="' + c + '" stroke-width="1.5" stroke-dasharray="6 5"/>');
            out.push('<text x="' + (n.x + 14) + '" y="' + (n.y + 22) + '" font-size="13" font-weight="700" fill="' + c + '">' + esc(n.label) + "</text>");
          });
          B.edges.forEach(function (e) {
            var g = self.edgeGeom(e); if (!g) return;
            out.push('<path d="' + g.d + '" fill="none" stroke="#6b7280" stroke-width="1.8"' + (e.style === "dashed" ? ' stroke-dasharray="7 5"' : "") + "/>");
            if (e.arrow !== "none") out.push('<path d="' + arrowHead(g.b.x, g.b.y, g.endFrom.x, g.endFrom.y) + '" fill="#6b7280"/>');
            if (e.arrow === "both") out.push('<path d="' + arrowHead(g.a.x, g.a.y, g.startTo.x, g.startTo.y) + '" fill="#6b7280"/>');
            if (e.label) out.push('<text x="' + g.mid.x + '" y="' + (g.mid.y - 6) + '" font-size="11" fill="#374151" text-anchor="middle" stroke="#ffffff" stroke-width="4" paint-order="stroke">' + esc(e.label) + "</text>");
          });
          B.nodes.forEach(function (n) {
            if (n.type === "zone") return;
            var c = partColor(n);
            if (n.type === "note") {
              out.push('<rect x="' + n.x + '" y="' + n.y + '" width="' + n.w + '" height="' + n.h + '" rx="6" fill="#fff4bf" stroke="#f0c36d"/>');
              out.push(svgLines(String(n.label || "").split("\n"), n.x + 12, n.y + 24, 13, 18, 'fill="#5c4a00"'));
              return;
            }
            out.push('<rect x="' + n.x + '" y="' + n.y + '" width="' + n.w + '" height="' + n.h + '" rx="12" fill="#ffffff" stroke="' + c + '" stroke-width="1.6"/>');
            out.push('<rect x="' + (n.x + 10) + '" y="' + (n.y + n.h / 2 - 17) + '" width="34" height="34" rx="9" fill="' + c + '1f"/>');
            out.push('<g transform="translate(' + (n.x + 16) + "," + (n.y + n.h / 2 - 11) + ') scale(0.92)" fill="none" stroke="' + c + '" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="' + (P[n.type] || P.service)[0] + '"/></g>');
            var tx = n.x + 54, room = n.w - 66, lines = wrapText(n.label, room, 7.2, 2), tech = n.tech ? wrapText(n.tech, room, 5.9, 1) : [];
            var block = lines.length * 17 + tech.length * 15, ty = n.y + (n.h - block) / 2 + 13;
            out.push(svgLines(lines, tx, ty, 13.5, 17, 'font-weight="650" fill="#1f2a24"'));
            if (tech.length) out.push(svgLines(tech, tx, ty + lines.length * 17, 11, 15, 'fill="#6b7280"'));
          });
          var svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ' + w + " " + h + '" width="' + w + '" height="' + h + '" font-family="' + esc(FONT) + '">' +
            '<rect width="100%" height="100%" fill="#ffffff"/><g transform="translate(' + ox + "," + oy + ')">' + out.join("") + "</g></svg>";
          return { svg: svg, w: w, h: h };
        },
      };
    });

    /* ══════════════════════════════════════════════════════════════════════
       Text diagrams (Mermaid)
       ══════════════════════════════════════════════════════════════════════ */
    var FLOW_LINE = /^(\s*(?:flowchart|graph))\s+(TB|TD|LR|RL|BT)\b/;
    Alpine.data("mermaidEditor", function () {
      var seq = 0, lastGood = "";
      return {
        source: "", error: "", busy: false, failed: false, pane: "code", zoom: 100, view: null, snippets: TEXT.snips || [], drawnOnce: false, look: "",
        get lineNumbers() { var n = this.source.split("\n").length, out = []; for (var i = 1; i <= n; i++) out.push(i); return out.join("\n"); },
        /* A flowchart's direction (TD, LR, BT…), from its first line; "" for other kinds */
        get dir() { var m = FLOW_LINE.exec(this.firstLine()); return m ? m[2] : ""; },
        firstLine: function () {
          var lines = this.source.split("\n"), i = 0;
          if ((lines[0] || "").trim() === "---") { i = lines.indexOf("---", 1) + 1 || lines.length; }
          for (; i < lines.length; i++) { var l = lines[i].trim(); if (l && l.indexOf("%%") !== 0) return lines[i]; }
          return "";
        },
        setDir: function (to) {
          var line = this.firstLine(), at = this.source.indexOf(line); if (!line || at < 0) return;
          var next = FLOW_LINE.exec(line) ? line.replace(FLOW_LINE, function (_m, kw, _d) { return kw + " " + to; }) : line;
          this.source = this.source.slice(0, at) + next + this.source.slice(at + line.length);
          this._refit = true; this.changed();
        },
        toggleLook: function () {
          this.look = this.look === "handDrawn" ? "" : "handDrawn";
          if (this.look) LIVE.data.look = this.look; else delete LIVE.data.look;
          this.queue({ data: JSON.stringify(LIVE.data) });
          this._refit = true; this.draw();
        },
        init: function () {
          var self = this;
          this.source = LIVE.source; this.look = LIVE.data.look || "";
          this.pane = matchMedia("(min-width: 1024px)").matches ? "both" : "view";
          this.view = new Viewport(this.$refs.canvas, this.$refs.world, function (k) { self.zoom = Math.round(k * 100); });
          var c = this.$refs.canvas;
          c.addEventListener("pointerdown", function (e) { self.view.down(e); });
          c.addEventListener("pointermove", function (e) { self.view.move(e); });
          c.addEventListener("pointerup", function (e) { self.view.up(e); }); c.addEventListener("pointercancel", function (e) { self.view.up(e); });
          this.editor = {
            svg: function () { return self.picture(); }, preview: function () { return self.picture().then(function (o) { return o ? o.svg : ""; }); },
            text: function () { return self.source; }, resized: function () { self.fit(); },
          };
          matchMedia("(min-width: 1024px)").addEventListener("change", function (m) { self.pane = m.matches ? "both" : "view"; });
          this.draw();
        },
        changed: function () { LIVE.source = this.source; this.queue({ source: this.source }); clearTimeout(this._t); var self = this; this._t = setTimeout(function () { self.draw(); }, 350); },
        insert: function (text) {
          var ta = this.$refs.text, s = ta.selectionStart || this.source.length, e = ta.selectionEnd || s;
          if (text.charAt(0) === "\n") { var end = this.source.indexOf("\n", e); s = e = end < 0 ? this.source.length : end; }
          this.source = this.source.slice(0, s) + text + this.source.slice(e);
          var self = this, at = s + text.length; this.$nextTick(function () { ta.focus(); ta.setSelectionRange(at, at); });
          this.changed();
        },
        key: function (e) {
          if (e.key === "Tab" && !e.ctrlKey && !e.metaKey) { e.preventDefault(); this.insert("    "); }
          else if (e.key === "Enter" && !e.shiftKey && !e.ctrlKey && !e.metaKey && !e.altKey) {   // keep the line's indent
            var ta = this.$refs.text, s = ta.selectionStart, start = this.source.lastIndexOf("\n", s - 1) + 1;
            var ind = (this.source.slice(start, s).match(/^\s*/) || [""])[0];
            if (ind) {
              e.preventDefault();
              this.source = this.source.slice(0, s) + "\n" + ind + this.source.slice(ta.selectionEnd);
              var at = s + 1 + ind.length; this.$nextTick(function () { ta.setSelectionRange(at, at); });
              this.changed();
            }
          }
        },
        load: function () { return Work.loadMermaid(); },
        /* Draw the text into the view; a mistake keeps the last good drawing (dimmed) and says where. */
        draw: function () {
          var self = this, text = this.source, mine = ++seq;
          this.busy = true;
          this.load().then(function (mm) {
            Work.mermaidTheme(isDark() ? "dark" : "default", self.look);
            return mm.parse(text).then(function () { return mm.render("wmd-" + mine, text); });
          }).then(function (res) {
            if (mine !== seq || !self.$refs.out) return;             // a newer drawing, or switched to drag and drop meanwhile
            self.error = ""; self.busy = false; self.failed = false; lastGood = text;
            self.$refs.out.innerHTML = res.svg;
            var svg = self.$refs.out.querySelector("svg");
            if (svg) { var sz = svgSize(res.svg); svg.removeAttribute("style"); svg.setAttribute("width", sz.w); svg.setAttribute("height", sz.h); self._size = sz; }
            if (!self.drawnOnce || self._refit) { self.drawnOnce = true; self._refit = false; self.$nextTick(function () { self.fit(); }); }
            if (!REDUCED) { self.$refs.out.classList.remove("is-drawn"); void self.$refs.out.offsetWidth; self.$refs.out.classList.add("is-drawn"); }
          }).catch(function (err) {
            if (mine !== seq) return;
            self.busy = false;
            if (err && err.message === "mermaid-load") { self.failed = true; return; }
            self.error = String((err && (err.str || err.message)) || err || "").split("\n").slice(0, 4).join(" ").slice(0, 300);
            d.querySelectorAll("#dwmd-" + mine + ", #wmd-" + mine).forEach(function (n) { n.remove(); });
          });
        },
        fit: function () { var s = this._size; if (s) this.view.fit({ x1: 0, y1: 0, x2: s.w, y2: s.h }, 24, 1.5); },
        /* A light picture for the list and for export, whatever the page's theme. */
        picture: function () {
          var text = lastGood || this.source, look = this.look;
          if (!text.trim()) return Promise.resolve(null);
          return this.load().then(function (mm) {
            Work.mermaidTheme("default", look);
            return mm.render("wmdx-" + (++seq), text).then(function (res) {
              Work.mermaidTheme(isDark() ? "dark" : "default", look);
              // a picture of its own size: Mermaid's width="100%" and max-width style are for the page
              var sz = svgSize(res.svg), svg = res.svg.replace(/<svg\b[^>]*>/, function (tag) {
                return tag.replace(/\s(width|height|style)="[^"]*"/g, "").replace(/^<svg/, '<svg width="' + sz.w + '" height="' + sz.h + '"');
              });
              svg = svg.replace(/(<svg\b[^>]*>)/, '$1<rect width="100%" height="100%" fill="#ffffff"/>');
              return { svg: svg, w: sz.w, h: sz.h };
            });
          }).catch(function () { return null; });
        },
      };
    });
  });
})();
