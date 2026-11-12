/* Timers, the stopwatch, ringing and ticking — on every Productivity page (after work.js), as Google Clock and
   Apple's Clock app have them:

   - Timers: as many as you like, each with its own label; started from a preset or a time typed in; pause, +1 min,
     start again, delete. They go on while you use other pages, and after a reload (kept on this device).
   - The stopwatch: start, stop, laps (the fastest and slowest marked), reset — kept on this device too.
   - Ringing (Work.ring): a finished timer, focus session or break plays its sound once, three times or until
     stopped (settings), with a "Time's up" card over any page: Stop, +1 min. Only one tab rings; Stop stops them all.
   - Ticking: a clock's tick-tock while a focus session runs, on the focus page or on every page (settings).
   - The page's title shows the time left (⏲ a timer, ⏱ the stopwatch), and the screen stays on while something
     runs on the focus page (phones).

   Times are kept as "ends at" moments, not counted down, so a tab asleep in the background is never behind. */
(function () {
  "use strict";
  var d = document, W = window.Work;
  if (!W) return;
  var CFG = W.cfg, ME = d.documentElement.getAttribute("data-user") || "0";
  function T(key, fallback) { return (CFG.text || {})[key] || fallback; }
  function load(key, fallback) { var v = W.recall(key, null); return v == null ? fallback : v; }
  function uid() { return Date.now().toString(36) + Math.random().toString(36).slice(2, 6); }
  function pad(n) { return (n < 10 ? "0" : "") + n; }
  // 1:05:09, 4:32 — and for the stopwatch 4:32.07
  function fmt(sec, hundredths) {
    sec = Math.max(0, sec);
    var whole = Math.floor(sec + (hundredths ? 0 : 0.999)), h = Math.floor(whole / 3600), m = Math.floor(whole % 3600 / 60), s = whole % 60;
    var out = (h ? h + ":" + pad(m) : m) + ":" + pad(s);
    return hundredths ? out + "." + pad(Math.floor((sec * 100) % 100)) : out;
  }
  var chan = ("BroadcastChannel" in window) ? new BroadcastChannel("work-clock:" + ME) : null;
  function tell(msg) { if (chan) chan.postMessage(msg); }
  function once(name, fn) {           // one tab does it (Web Locks), the others follow from storage
    if (navigator.locks && navigator.locks.request) navigator.locks.request("work-clock:" + ME + ":" + name, { ifAvailable: true }, function (lock) { if (lock) fn(); });
    else fn();
  }

  /* ── Ringing ───────────────────────────────────────────────────────────── */
  var ringing = {};        // id → { stop() }
  function ringStop(id, quiet) {
    var r = ringing[id];
    if (r) { clearInterval(r.timer); delete ringing[id]; }
    var st = window.Alpine && Alpine.store("ring");
    if (st) st.items = st.items.filter(function (x) { return x.id !== id; });
    if (!quiet) tell({ ringStop: id });
  }
  /* Work.ring(id, { title, text, sound, icon, snooze() }): plays `sound` (once, 3 times or until stopped — CFG.ring)
     and shows a card with Stop (and +1 min when there's a snooze) until it's stopped or the ringing is over. */
  W.ring = function (id, o) {
    o = o || {};
    var times = CFG.ring == null ? 1 : +CFG.ring, played = 0, sound = o.sound;
    ringStop(id, true);
    var play = function () {
      if (sound) W.play(sound);
      if (navigator.vibrate) try { navigator.vibrate([250, 120, 250]); } catch (e) { /* not on this device */ }
      played++;
      if (times && played >= times && ringing[id]) { clearInterval(ringing[id].timer); ringing[id].timer = null; }
    };
    if (times === 1 && !o.keep) { play(); W.toast((o.icon ? o.icon + " " : "") + o.title + (o.text ? " — " + o.text : ""), "warn",
                                                  o.snooze ? { label: T("plusMinute", "+1 min"), run: o.snooze } : null); return; }
    ringing[id] = { timer: setInterval(play, W.ringGap) };
    play();
    var st = window.Alpine && Alpine.store("ring");
    if (st) st.items = st.items.filter(function (x) { return x.id !== id; }).concat([{ id: id, title: o.title, text: o.text || "", icon: o.icon || "⏰", canSnooze: !!o.snooze, snooze: o.snooze || null }]);
  };
  W.ringStop = ringStop;

  /* ── Timers ────────────────────────────────────────────────────────────── */
  var TKEY = "work-timers:" + ME, subs = [];
  function tLoad() { var x = load(TKEY, {}); return { list: x.list || [], recent: x.recent || [] }; }
  var TS = tLoad();
  function tSave() { W.store(TKEY, TS); subs.forEach(function (fn) { fn(); }); }
  function tLeft(t) { return t.running ? Math.max(0, (t.endsAt - Date.now()) / 1000) : t.left; }
  function find(id) { TS = tLoad(); return TS.list.filter(function (t) { return t.id === id; })[0]; }
  var Timers = {
    get list() { return TS.list; }, get recent() { return TS.recent; },
    left: tLeft,
    add: function (seconds, label) {
      seconds = Math.round(seconds);
      if (!(seconds > 0)) return null;
      TS = tLoad();
      var t = { id: uid(), label: (label || "").trim().slice(0, 60), total: seconds, left: seconds, running: true, endsAt: Date.now() + seconds * 1000, done: false };
      TS.list.unshift(t);
      TS.recent = [seconds].concat(TS.recent.filter(function (s) { return s !== seconds; })).slice(0, 6);      // the last few lengths, to start again in one tap
      tSave(); W.askNotify();
      return t;
    },
    toggle: function (id) {
      var t = find(id); if (!t) return;
      if (t.done) { return Timers.restart(id); }
      if (t.running) { t.left = tLeft(t); t.running = false; } else { t.running = true; t.endsAt = Date.now() + t.left * 1000; }
      tSave();
    },
    plus: function (id, seconds) {
      var t = find(id); if (!t) return;
      ringStop("timer-" + id);
      if (t.done) { t.done = false; t.left = 0; t.running = true; t.endsAt = Date.now(); t.total = 0; }
      if (t.running) t.endsAt += seconds * 1000; else t.left += seconds;
      t.total += seconds;
      tSave();
    },
    restart: function (id) {
      var t = find(id); if (!t) return;
      ringStop("timer-" + id);
      t.done = false; t.running = true; t.left = t.total; t.endsAt = Date.now() + t.total * 1000;
      tSave();
    },
    remove: function (id) {
      ringStop("timer-" + id);
      TS = tLoad(); var gone = TS.list.filter(function (t) { return t.id === id; })[0];
      TS.list = TS.list.filter(function (t) { return t.id !== id; }); tSave();
      return gone;
    },
    putBack: function (t) { TS = tLoad(); TS.list.unshift(t); tSave(); },
    rename: function (id, label) { var t = find(id); if (!t) return; t.label = (label || "").trim().slice(0, 60); tSave(); },
    clearDone: function () { TS = tLoad(); TS.list.forEach(function (t) { if (t.done) ringStop("timer-" + t.id); }); TS.list = TS.list.filter(function (t) { return !t.done; }); tSave(); },
    subscribe: function (fn) { subs.push(fn); },
  };
  function timerDone(t, late) {
    t.running = false; t.left = 0; t.done = true; tSave();
    var name = t.label || T("timer", "Timer");
    if (late) { W.toast("⏲ " + name + " — " + T("timerEndedAway", "it ended while the app was closed."), ""); return; }
    W.ring("timer-" + t.id, { title: name, text: T("timesUp", "Time's up"), sound: CFG.timerSound, icon: "⏲",
                             snooze: function () { Timers.plus(t.id, 60); } });
    if (d.hidden) W.notify("⏲ " + name, T("timesUp", "Time's up"), CFG.urls.focus_page + "?tab=timers", "timer-" + t.id);     // (in sight: the card says it)
  }
  function checkTimers() {
    TS = tLoad();
    TS.list.forEach(function (t) {
      if (t.running && Date.now() >= t.endsAt) {
        var late = Date.now() - t.endsAt > 60000;
        once("timer-" + t.id, function () { var now = find(t.id); if (now && now.running && Date.now() >= now.endsAt) timerDone(now, late); });
      }
    });
  }

  /* ── The stopwatch ─────────────────────────────────────────────────────── */
  var SKEY = "work-stopwatch:" + ME;
  function sLoad() { var x = load(SKEY, {}); return { running: !!x.running, startedAt: x.startedAt || 0, base: x.base || 0, laps: x.laps || [] }; }
  var SW = sLoad();
  function sSave() { W.store(SKEY, SW); subs.forEach(function (fn) { fn(); }); }
  var Stopwatch = {
    get running() { return SW.running; }, get laps() { return SW.laps; },
    elapsed: function () { return (SW.base + (SW.running ? Date.now() - SW.startedAt : 0)) / 1000; },
    toggle: function () {
      SW = sLoad();
      if (SW.running) { SW.base += Date.now() - SW.startedAt; SW.running = false; } else { SW.running = true; SW.startedAt = Date.now(); }
      sSave();
    },
    lap: function () { SW = sLoad(); if (!SW.running) return; SW.laps.unshift(Math.round(Stopwatch.elapsed() * 1000)); sSave(); },
    reset: function () { SW = { running: false, startedAt: 0, base: 0, laps: [] }; sSave(); },
    // laps as rows: { n, lap (s), total (s), best, worst } — newest first, as Google Clock lists them
    rows: function () {
      var totals = SW.laps.slice().reverse(), rows = totals.map(function (ms, i) { return { n: i + 1, total: ms / 1000, lap: (ms - (i ? totals[i - 1] : 0)) / 1000 }; });
      if (rows.length > 2) {
        var laps = rows.map(function (r) { return r.lap; }), lo = Math.min.apply(null, laps), hi = Math.max.apply(null, laps);
        rows.forEach(function (r) { r.best = r.lap === lo; r.worst = r.lap === hi; });
      }
      return rows.reverse();
    },
  };

  window.addEventListener("storage", function (e) {
    if (e.key === TKEY) { TS = tLoad(); subs.forEach(function (fn) { fn(); }); }
    if (e.key === SKEY) { SW = sLoad(); subs.forEach(function (fn) { fn(); }); }
  });
  if (chan) chan.onmessage = function (e) { if (e.data && e.data.ringStop) ringStop(e.data.ringStop, true); };

  /* ── Every quarter second: finished timers, the ticking, the page's title, the screen kept on ── */
  var TITLE = /^(?:🍅|☕|⏲️?|⏱️?) [^·]+ · /u, lastTick = -1, wake = null;
  function onClockPage() { return !!d.querySelector("[data-focus-page]"); }
  function anyRunning() { return TS.list.some(function (t) { return t.running; }) || SW.running || (W.focus && W.focus.state.running); }
  function keepAwake() {
    var want = onClockPage() && anyRunning() && !d.hidden && "wakeLock" in navigator;
    if (want && !wake) navigator.wakeLock.request("screen").then(function (l) { wake = l; l.addEventListener("release", function () { wake = null; }); }).catch(function () {});
    else if (!want && wake) { wake.release().catch(function () {}); wake = null; }
  }
  setInterval(function () {
    checkTimers();
    var F = W.focus && W.focus.state;
    // ticking: a running focus session, here or (if chosen) on every page, in the tab you're looking at
    if (CFG.tick && F && F.running && F.mode === "focus" && !d.hidden && (CFG.tickEverywhere || onClockPage())) {
      var sec = Math.ceil(W.focus.left());
      if (sec !== lastTick) { if (lastTick >= 0) W.tick(sec); lastTick = sec; }
    } else lastTick = -1;
    if (!F || !F.running) {        // (a running focus session has the title: work.js)
      var base = d.title.replace(TITLE, ""), next = TS.list.filter(function (t) { return t.running; }).sort(function (a, b) { return a.endsAt - b.endsAt; })[0];
      d.title = next ? "⏲ " + fmt(tLeft(next)) + " · " + base : SW.running ? "⏱ " + fmt(Stopwatch.elapsed()) + " · " + base : base;
    }
    keepAwake();
  }, 250);
  d.addEventListener("visibilitychange", function () { if (!d.hidden) { TS = tLoad(); SW = sLoad(); checkTimers(); subs.forEach(function (fn) { fn(); }); } keepAwake(); });

  window.Clock = { timers: Timers, stopwatch: Stopwatch, fmt: fmt, tab: function () { var p = d.querySelector("[data-clock-tab]"); return p ? p.getAttribute("data-clock-tab") : "focus"; } };

  document.addEventListener("alpine:init", function () {
    function typing(e) { var el = e.target; return !!(el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName))); }

    /* The page: Focus | Timers | Stopwatch (?tab=… or the one last open). 1 2 3 switch. */
    Alpine.data("clockPage", function () {
      var from = new URLSearchParams(location.search).get("tab");
      return {
        tab: ["focus", "timers", "stopwatch"].indexOf(from) >= 0 ? from : (W.recall("work-clock-tab", "focus") || "focus"),
        init: function () {
          var self = this;
          this.$watch("tab", function (v) { W.store("work-clock-tab", v); var u = new URL(location.href); u.searchParams.set("tab", v); history.replaceState(null, "", u); });
          d.addEventListener("keydown", function (e) {
            if (typing(e) || e.ctrlKey || e.metaKey || e.altKey || d.querySelector(".wc[role=dialog]:not([style*='display: none'])")) return;
            var to = { "1": "focus", "2": "timers", "3": "stopwatch" }[e.key];
            if (to) { e.preventDefault(); self.tab = to; }
          });
        },
      };
    });

    /* Timers: presets, a time typed in (hours, minutes, seconds), a label; each timer's card. */
    Alpine.data("timersPanel", function () {
      return {
        h: "", m: "", s: "", label: "",
        get list() { return Alpine.store("clock").list; },
        get recent() { return Timers.recent; },
        seconds: function () { return (+this.h || 0) * 3600 + (+this.m || 0) * 60 + (+this.s || 0); },
        start: function (sec, label) {
          sec = sec || this.seconds();
          if (!(sec > 0)) { this.$refs.m && this.$refs.m.focus(); return; }
          Timers.add(sec, label != null ? label : this.label);
          this.h = this.m = this.s = ""; this.label = "";
        },
        left: function (t) { Alpine.store("clock").now; return tLeft(t); },
        text: function (t) { return t.done ? T("timesUp", "Time's up") : fmt(this.left(t)); },
        pct: function (t) { return t.total ? Math.max(0, Math.min(100, 100 * this.left(t) / t.total)) : 0; },
        length: function (sec) { return sec >= 3600 ? fmt(sec) : sec % 60 ? fmt(sec) : (sec / 60) + " " + T("min", "min"); },
        toggle: function (t) { Timers.toggle(t.id); },
        plus: function (t) { Timers.plus(t.id, 60); },
        restart: function (t) { Timers.restart(t.id); },
        remove: function (t) {
          var gone = Timers.remove(t.id);
          if (gone) W.toast(T("timerDeleted", "Timer deleted"), "", { label: T("undo", "Undo"), run: function () { Timers.putBack(gone); } });
        },
        rename: function (t, v) { Timers.rename(t.id, v); },
        clearDone: function () { Timers.clearDone(); },
        get anyDone() { return this.list.some(function (t) { return t.done; }); },
      };
    });

    /* The stopwatch: hundredths of a second while it runs (drawn each frame, only while it's in sight). */
    Alpine.data("stopwatchPanel", function () {
      return {
        shown: fmt(Stopwatch.elapsed(), true), running: Stopwatch.running, rows: Stopwatch.rows(),
        init: function () {
          var self = this, frame = function () {
            self.shown = fmt(Stopwatch.elapsed(), true);
            if (Stopwatch.running && !d.hidden) requestAnimationFrame(frame); else self.loop = false;
          };
          this.loop = false;
          this.go = function () { if (!self.loop && Stopwatch.running) { self.loop = true; requestAnimationFrame(frame); } };
          Timers.subscribe(function () { self.running = Stopwatch.running; self.rows = Stopwatch.rows(); self.shown = fmt(Stopwatch.elapsed(), true); self.go(); });
          d.addEventListener("visibilitychange", function () { self.go(); });
          this.go();
          d.addEventListener("keydown", function (e) {
            if (typing(e) || e.ctrlKey || e.metaKey || e.altKey || window.Clock.tab() !== "stopwatch") return;
            if (e.code === "Space") { e.preventDefault(); self.toggle(); }
            else if (e.key === "l" || e.key === "L") { e.preventDefault(); self.lap(); }
            else if (e.key === "r" || e.key === "R") { e.preventDefault(); self.reset(); }
          });
        },
        toggle: function () { Stopwatch.toggle(); },
        lap: function () { if (Stopwatch.running) Stopwatch.lap(); },
        reset: function () { if (!Stopwatch.running) Stopwatch.reset(); },
        fmt: function (sec) { return fmt(sec, true); },
        copy: function () {
          var text = this.rows.slice().reverse().map(function (r) { return "#" + r.n + "  " + fmt(r.lap, true) + "  " + fmt(r.total, true); }).join("\n");
          if (navigator.clipboard) navigator.clipboard.writeText(text).then(function () { W.toast(T("copied", "Copied")); });
        },
      };
    });

    /* The focus page's settings (⚙): each change is saved at once — lengths, goal, starting by itself, the sounds,
       how long they ring, the ticking — and the timer follows straight away. */
    Alpine.data("focusSettings", function (values, url) {
      return {
        open: false, v: values, state: "", timer: null,
        step: function (name, by, lo, hi) { this.v[name] = Math.max(lo, Math.min(hi, (+this.v[name] || 0) + by)); this.save(); },
        preset: function (f, sh, lo) { this.v.focus_minutes = f; this.v.short_break_minutes = sh; this.v.long_break_minutes = lo; this.save(); },
        isPreset: function (f, sh, lo) { return +this.v.focus_minutes === f && +this.v.short_break_minutes === sh && +this.v.long_break_minutes === lo; },
        hear: function (sound) { W.cfg.volume = this.v.volume; W.play(sound || this.v.sound, true); },
        hearTick: function (style) { W.cfg.volume = this.v.volume; var n = 0, iv = setInterval(function () { W.tick(n++, style); if (n > 3) clearInterval(iv); }, 500); },
        save: function () { var self = this; this.state = "saving"; clearTimeout(this.timer); this.timer = setTimeout(function () { self.send({}); }, 350); },
        defaults: function () { this.send({ action: "defaults" }); },
        send: function (extra) {
          var self = this, body = new FormData(), was = { focus: W.cfg.focus, short: W.cfg.short, long: W.cfg.long };
          body.append("csrfmiddlewaretoken", (d.querySelector("[name=csrfmiddlewaretoken]") || {}).value || (d.cookie.match(/csrftoken=([^;]+)/) || [])[1] || "");
          Object.keys(this.v).forEach(function (k) { var x = self.v[k]; body.append(k, typeof x === "boolean" ? (x ? "true" : "false") : x == null ? "" : x); });
          Object.keys(extra).forEach(function (k) { body.append(k, extra[k]); });
          fetch(url, { method: "POST", body: body, credentials: "same-origin", headers: { "X-Requested-With": "fetch", "X-CSRFToken": (d.cookie.match(/csrftoken=([^;]+)/) || [])[1] || "" } })
            .then(function (r) { return r.json(); })
            .then(function (res) {
              if (!res.ok) { self.state = "error"; W.toast(Object.values(res.errors || {}).map(function (e) { return e.join(" "); }).join(" ") || T("notSaved", "Not saved."), "warn"); return; }
              Object.assign(W.cfg, res.cfg); self.v = res.values; self.state = "saved";
              if (W.focus) W.focus.lengthsChanged(was);
              window.dispatchEvent(new CustomEvent("work:focus-settings", { detail: res.cfg }));
              if (extra.action === "defaults") W.toast(T("defaultsBack", "Back to the usual settings."));
            })
            .catch(function () { self.state = "error"; });
        },
      };
    });

    /* the "Time's up" cards, over any page */
    Alpine.store("ring", {
      items: [],
      stop: function (id) { ringStop(id); },
      stopAll: function () { this.items.slice().forEach(function (x) { ringStop(x.id); }); },
      snooze: function (x) { if (x.snooze) x.snooze(); ringStop(x.id); },
    });
    /* timers and the stopwatch, for the pages (and the pills in the top bar) */
    Alpine.store("clock", {
      now: Date.now(), list: TS.list.slice(), sw: { running: SW.running, laps: SW.laps.length },
      init: function () {
        var self = this;
        Timers.subscribe(function () { self.list = TS.list.slice(); self.sw = { running: SW.running, laps: SW.laps.length }; });
        setInterval(function () { if (anyRunning()) self.now = Date.now(); }, 250);
      },
      get running() { this.now; return this.list.filter(function (t) { return t.running; }); },
      get nextText() {
        this.now;
        var r = this.list.filter(function (t) { return t.running; }).sort(function (a, b) { return a.endsAt - b.endsAt; })[0];
        return r ? fmt(tLeft(r)) : "";
      },
      get swText() { this.now; return fmt(Stopwatch.elapsed()); },
    });
  });
}());
