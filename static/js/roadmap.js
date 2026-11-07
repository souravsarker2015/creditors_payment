/* A roadmap (Productivity), as Linear, Jira Plans, ProductPlan and Aha! show one:
   - Timeline: bars from start to end in lanes, milestones as diamonds, arrows for
     "waits on", drag to move or to change the dates, zoom from weeks to years;
   - Board: Now / Next / Later (or by status), drag between columns;
   - List: every piece of work, sorted by any column;
   - Priorities: value against effort — quick wins, big bets, fill-ins, time sinks.
   The side panel edits one piece of work: its tasks, its updates and how it's going.
   Every change is saved at once (Work.api); the server answers with the item as it
   now is (its progress, health and finish date worked out again), which replaces ours. */
(function () {
  "use strict";
  var d = document;
  var TEXT = (function () { try { return JSON.parse(d.getElementById("roadmap-text").textContent); } catch (e) { return {}; } })();
  var DAY = 864e5, ROW = 40, LANE_ROW = 36;
  var ZOOMS = { week: 34, month: 9, quarter: 3.2, year: 1.15 };
  var LANG = d.documentElement.lang || undefined;

  function t(key, vars) {
    var s = TEXT[key] || key;
    if (vars) Object.keys(vars).forEach(function (k) { s = s.split("%(" + k + ")s").join(vars[k]); });
    return s;
  }
  function toast(msg, tone, act) { if (window.Work && Work.toast) Work.toast(msg, tone, act); }
  function dayOf(iso) { if (!iso) return null; var p = iso.split("-"); return Math.round(Date.UTC(+p[0], +p[1] - 1, +p[2]) / DAY); }
  function isoOf(n) { return new Date(n * DAY).toISOString().slice(0, 10); }
  var fmtShort = new Intl.DateTimeFormat(LANG, { day: "numeric", month: "short", timeZone: "UTC" });
  var fmtLong = new Intl.DateTimeFormat(LANG, { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
  var fmtMonth = new Intl.DateTimeFormat(LANG, { month: "short", timeZone: "UTC" });
  var fmtMonthYear = new Intl.DateTimeFormat(LANG, { month: "long", year: "numeric", timeZone: "UTC" });
  function show(iso, long) { return iso ? (long ? fmtLong : fmtShort).format(new Date(dayOf(iso) * DAY)) : ""; }
  function typing(e) { var el = e.target; return el && (el.closest("input, textarea, select, [contenteditable=true]")); }
  function hm(min) { if (!min) return ""; return min >= 60 ? t("hours", { h: (Math.round(min / 6) / 10).toString() }) : t("minutes", { m: min }); }
  function keep(key, value) { try { if (value === undefined) return JSON.parse(localStorage.getItem(key)); localStorage.setItem(key, JSON.stringify(value)); } catch (e) { return null; } }

  document.addEventListener("alpine:init", function () {
    Alpine.data("roadmapPage", function (initial) {
      var KEY = "rmp:" + initial.roadmap.id + ":";
      var saved = keep(KEY + "ui") || {};
      return {
        rm: initial.roadmap, lanes: initial.lanes, items: initial.items, goals: initial.goals, projects: initial.projects,
        momentum: initial.momentum, todayIso: initial.today, today: dayOf(initial.today),
        view: saved.view || "timeline", zoom: saved.zoom || "month", boardBy: saved.boardBy || "horizon",
        q: "", fLane: "", fStatus: "", fHealth: "", hideDone: !!saved.hideDone, collapsed: saved.collapsed || {},
        sortKey: "start", sortDir: 1,
        sel: null, detail: { tasks: [], updates: [] }, loading: false, state: "saved",
        adding: false, draft: { title: "", lane: "", kind: "item", start: "", end: "" },
        lanesOpen: false, newLane: "", taskText: "", search: "", found: [], searching: false, linkOpen: false,
        upHealth: "", upText: "", descPreview: true, dragId: null, dragOver: "", texts: TEXT,

        init: function () {
          var self = this;
          ["view", "zoom", "boardBy", "hideDone", "collapsed"].forEach(function (k) { self.$watch(k, function () { self.remember(); }); });
          var asked = new URLSearchParams(location.search).get("item");
          if (asked) this.open(+asked);
          this.$nextTick(function () { self.goToday(true); });
          this.$watch("zoom", function () { self.$nextTick(function () { self.goToday(true); }); });
          this.$watch("view", function (v) { if (v === "timeline") self.$nextTick(function () { self.goToday(true); }); });
          window.addEventListener("keydown", function (e) { self.key(e); });
          window.addEventListener("popstate", function () { var id = +new URLSearchParams(location.search).get("item"); if (id) self.open(id, true); else self.sel = null; });
        },
        remember: function () { keep(KEY + "ui", { view: this.view, zoom: this.zoom, boardBy: this.boardBy, hideDone: this.hideDone, collapsed: this.collapsed }); },

        /* ── Saving ─────────────────────────────────────────────── */
        post: function (url, data) {
          var self = this;
          this.state = "saving";
          return Work.api(url, data).then(function (res) {
            self.state = res && (res.ok || res.queued) ? "saved" : "error";
            if (res && !res.ok && !res.queued && res.error) toast(res.error, "warn");
            return res || {};
          });
        },
        itemUrl: function (id) { return "/work/api/roadmap-items/" + id + "/"; },
        rmUrl: function () { return "/work/api/roadmaps/" + this.rm.id + "/"; },
        put: function (item) {
          var i = this.items.findIndex(function (x) { return x.id === item.id; });
          if (i >= 0) this.items.splice(i, 1, item); else this.items.push(item);
        },
        save: function (it, fields) {
          var self = this, before = JSON.parse(JSON.stringify(it));
          Object.keys(fields).forEach(function (k) { if (k !== "deps") it[k] = fields[k]; });   // shown at once
          var data = Object.assign({ action: "save" }, fields);
          if (Array.isArray(data.deps)) data.deps = data.deps.join(",");
          ["lane", "goal", "project", "progress", "impact", "effort"].forEach(function (k) { if (k in data && data[k] == null) data[k] = ""; });
          return this.post(this.itemUrl(it.id), data).then(function (res) {
            if (res.ok && res.item) self.put(res.item);
            else if (!res.queued) self.put(before);
            return res;
          });
        },
        stateText: function () { return this.state === "saving" ? t("saving") : this.state === "error" ? t("notSaved") : t("saved"); },
        saveRoadmap: function (fields) {
          Object.assign(this.rm, fields);
          if (fields.title !== undefined) d.title = fields.title + " | " + d.title.split(" | ").slice(1).join(" | ");
          return this.post(this.rmUrl(), Object.assign({ action: "save" }, fields));
        },
        roadmapAction: function (action) {
          var self = this;
          if (action === "delete" && !this.sure) {
            FT.ask({ message: t("deleteRoadmap"), danger: true, after: "back" }).then(function (yes) { if (yes) { self.sure = true; self.roadmapAction(action); self.sure = false; } });
            return;
          }
          this.post(this.rmUrl(), { action: action }).then(function (res) {
            if (!res.ok) return;
            if (action === "archive") { self.rm.archived = res.archived; toast(res.archived ? t("archived") : t("unarchived")); }
            else if (res.url) location.href = res.url;
          });
        },

        /* ── What's shown ───────────────────────────────────────── */
        health: function (it) { return it.health || it.auto || ""; },
        lane: function (id) { return this.lanes.find(function (l) { return l.id === id; }) || null; },
        colorOf: function (it) { var l = this.lane(it.lane); return it.color || (l ? l.color : "slate"); },
        item: function (id) { return this.items.find(function (x) { return x.id === id; }) || null; },
        get current() { return this.sel ? this.item(this.sel) : null; },
        get filtering() { return !!(this.q || this.fLane || this.fStatus || this.fHealth); },
        clearFilters: function () { this.q = ""; this.fLane = ""; this.fStatus = ""; this.fHealth = ""; },
        get shown() {
          var q = this.q.trim().toLowerCase(), self = this;
          return this.items.filter(function (it) {
            if (self.hideDone && (it.status === "done" || it.status === "dropped") && self.view !== "board") return false;
            if (q && (it.title + " " + it.description).toLowerCase().indexOf(q) < 0) return false;
            if (self.fLane && String(it.lane || "none") !== self.fLane) return false;
            if (self.fStatus && it.status !== self.fStatus) return false;
            if (self.fHealth && self.health(it) !== self.fHealth) return false;
            return true;
          });
        },
        get summary() {
          var live = this.items.filter(function (i) { return i.status !== "dropped"; }), self = this, s = { on_track: 0, at_risk: 0, off_track: 0 };
          live.forEach(function (i) { var h = self.health(i); if (i.status !== "done" && s[h] !== undefined) s[h]++; });
          var next = live.filter(function (i) { return i.kind === "milestone" && i.status !== "done" && i.end && i.end >= self.todayIso; })
            .sort(function (a, b) { return a.end < b.end ? -1 : 1; })[0] || null;
          return Object.assign(s, {
            progress: live.length ? Math.round(live.reduce(function (a, i) { return a + i.progress; }, 0) / live.length) : 0,
            count: live.length, done: live.filter(function (i) { return i.status === "done"; }).length,
            active: live.filter(function (i) { return i.status === "active"; }).length,
            minutes: this.items.reduce(function (a, i) { return a + (i.minutes || 0); }, 0), next: next,
            nextIn: next ? dayOf(next.end) - this.today : null,
          });
        },
        get pace() { var top = Math.max.apply(null, this.momentum.map(function (w) { return w.done; }).concat([1])); return this.momentum.map(function (w) { return Object.assign({ h: Math.round(100 * w.done / top) }, w); }); },
        weekTip: function (w) { return t("week", { date: show(w.week) }) + " · " + t("doneTasks", { n: w.done }) + (w.minutes ? " · " + hm(w.minutes) : ""); },
        hm: hm, show: show,
        when: function (it) {
          if (!it.end) return t("noDates");
          if (it.kind === "milestone" || it.start === it.end) return show(it.end, true);
          return show(it.start) + " – " + show(it.end, true);
        },
        left: function (it) {
          if (!it.end || it.status === "done" || it.status === "dropped") return "";
          var n = dayOf(it.end) - this.today;
          if (n < 0) return n === -1 ? t("dayLate") : t("daysLate", { n: -n });
          if (n === 0) return t("dueToday");
          return n === 1 ? t("dayLeft") : t("daysLeft", { n: n });
        },
        lateBy: function (it) { return it.end && it.status !== "done" && it.status !== "dropped" && dayOf(it.end) < this.today; },
        likelyText: function (it) {
          if (!it.likely) return it.tasks.open && it.status !== "done" ? t("noPace") : "";
          var over = it.end ? dayOf(it.likely) - dayOf(it.end) : 0;
          return over > 0 ? t("likelyLate", { date: show(it.likely, true), n: over }) : t("likely", { date: show(it.likely, true) });
        },
        fromText: function (it) {
          if (it.from === "tasks") return t("tasksOf", { done: it.tasks.done, total: it.tasks.total });
          if (it.from === "goal") return t("fromGoal");
          if (it.from === "done") return TEXT.statuses.done;
          return t("byHand");
        },
        conflicts: function (it) {
          var self = this;
          if (!it.start) return [];
          return it.deps.map(function (id) { return self.item(id); }).filter(function (dep) { return dep && dep.end && dep.end >= it.start && dep.status !== "done"; });
        },
        conflictText: function (dep) { return t("conflict", { title: dep.title }); },

        /* ── Timeline ───────────────────────────────────────────── */
        get ppd() { return ZOOMS[this.zoom] || ZOOMS.month; },
        get range() {
          var lo = this.today - 21, hi = this.today + (this.zoom === "week" ? 60 : this.zoom === "month" ? 150 : this.zoom === "quarter" ? 360 : 720);
          this.items.forEach(function (it) { if (it.start) lo = Math.min(lo, dayOf(it.start) - 14); if (it.end) hi = Math.max(hi, dayOf(it.end) + 30); });
          var first = new Date(lo * DAY);
          if (this.zoom === "week") lo -= (first.getUTCDay() + 6) % 7;                 // a Monday
          else lo = Math.round(Date.UTC(first.getUTCFullYear(), this.zoom === "year" ? 0 : this.zoom === "quarter" ? Math.floor(first.getUTCMonth() / 3) * 3 : first.getUTCMonth(), 1) / DAY);
          return { first: lo, days: hi - lo + 1 };
        },
        get width() { return Math.round(this.range.days * this.ppd); },
        x: function (iso) { return (dayOf(iso) - this.range.first) * this.ppd; },
        get todayX() { return (this.today - this.range.first) * this.ppd + this.ppd / 2; },
        get scale() {
          /* two rows: the bigger unit above (months, quarters, years), the smaller below (days, weeks, months) */
          var r = this.range, ppd = this.ppd, major = [], minor = [], z = this.zoom;
          for (var n = r.first; n < r.first + r.days; n++) {
            var dt = new Date(n * DAY), dom = dt.getUTCDate(), m = dt.getUTCMonth(), y = dt.getUTCFullYear(), x = (n - r.first) * ppd;
            if (z === "week" || z === "month") { if (dom === 1 || n === r.first) major.push({ x: x, label: fmtMonthYear.format(dt) }); }
            else if (z === "quarter") { if ((dom === 1 && m % 3 === 0) || n === r.first) major.push({ x: x, label: "Q" + (Math.floor(m / 3) + 1) + " " + y }); }
            else if ((dom === 1 && m === 0) || n === r.first) major.push({ x: x, label: String(y) });
            if (z === "week") minor.push({ x: x, w: ppd, label: String(dom), wk: dt.getUTCDay() === 0 || dt.getUTCDay() === 6, line: dt.getUTCDay() === 1 });
            else if (z === "month") { if (dt.getUTCDay() === 1) minor.push({ x: x, w: 7 * ppd, label: String(dom), line: true }); }
            else if (dom === 1) minor.push({ x: x, w: 30 * ppd, label: z === "year" ? fmtMonth.format(dt).slice(0, 3) : fmtMonth.format(dt), line: true });
          }
          return { major: major, minor: minor };
        },
        /* Lanes with their pieces of work, in rows; each row's y for the arrows. */
        get rows() {
          var out = [], y = 0, self = this, shown = this.shown;
          var groups = this.lanes.map(function (l) { return { lane: l, key: String(l.id) }; });
          if (shown.some(function (i) { return !i.lane; }) || !this.lanes.length) groups.push({ lane: null, key: "none" });
          groups.forEach(function (g) {
            var its = shown.filter(function (i) { return (i.lane || null) === (g.lane ? g.lane.id : null); })
              .sort(function (a, b) { return (a.start || "9999") < (b.start || "9999") ? -1 : (a.start || "9999") > (b.start || "9999") ? 1 : a.order - b.order; });
            if (self.filtering && !its.length) return;
            out.push({ type: "lane", key: "l" + g.key, lane: g.lane, laneKey: g.key, count: its.length, y: y,
                       pct: its.length ? Math.round(its.reduce(function (a, i) { return a + i.progress; }, 0) / its.length) : 0 });
            y += LANE_ROW;
            if (self.collapsed[g.key]) return;
            its.forEach(function (it) { out.push({ type: "item", key: "i" + it.id, it: it, laneKey: g.key, y: y }); y += ROW; });
          });
          return out;
        },
        get height() { var r = this.rows; return r.length ? r[r.length - 1].y + (r[r.length - 1].type === "lane" ? LANE_ROW : ROW) : 0; },
        bar: function (it) {
          if (!it.end) return null;
          var a = this.x(it.start || it.end), b = this.x(it.end) + this.ppd;
          if (it.kind === "milestone") return "left:" + (b - this.ppd / 2) + "px";
          return "left:" + a + "px;width:" + Math.max(b - a, 8) + "px";
        },
        get arrows() {
          var pos = {}, self = this, out = [];
          this.rows.forEach(function (r) { if (r.type === "item") pos[r.it.id] = r; });
          this.items.forEach(function (it) {
            var to = pos[it.id]; if (!to || !it.end) return;
            it.deps.forEach(function (id) {
              var from = pos[id]; if (!from || !from.it.end) return;
              var x1 = self.x(from.it.end) + self.ppd, y1 = from.y + ROW / 2, x2 = self.x(it.start || it.end), y2 = to.y + ROW / 2;
              if (it.kind === "milestone") x2 += self.ppd / 2 - 9;
              var bad = from.it.end >= (it.start || it.end) && from.it.status !== "done", mid = Math.max(x1 + 12, x2 - 12);
              out.push({ key: id + "-" + it.id, bad: bad, d: "M" + x1 + " " + y1 + " H" + mid + " V" + y2 + " H" + (x2 - 2) });
            });
          });
          return out;
        },
        narrow: function (it) {      // too short for its title: the title goes beside it
          var days = dayOf(it.end) - dayOf(it.start || it.end) + 1;
          return days * this.ppd < Math.min(it.title.length * 6.5 + 44, 160);
        },
        get arrowsSvg() {          // (Alpine can't loop inside an <svg>, so the paths are written out)
          return this.arrows.map(function (a) {
            return '<path d="' + a.d + '"' + (a.bad ? ' class="is-bad" marker-end="url(#rmp-arrow-bad)"' : ' marker-end="url(#rmp-arrow)"') + "/>";
          }).join("");
        },
        goToday: function (quiet) {
          var box = this.$refs.scroll; if (!box) return;
          box.scrollTo({ left: Math.max(this.todayX - box.clientWidth * 0.3, 0), behavior: quiet ? "auto" : "smooth" });
        },
        zoomBy: function (n) { var z = ["week", "month", "quarter", "year"], i = z.indexOf(this.zoom) + n; if (i >= 0 && i < z.length) this.zoom = z[i]; },
        toggleLane: function (key) { this.collapsed[key] = !this.collapsed[key]; this.collapsed = Object.assign({}, this.collapsed); },
        trackDblClick: function (e, laneKey) {
          if (e.target.closest(".rmp-bar, .rmp-ms, button")) return;
          var box = e.currentTarget.getBoundingClientRect(), n = this.range.first + Math.floor((e.clientX - box.left) / this.ppd);
          this.newItem({ lane: laneKey === "none" ? "" : laneKey, start: isoOf(n), end: isoOf(n + (this.zoom === "week" ? 6 : 13)) });
        },
        schedule: function (it) {
          var a = this.today, b = a + 13;
          this.save(it, it.kind === "milestone" ? { end: isoOf(a + 14) } : { start: isoOf(a), end: isoOf(b) });
          toast(t("scheduled"));
        },
        /* Drag a bar: the middle moves it, the ends change the start or the end. Day by day. */
        grab: function (e, it, edge) {
          if (e.button > 0 || !it.end) return;
          if (e.pointerType === "touch" && edge === "move") return;     // a finger scrolls; its ends still resize
          e.preventDefault(); e.stopPropagation();
          var self = this, el = e.target.closest(".rmp-bar, .rmp-ms"), x0 = e.clientX, n = 0, moved = false, ppd = this.ppd;
          var span = dayOf(it.end) - dayOf(it.start || it.end), left0 = el.offsetLeft, w0 = el.offsetWidth;
          el.setPointerCapture(e.pointerId);
          var tip = d.createElement("span"); tip.className = "rmp-dragtip";
          function where() {
            var a = dayOf(it.start || it.end), b = dayOf(it.end);
            if (edge === "move") { a += n; b += n; } else if (edge === "start") a += n; else b += n;
            return { a: a, b: b };
          }
          function move(ev) {
            var k = Math.round((ev.clientX - x0) / ppd);
            if (edge === "start") k = Math.min(k, span); if (edge === "end") k = Math.max(k, -span);
            if (Math.abs(ev.clientX - x0) > 3 && !moved) { moved = true; el.classList.add("is-dragging"); el.appendChild(tip); }
            if (k === n) return; n = k;
            if (edge === "move" || edge === "start") el.style.left = (left0 + n * ppd) + "px";
            if (edge === "start") el.style.width = (w0 - n * ppd) + "px";
            if (edge === "end") el.style.width = (w0 + n * ppd) + "px";
            var w = where(); tip.textContent = it.kind === "milestone" ? show(isoOf(w.b)) : show(isoOf(w.a)) + " – " + show(isoOf(w.b));
          }
          function up() {
            el.removeEventListener("pointermove", move); el.removeEventListener("pointerup", up); el.removeEventListener("pointercancel", up);
            el.classList.remove("is-dragging"); tip.remove(); el.style.left = ""; el.style.width = "";
            if (!moved) { self.open(it.id); return; }
            self.swallow = true; setTimeout(function () { self.swallow = false; }, 0);
            if (!n) return;
            var w = where();
            self.save(it, it.kind === "milestone" ? { end: isoOf(w.b) } : { start: isoOf(w.a), end: isoOf(w.b) });
          }
          el.addEventListener("pointermove", move); el.addEventListener("pointerup", up); el.addEventListener("pointercancel", up);
        },
        barKey: function (e, it) {        // keyboard: ← → move a day, Shift moves a week, Alt changes the end
          if (["ArrowLeft", "ArrowRight"].indexOf(e.key) < 0 || !it.end) return;
          e.preventDefault();
          var n = (e.key === "ArrowLeft" ? -1 : 1) * (e.shiftKey ? 7 : 1);
          if (e.altKey && it.kind !== "milestone") { if (dayOf(it.end) + n >= dayOf(it.start)) this.save(it, { end: isoOf(dayOf(it.end) + n) }); }
          else if (it.kind === "milestone") this.save(it, { end: isoOf(dayOf(it.end) + n) });
          else this.save(it, { start: isoOf(dayOf(it.start) + n), end: isoOf(dayOf(it.end) + n) });
        },

        /* ── Board and priorities: drag a card to another column ── */
        get columns() {
          var by = this.boardBy, self = this, keys = by === "horizon" ? ["now", "next", "later"] : ["idea", "planned", "active", "done"];
          var names = by === "horizon" ? TEXT.horizons : TEXT.statuses;
          return keys.map(function (k) {
            var its = self.shown.filter(function (i) {
              if (by === "horizon") return i.horizon === k && (!self.hideDone || (i.status !== "done" && i.status !== "dropped"));
              return i.status === k;
            }).sort(function (a, b) { return a.order - b.order; });
            return { key: k, label: names[k], items: its };
          });
        },
        get quadrants() {
          var self = this, its = this.shown.filter(function (i) { return i.status !== "done" && i.status !== "dropped"; });
          var q = function (hiV, hiE) { return its.filter(function (i) { return i.impact && i.effort && (i.impact >= 3) === hiV && (i.effort >= 3) === hiE; })
            .sort(function (a, b) { return (b.impact / b.effort) - (a.impact / a.effort); }); };
          return { scored: [
            { key: "quick", label: t("quickWins"), hint: TEXT.quickHint, items: q(true, false), v: 4, e: 2 },
            { key: "big", label: t("bigBets"), hint: TEXT.bigHint, items: q(true, true), v: 4, e: 4 },
            { key: "fill", label: t("fillIns"), hint: TEXT.fillHint, items: q(false, false), v: 2, e: 2 },
            { key: "sink", label: t("timeSinks"), hint: TEXT.sinkHint, items: q(false, true), v: 2, e: 4 },
          ], unscored: its.filter(function (i) { return !i.impact || !i.effort; }) };
        },
        dragStart: function (e, it) { this.dragId = it.id; e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", String(it.id)); },
        dragEnd: function () { this.dragId = null; this.dragOver = ""; },
        dropOn: function (e, col, before) {
          var it = this.item(this.dragId); this.dragOver = ""; this.dragId = null;
          if (!it) return;
          var list = col.items.filter(function (i) { return i.id !== it.id; }), idx = before ? list.findIndex(function (i) { return i.id === before; }) : list.length;
          if (idx < 0) idx = list.length;
          var prev = list[idx - 1], next = list[idx];
          var order = prev && next ? (prev.order + next.order) / 2 : prev ? prev.order + 1 : next ? next.order - 1 : 1;
          var fields = { order: order };
          if (col.v) {            // a quadrant: only the side that changed
            if (!it.impact || (it.impact >= 3) !== (col.v >= 3)) fields.impact = col.v;
            if (!it.effort || (it.effort >= 3) !== (col.e >= 3)) fields.effort = col.e;
          } else fields[this.boardBy === "horizon" ? "horizon" : "status"] = col.key;
          var where = col.label;
          this.save(it, fields);
          if (col.key !== (this.boardBy === "horizon" ? it.horizon : it.status)) toast(t("moved", { where: where }));
        },

        /* ── List ───────────────────────────────────────────────── */
        sortBy: function (k) { if (this.sortKey === k) this.sortDir = -this.sortDir; else { this.sortKey = k; this.sortDir = 1; } },
        get sorted() {
          var k = this.sortKey, dir = this.sortDir, self = this;
          var val = function (i) {
            if (k === "lane") { var l = self.lane(i.lane); return l ? l.order : 1e9; }
            if (k === "health") return { off_track: 0, at_risk: 1, on_track: 2 }[self.health(i)] !== undefined ? { off_track: 0, at_risk: 1, on_track: 2 }[self.health(i)] : 3;
            if (k === "status") return ["active", "planned", "idea", "done", "dropped"].indexOf(i.status);
            if (k === "start" || k === "end") return i[k] || "9999";
            if (k === "title") return i.title.toLowerCase();
            if (k === "tasks") return i.tasks.total;
            return i[k] == null ? -1 : i[k];
          };
          return this.shown.slice().sort(function (a, b) { var x = val(a), y = val(b); return (x < y ? -1 : x > y ? 1 : a.order - b.order) * dir; });
        },

        /* ── New pieces of work ────────────────────────────────── */
        newItem: function (pre) {
          pre = pre || {};
          var lane = pre.lane !== undefined ? pre.lane : (this.fLane && this.fLane !== "none" ? this.fLane : (this.lanes[0] ? String(this.lanes[0].id) : ""));
          var undated = pre.horizon && pre.horizon !== "now";       // added to Next or Later on the board: no dates yet
          this.draft = { title: "", lane: String(lane || ""), kind: pre.kind || "item", horizon: pre.horizon || "", status: pre.status || "",
                         start: undated ? "" : (pre.start || this.todayIso), end: undated ? "" : (pre.end || isoOf(this.today + (pre.kind === "milestone" ? 14 : 13))) };
          this.adding = true;
          var self = this; this.$nextTick(function () { self.$refs.draftTitle && self.$refs.draftTitle.focus(); });
        },
        create: function () {
          var self = this, dr = this.draft;
          if (!dr.title.trim()) { this.$refs.draftTitle.focus(); return; }
          var data = { action: "item_add", title: dr.title.trim(), lane: dr.lane, kind: dr.kind, end: dr.end || "", start: dr.kind === "milestone" ? "" : (dr.start || ""),
                       horizon: dr.horizon || (dr.start && dayOf(dr.start) <= this.today ? "now" : dr.end || dr.start ? "next" : "later") };
          if (dr.status) data.status = dr.status;
          if (dr.start && dr.end && dr.start > dr.end && dr.kind !== "milestone") { data.start = dr.end; data.end = dr.start; }
          this.post(this.rmUrl(), data).then(function (res) {
            if (!res.ok) return;
            self.items.push(res.item); self.adding = false;
            toast(t("saved"));
            if (self.view === "timeline") self.$nextTick(function () { var el = d.querySelector('[data-item="' + res.item.id + '"]'); if (el) el.scrollIntoView({ block: "nearest", inline: "center", behavior: "smooth" }); });
          });
        },

        /* ── The side panel ─────────────────────────────────────── */
        open: function (id, fromHistory) {
          if (this.swallow || !this.item(id)) return;
          var self = this; this.sel = id; this.detail = { tasks: [], updates: [] }; this.loading = true; this.found = []; this.search = ""; this.linkOpen = false;
          this.upHealth = ""; this.upText = ""; this.descPreview = true;
          if (!fromHistory) { var u = new URL(location.href); u.searchParams.set("item", id); history.replaceState(null, "", u); }
          fetch(this.itemUrl(id), { credentials: "same-origin", headers: { "X-Requested-With": "XMLHttpRequest" } })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (res) { if (res && self.sel === id) { self.detail = res; } self.loading = false; })
            .catch(function () { self.loading = false; });
        },
        close: function () {
          this.sel = null;
          var u = new URL(location.href); u.searchParams.delete("item"); history.replaceState(null, "", u);
        },
        step: function (n) {           // the next or the one before, in the order shown
          var list = this.view === "list" ? this.sorted : this.rows.filter(function (r) { return r.type === "item"; }).map(function (r) { return r.it; });
          if (this.view === "board") list = [].concat.apply([], this.columns.map(function (c) { return c.items; }));
          var sel = this.sel, i = list.findIndex(function (x) { return x.id === sel; });
          var next = list[i + n]; if (next) this.open(next.id);
        },
        removeItem: function (it) {
          var self = this;
          FT.ask({ message: t("deleteItem", { title: it.title }), danger: true, after: "back" }).then(function (yes) { if (yes) self.dropItem(it); });
        },
        dropItem: function (it) {
          var self = this;
          this.post(this.itemUrl(it.id), { action: "delete" }).then(function (res) {
            if (!res.ok) return;
            self.items = self.items.filter(function (x) { return x.id !== it.id; });
            self.items.forEach(function (x) { x.deps = x.deps.filter(function (dd) { return dd !== it.id; }); });
            self.close();
            Work.undoable(t("itemDeleted", { title: it.title }), res.undo);
          });
        },
        duplicate: function (it) {
          var self = this;
          this.post(this.itemUrl(it.id), { action: "duplicate" }).then(function (res) { if (res.ok) { self.items.push(res.item); self.open(res.item.id); toast(t("dupDone")); } });
        },
        setDeps: function (it, ids) { this.save(it, { deps: ids }); },
        addDep: function (it, id) { id = +id; if (id && it.deps.indexOf(id) < 0) this.setDeps(it, it.deps.concat([id])); },
        dropDep: function (it, id) { this.setDeps(it, it.deps.filter(function (x) { return x !== id; })); },
        depOptions: function (it) { return this.items.filter(function (x) { return x.id !== it.id && it.deps.indexOf(x.id) < 0; }); },
        waitingOnThis: function (it) { return this.items.filter(function (x) { return x.deps.indexOf(it.id) >= 0; }); },
        /* its tasks */
        taskDo: function (action, data) {
          var self = this, id = this.sel;
          return this.post(this.itemUrl(id), Object.assign({ action: action }, data)).then(function (res) {
            if (res.ok && res.item) self.put(res.item);
            return res;
          });
        },
        addTask: function () {
          var self = this, text = this.taskText.trim(); if (!text) return;
          this.taskDo("task_add", { title: text }).then(function (res) { if (res.ok) { self.detail.tasks.unshift(res.task); self.taskText = ""; } });
        },
        tickTask: function (task) {
          var self = this, done = !task.done;
          task.done = done;
          this.taskDo("task_done", { task: task.id, done: done ? "1" : "0" }).then(function (res) { if (!res.ok) task.done = !done; else Object.assign(task, res.task); if (res.ok && self.current && self.current.tasks.open === 0 && self.current.tasks.total && self.current.status !== "done") toast(t("allDone"), "good", { label: TEXT.statuses.done, run: function () { self.save(self.current, { status: "done" }); } }); });
        },
        unlinkTask: function (task) {
          var self = this;
          this.taskDo("task_unlink", { task: task.id }).then(function (res) { if (res.ok) { self.detail.tasks = self.detail.tasks.filter(function (x) { return x.id !== task.id; }); toast(t("unlinked")); } });
        },
        findTasks: function () {
          var self = this, q = this.search;
          this.searching = true;
          Work.ask(this.itemUrl(this.sel), { action: "task_search", q: q }).then(function (res) { self.searching = false; if (res && res.ok && q === self.search) self.found = res.tasks; });
        },
        linkTask: function (task) {
          var self = this;
          this.taskDo("task_link", { task: task.id }).then(function (res) {
            if (res.ok) { self.detail.tasks.unshift(res.task); self.found = self.found.filter(function (x) { return x.id !== task.id; }); toast(t("linked")); }
          });
        },
        /* its updates */
        postUpdate: function () {
          var self = this;
          this.taskDo("update", { health: this.upHealth, text: this.upText }).then(function (res) {
            if (res.ok) { self.detail.updates.unshift(res.update); self.upText = ""; self.upHealth = ""; toast(t("updatePosted")); }
          });
        },
        dropUpdate: function (u) {
          var self = this;
          this.taskDo("update_delete", { update: u.id }).then(function (res) { if (res.ok) self.detail.updates = self.detail.updates.filter(function (x) { return x.id !== u.id; }); });
        },
        ago: function (iso) {
          var s = (Date.now() - new Date(iso).getTime()) / 1000, rtf = new Intl.RelativeTimeFormat(LANG, { numeric: "auto" });
          if (s < 60) return rtf.format(0, "second");
          if (s < 3600) return rtf.format(-Math.round(s / 60), "minute");
          if (s < 86400) return rtf.format(-Math.round(s / 3600), "hour");
          if (s < 86400 * 30) return rtf.format(-Math.round(s / 86400), "day");
          return fmtLong.format(new Date(iso));
        },
        md: function (text) { return window.Work && Work.markdown ? Work.markdown(text || "") : ""; },

        /* ── Lanes ──────────────────────────────────────────────── */
        addLane: function () {
          var self = this, name = this.newLane.trim(); if (!name) return;
          var colors = Object.keys(TEXT.colors), color = colors[(this.lanes.length * 3 + 1) % colors.length];
          this.post(this.rmUrl(), { action: "lane_add", name: name, color: color }).then(function (res) { if (res.ok) { self.lanes.push(res.lane); self.newLane = ""; } });
        },
        saveLane: function (lane, fields) {
          Object.assign(lane, fields);
          this.post(this.rmUrl(), Object.assign({ action: "lane_save", lane: lane.id }, fields));
        },
        moveLane: function (lane, n) {
          var i = this.lanes.indexOf(lane), j = i + n; if (j < 0 || j >= this.lanes.length) return;
          var other = this.lanes[j], a = lane.order, b = other.order;
          if (a === b) { a = i; b = j; }
          this.lanes.splice(i, 1); this.lanes.splice(j, 0, lane);
          this.saveLane(lane, { order: b }); this.saveLane(other, { order: a });
        },
        deleteLane: function (lane) {
          var self = this;
          FT.ask({ message: t("deleteLane", { name: lane.name }), danger: true, after: "gone" }).then(function (yes) { if (yes) self.dropLane(lane); });
        },
        dropLane: function (lane) {
          var self = this;
          this.post(this.rmUrl(), { action: "lane_delete", lane: lane.id }).then(function (res) {
            if (!res.ok) return;
            self.lanes = self.lanes.filter(function (l) { return l.id !== lane.id; });
            self.items.forEach(function (i) { if (i.lane === lane.id) i.lane = null; });
            toast(t("laneDeleted"));
          });
        },

        /* ── Keys ───────────────────────────────────────────────── */
        key: function (e) {
          if (e.ctrlKey || e.metaKey || e.defaultPrevented) return;
          if (e.key === "Escape") {
            if (this.adding) { this.adding = false; e.preventDefault(); return; }
            if (this.lanesOpen) { this.lanesOpen = false; e.preventDefault(); return; }
            if (this.sel && !typing(e)) { this.close(); e.preventDefault(); }
            return;
          }
          if (typing(e) || e.altKey || this.adding || this.lanesOpen) return;
          var k = e.key, views = { 1: "timeline", 2: "board", 3: "list", 4: "matrix" };
          if (views[k]) { this.view = views[k]; e.preventDefault(); }
          else if (k === "n") { this.newItem(); e.preventDefault(); }
          else if (k === "m") { this.newItem({ kind: "milestone" }); e.preventDefault(); }
          else if (k === "t" && this.view === "timeline") { this.goToday(); e.preventDefault(); }
          else if (k === "f") { var s = this.$refs.q; if (s) { s.focus(); e.preventDefault(); } }
          else if ((k === "+" || k === "=") && this.view === "timeline") { this.zoomBy(-1); e.preventDefault(); }
          else if (k === "-" && this.view === "timeline") { this.zoomBy(1); e.preventDefault(); }
          else if (this.sel && (k === "j" || k === "ArrowDown")) { this.step(1); e.preventDefault(); }
          else if (this.sel && (k === "k" || k === "ArrowUp")) { this.step(-1); e.preventDefault(); }
        },
      };
    });
  });
})();
