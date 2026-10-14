/* Productivity (/work/): everything that makes it quick.
 * ---------------------------------------------------------------------------
 *  - Outbox: every change is sent at once; with no signal it waits on this
 *    device and goes out when the connection is back (never twice: each
 *    carries a one-off _ft_key, see apps/core/offline.py).
 *  - Timer: one running timer, ticking in the top bar and the tab title,
 *    the same in every open tab. Started and stopped by this device's clock,
 *    so it's right even when stopped offline.
 *  - Focus (Pomodoro): runs by end time, so it stays right when the phone
 *    sleeps; sounds (made in the browser, no files) and notifications.
 *  - Task rows: one click handler for the whole page and one shared ⋯ menu
 *    (rows are plain HTML, so long lists draw fast); j / k to move, x to tick.
 *  - Command palette (Ctrl+K): every page, command and item in one box.
 *  - Reminders, quick capture, keyboard shortcuts, undo.
 * Server: apps/productivity/api.py. Settings: window.WORK (json_script).
 */
(function () {
  "use strict";
  var d = document, root = d.documentElement;
  var CFG = {};
  try { CFG = JSON.parse((d.getElementById("work-config") || {}).textContent || "{}"); } catch (e) { CFG = {}; }
  var T = CFG.text || {};
  var ME = root.getAttribute("data-user") || "";
  var GROWS = !!(window.CSS && CSS.supports && CSS.supports("field-sizing", "content"));   // textareas that grow by themselves
  function t(key, fallback) { return T[key] || fallback; }

  /* ── Small helpers ─────────────────────────────────────────────────── */
  function csrf() { var m = d.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/); return m ? decodeURIComponent(m[1]) : ""; }
  function uid() { return (window.crypto && crypto.randomUUID) ? crypto.randomUUID() : Date.now().toString(36) + Math.random().toString(36).slice(2, 12); }
  function store(k, v) { try { if (v === null || v === undefined) localStorage.removeItem(k); else localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* storage off */ } }
  function recall(k, fallback) { try { var v = localStorage.getItem(k); return v === null ? fallback : JSON.parse(v); } catch (e) { return fallback; } }
  function pad(n) { return (n < 10 ? "0" : "") + n; }
  function clock(sec) {
    sec = Math.max(0, Math.floor(sec)); var h = Math.floor(sec / 3600), m = Math.floor(sec % 3600 / 60), s = sec % 60;
    return h ? h + ":" + pad(m) + ":" + pad(s) : pad(m) + ":" + pad(s);
  }
  function hm(sec) { sec = Math.max(0, Math.floor(sec)); var h = Math.floor(sec / 3600), m = Math.floor(sec % 3600 / 60); return h ? h + "h " + pad(m) + "m" : m + "m"; }
  function typing(e) {
    var el = e.target;
    // a drawing canvas (diagrams) has its own single-key shortcuts
    return el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName) || !!(el.closest && el.closest("[data-own-keys]")));
  }

  /* ── Outbox: send now, or keep until there's signal ──────────────────── */
  var OUTBOX = "work-outbox:" + ME;
  function body(fields) {
    var f = new FormData();
    Object.keys(fields).forEach(function (k) { if (fields[k] !== undefined && fields[k] !== null) f.append(k, fields[k]); });
    return f;
  }
  function post(url, fields, replay) {
    var headers = { "X-CSRFToken": csrf(), "X-Requested-With": "fetch", "Accept": "application/json" };
    if (replay) headers["X-FT-Replay"] = "1";
    return fetch(url, { method: "POST", body: body(fields), headers: headers, credentials: "same-origin" });
  }
  function queued() { return recall(OUTBOX, []); }
  function badge() {
    var n = queued().length;
    d.querySelectorAll("[data-work-outbox]").forEach(function (el) { el.hidden = !n; el.querySelector("b") && (el.querySelector("b").textContent = n); });
  }
  var api = function (url, data) {
    var fields = Object.assign({}, data || {}, { _ft_key: uid(), _ft_user: ME });
    return post(url, fields).then(function (res) {
      if (res.status === 403) return { ok: false, error: t("noAccess", "Not allowed.") };
      return res.json().catch(function () { return { ok: res.ok }; });
    }).catch(function () {
      var box = queued(); box.push({ url: url, fields: fields, at: Date.now() }); store(OUTBOX, box); badge();
      toast(t("savedOffline", "Saved on this device — it will sync when you're online."), "warn");
      return { ok: true, queued: true };
    });
  };
  var flushing = false;
  function flush() {
    if (flushing || !navigator.onLine) return Promise.resolve();
    var box = queued(); if (!box.length) return Promise.resolve();
    flushing = true;
    var sent = 0;
    function next() {
      var item = queued()[0];
      if (!item) return Promise.resolve();
      return post(item.url, item.fields, true).then(function (res) { return res.json().catch(function () { return { ok: res.ok }; }); }).then(function (ans) {
        var retry = !ans.ok && (ans.why === "busy" || ans.why === "error" || ans.why === "signin");
        if (retry) throw new Error("later");
        store(OUTBOX, queued().slice(1)); sent++; return next();
      });
    }
    return next().catch(function () { /* still offline: try again later */ }).then(function () {
      flushing = false; badge();
      if (sent) { toast(t("synced", "Synced changes made offline.")); if (d.querySelector("[data-work-refresh]")) location.reload(); }
    });
  }
  window.addEventListener("online", flush);
  setInterval(flush, 60000);

  /* ── Toast with an optional action (Undo) ───────────────────────────── */
  function toast(message, tone, action) {
    var rootEl = d.getElementById("toast-root");
    if (!rootEl) return;
    var el = d.createElement("div");
    el.className = "toast work-toast"; el.setAttribute("data-tone", tone || "good");
    var span = d.createElement("span"); span.textContent = message; el.appendChild(span);
    if (action) {
      var b = d.createElement("button"); b.type = "button"; b.className = "work-toast-btn"; b.textContent = action.label;
      b.addEventListener("click", function () { action.run(); el.remove(); });
      el.appendChild(b); el.style.pointerEvents = "auto";
    }
    rootEl.appendChild(el);
    requestAnimationFrame(function () { el.classList.add("is-in"); });
    setTimeout(function () { el.classList.remove("is-in"); setTimeout(function () { el.remove(); }, 250); }, action ? 6500 : 3200);
  }
  function undoable(message, undoUrl, after) {
    toast(message, "good", undoUrl ? { label: t("undo", "Undo"), run: function () {
      post(undoUrl, {}).then(function () { if (after) after(); else location.reload(); });
    } } : null);
  }

  /* ── Sound: made in the browser (no files to download) ──────────────── */
  var audio = null;
  function ctx() {
    if (!audio) { var C = window.AudioContext || window.webkitAudioContext; if (!C) return null; audio = new C(); }
    if (audio.state === "suspended") audio.resume();
    return audio;
  }
  // Any tap unlocks sound for later (browsers only allow it after a gesture).
  d.addEventListener("pointerdown", function once() { ctx(); d.removeEventListener("pointerdown", once); }, { passive: true });
  function tone(c, freq, start, length, type, gain) {
    var o = c.createOscillator(), g = c.createGain();
    o.type = type; o.frequency.value = freq;
    g.gain.setValueAtTime(0.0001, c.currentTime + start);
    g.gain.exponentialRampToValueAtTime(Math.max(gain, 0.0002), c.currentTime + start + 0.02);
    g.gain.exponentialRampToValueAtTime(0.0001, c.currentTime + start + length);
    o.connect(g); g.connect(c.destination); o.start(c.currentTime + start); o.stop(c.currentTime + start + length + 0.05);
  }
  var SOUNDS = {
    chime: function (c, v) { [523.25, 659.25, 783.99, 1046.5].forEach(function (f, i) { tone(c, f, i * 0.16, 1.1, "sine", v * 0.5); }); },
    bell: function (c, v) { [880, 1760, 2640].forEach(function (f, i) { tone(c, f, 0, 2.2 - i * 0.5, "triangle", v * (0.45 - i * 0.12)); }); tone(c, 880, 0.9, 1.6, "triangle", v * 0.3); },
    digital: function (c, v) { for (var i = 0; i < 3; i++) { tone(c, 1046.5, i * 0.22, 0.12, "square", v * 0.18); } },
    soft: function (c, v) { tone(c, 392, 0, 1.4, "sine", v * 0.4); tone(c, 523.25, 0.35, 1.6, "sine", v * 0.35); },
  };
  function play(kind, force) {
    var name = kind || CFG.sound;
    if (!name && !force) return;
    var c = ctx(); if (!c) return;
    (SOUNDS[name] || SOUNDS.chime)(c, Math.max(0.05, (CFG.volume == null ? 70 : CFG.volume) / 100));
  }
  function tick() { var c = ctx(); if (c && CFG.sound) tone(c, 1800, 0, 0.03, "square", 0.02 * (CFG.volume || 70) / 100); }

  /* ── Notifications (also when this tab is in the background) ──────────── */
  function canNotify() { return "Notification" in window && CFG.notify; }
  function askNotify() {
    if (!("Notification" in window)) return Promise.resolve("unsupported");
    return Notification.permission === "default" ? Notification.requestPermission() : Promise.resolve(Notification.permission);
  }
  function notify(title, text, url, tag) {
    if (canNotify() && Notification.permission === "granted") {
      var opts = { body: text || "", tag: tag || "work", icon: "/static/img/icons/icon-192.png", badge: "/static/img/icons/icon-192.png", data: { url: url || location.pathname }, renotify: true };
      if (navigator.serviceWorker && navigator.serviceWorker.ready) {
        navigator.serviceWorker.ready.then(function (reg) { reg.showNotification(title, opts); }).catch(function () { try { new Notification(title, opts); } catch (e) { /* ignore */ } });
      } else { try { new Notification(title, opts); } catch (e) { /* ignore */ } }
    }
    if (!d.hidden) toast(title + (text ? " — " + text : ""), "warn");
  }

  /* ── Reminders for tasks (remind_at), while the app is open ──────────── */
  (CFG.reminders || []).forEach(function (r) {
    var wait = new Date(r.at).getTime() - Date.now();
    var seen = recall("work-reminded", {});
    if (seen[r.id + "@" + r.at]) return;
    var fire = function () {
      var s = recall("work-reminded", {}); s[r.id + "@" + r.at] = 1; store("work-reminded", s);
      play(); notify(t("reminder", "Reminder"), r.title, r.url, "reminder-" + r.id);
    };
    if (wait <= 0 && wait > -3600000) fire(); else if (wait > 0 && wait < 86400000) setTimeout(fire, wait);
  });

  /* ── Flashcards: a nudge once a day, at the time picked in settings ──── */
  (function cardsNudge() {
    var at = CFG.cardsRemind, key = "work-cards-nudge:" + ME;
    if (!at || !CFG.urls.cardsDue) return;
    function check() {
      var now = new Date(), day = now.getFullYear() + "-" + pad(now.getMonth() + 1) + "-" + pad(now.getDate());
      if (pad(now.getHours()) + ":" + pad(now.getMinutes()) < at || recall(key, "") === day) return;
      store(key, day);
      if (location.pathname.indexOf(CFG.urls.cardReview) === 0) return;          // already reviewing
      fetch(CFG.urls.cardsDue, { credentials: "same-origin", headers: { Accept: "application/json" } })
        .then(function (r) { return r.json(); })
        .then(function (res) {
          if (!res || !res.due) return;
          var msg = t("cardsToReview", "%(n)s cards to review").replace(/%\(n\)s/g, res.due);
          play();
          if (d.hidden) notify(t("cardsWaiting", "Flashcards waiting"), msg, res.url, "cards");
          else toast(msg, "good", { label: t("review", "Review"), run: function () { location.href = res.url; } });
        })
        .catch(function () { store(key, null); });                             // offline: try again later
    }
    setTimeout(check, 3000); setInterval(check, 60000);
  })();

  /* ── Expose for the page components ──────────────────────────────────── */
  window.Work = { api: api, toast: toast, undoable: undoable, play: play, notify: notify, askNotify: askNotify, clock: clock, hm: hm, cfg: CFG, flush: flush, recall: recall, store: store };

  document.addEventListener("alpine:init", function () {

    /* ── The running timer (top bar + any "start" button) ─────────────── */
    var chan = ("BroadcastChannel" in window) ? new BroadcastChannel("work-timer:" + ME) : null;
    Alpine.store("timer", {
      running: CFG.running || null,     // {id, label, started_at, task, project, …}
      today: CFG.todaySeconds || 0,     // finished time today (the running part is added live)
      now: Date.now(),
      warned: false,
      get elapsed() { return this.running ? (this.now - new Date(this.running.started_at).getTime()) / 1000 : 0; },
      get text() { return clock(this.elapsed); },
      get todayText() { return hm(this.today + (this.running ? this.elapsedToday() : 0)); },
      elapsedToday: function () {
        if (!this.running) return 0;
        var mid = new Date(); mid.setHours(0, 0, 0, 0);
        var from = Math.max(new Date(this.running.started_at).getTime(), mid.getTime());
        return Math.max(0, (this.now - from) / 1000);
      },
      init: function () {
        var self = this;
        setInterval(function () { self.now = Date.now(); self.title(); self.check(); }, 1000);
        if (chan) chan.onmessage = function (e) { self.running = e.data.running; if (e.data.today != null) self.today = e.data.today; self.title(); };
        Alpine.effect(function () { markTimer(self.running ? self.running.task : null); });
        d.addEventListener("visibilitychange", function () { if (!d.hidden) self.sync(); });
        this.title();
      },
      share: function () {   // a plain copy: Alpine's reactive objects can't be sent between tabs
        if (chan) chan.postMessage({ running: this.running ? JSON.parse(JSON.stringify(this.running)) : null, today: this.today });
      },
      title: function () {
        var base = d.title.replace(/^⏱ [^·]+ · /, "");
        d.title = this.running ? "⏱ " + this.text + " · " + base : base;
        if ("setAppBadge" in navigator) { try { this.running ? navigator.setAppBadge() : navigator.clearAppBadge(); } catch (e) { /* ignore */ } }
      },
      check: function () {
        if (this.running && !this.warned && this.elapsed > (CFG.longTimer || 3) * 3600) {
          this.warned = true;
          play(); notify(t("stillWorking", "Still working?"), this.running.label + " · " + this.text, location.pathname, "long-timer");
        }
      },
      sync: function () {
        var self = this;
        fetch(CFG.urls.timerState, { credentials: "same-origin", headers: { "Accept": "application/json" } })
          .then(function (r) { return r.json(); }).then(function (data) {
            if (!data.ok || queued().length) return;   // changes still waiting win
            self.running = data.running; self.today = data.today - (data.running ? self.elapsedToday() : 0); self.share();
          }).catch(function () { /* offline */ });
      },
      start: function (opts) {
        opts = opts || {};
        var self = this, at = new Date().toISOString();
        if (this.running) this.today += this.elapsedToday();
        this.running = { id: null, label: opts.label || opts.description || t("noDescription", "No description"), started_at: at,
                         task: opts.task || null, project: opts.project || null, description: opts.description || "", color: opts.color || "" };
        this.warned = false; this.share(); play(CFG.sound ? "soft" : "");
        return api(CFG.urls.timerStart, { task: opts.task || "", project: opts.project || "", description: opts.description || "", at: at }).then(function (res) {
          if (res.ok && res.running) { self.running = res.running; self.today = res.today - self.elapsedToday(); self.share(); }
          d.dispatchEvent(new CustomEvent("work:timer", { detail: self.running }));
          return res;
        });
      },
      stop: function () {
        if (!this.running) return Promise.resolve();
        var self = this, at = new Date().toISOString();
        this.today += this.elapsedToday(); var label = this.running.label, took = this.text;
        this.running = null; this.share(); this.title();
        return api(CFG.urls.timerStop, { at: at }).then(function (res) {
          if (res.ok && !res.queued) self.today = res.today;
          toast(t("tracked", "Tracked") + " " + took + " · " + label);
          d.dispatchEvent(new CustomEvent("work:timer", { detail: null }));
          if (d.querySelector("[data-work-refresh-on-stop]")) setTimeout(function () { location.reload(); }, 400);
          return res;
        });
      },
      toggle: function (opts) { return this.running ? this.stop() : this.start(opts); },
      rename: function (text) {
        if (!this.running) return;
        this.running.description = text; this.running.label = text || this.running.task_title || this.running.label; this.share();
        api(CFG.urls.timerUpdate, { description: text });
      },
      isFor: function (taskId) { return !!(this.running && String(this.running.task) === String(taskId)); },
    });

    /* ── Quick capture: task / note / time, from anywhere (c, n) ──────── */
    Alpine.data("workCapture", function () {
      return {
        open: false, mode: "task", text: "", busy: false,
        init: function () {
          var self = this;
          d.addEventListener("work:capture", function (e) {
            var x = e.detail || "task";
            if (typeof x === "object") { if (x.text != null) self.text = x.text; x = x.mode || "task"; }
            self.show(x);
          });
          var asked = new URLSearchParams(location.search).get("capture");
          if (asked && /^(task|note|time)$/.test(asked)) setTimeout(function () { self.show(asked); }, 60);
        },
        show: function (mode) { this.mode = mode || "task"; this.open = true; var self = this; setTimeout(function () { var el = self.$refs[self.mode]; if (el) el.focus(); }, 40); },
        hide: function () { this.open = false; },
        get chips() { return this.mode === "task" ? parseChips(this.text) : []; },
        save: function (startTimer) {
          var self = this, text = this.text.trim();
          if (!text || this.busy) return;
          this.busy = true;
          var go;
          if (this.mode === "note") go = api(CFG.urls.noteSave, { body: text });
          else if (this.mode === "time") go = Alpine.store("timer").start({ description: text, label: text });
          else go = api(CFG.urls.taskAdd, { text: text, my_day: this.myDay ? "1" : "", start: startTimer ? "1" : "", at: new Date().toISOString() });
          go.then(function (res) {
            self.busy = false;
            if (!res || !res.ok) { toast((res && res.error) || t("notSaved", "Not saved."), "warn"); return; }
            self.text = "";
            if (self.mode === "task") {
              toast(res.queued ? t("savedOffline", "Saved on this device") : t("taskAdded", "Task added"));
              if (startTimer && res.id) Alpine.store("timer").sync();
              d.dispatchEvent(new CustomEvent("work:task-added", { detail: res }));
              if (res.url && !res.queued) self.last = res.url;
            } else if (self.mode === "note") { toast(t("noteSaved", "Note saved")); }
            if (!self.keepOpen) self.hide();
          });
        },
        myDay: false, keepOpen: false,
      };
    });

    /* ── A task list: new tasks (quick add) appear at the top ────────────── */
    Alpine.data("workTasks", function () {
      return {
        init: function () {
          var self = this;
          d.addEventListener("work:task-added", function (e) {
            var list = self.$root.querySelector("[data-new-tasks]");
            if (list && e.detail.html) {
              list.insertAdjacentHTML("afterbegin", e.detail.html); markTimer();
              var wrap = list.closest("[data-empty-wrap]"); if (wrap) wrap.classList.add("has-items");
            }
          });
        },
      };
    });

    /* ── Board: drag cards between columns (SortableJS) ───────────────── */
    Alpine.data("workBoard", function () {
      return {
        init: function () {
          var self = this;
          function setup() {
            if (!window.Sortable) return setTimeout(setup, 80);
            self.$root.querySelectorAll("[data-column]").forEach(function (col) {
              Sortable.create(col, {
                group: "tasks", animation: 160, ghostClass: "is-ghost", dragClass: "is-dragging", delay: 120, delayOnTouchOnly: true,
                onEnd: function (e) {
                  var card = e.item, prev = card.previousElementSibling, next = card.nextElementSibling;
                  var status = e.to.getAttribute("data-column");
                  card.classList.toggle("is-done", status === "done");
                  if (status === "done" && e.from !== e.to) play(CFG.sound ? "chime" : "");
                  api(CFG.urls.taskBase + card.getAttribute("data-task") + "/move/", {
                    status: status, after: prev ? prev.getAttribute("data-task") : "", before: next ? next.getAttribute("data-task") : "",
                  });
                  self.count();
                },
              });
            });
          }
          setup();
          d.addEventListener("work:task-added", function (e) {
            var col = self.$root.querySelector('[data-column="' + (e.detail.status || "todo") + '"]') || self.$root.querySelector("[data-column=todo]");
            if (col && e.detail.card) col.insertAdjacentHTML("beforeend", e.detail.card);
            self.count();
          });
        },
        count: function () { this.$root.querySelectorAll("[data-column]").forEach(function (col) { var c = col.parentElement.querySelector("[data-count]"); if (c) c.textContent = col.children.length; }); },
      };
    });

    /* ── Plan the week: drag tasks between the days (sets My Day) ─────── */
    Alpine.data("workWeek", function () {
      return {
        init: function () {
          var self = this;
          function setup() {
            if (!window.Sortable) return setTimeout(setup, 80);
            self.$root.querySelectorAll("[data-day]").forEach(function (list) {
              Sortable.create(list, {
                group: { name: "week", put: function (to) { return !to.el.hasAttribute("data-past"); } },
                animation: 160, ghostClass: "is-ghost", dragClass: "is-dragging", delay: 150, delayOnTouchOnly: true, filter: "a.wt-link", preventOnFilter: false,
                forceFallback: true, fallbackTolerance: 4, fallbackOnBody: true, scroll: true, bubbleScroll: true,
                onAdd: function (e) {
                  var day = e.to.getAttribute("data-day");
                  api(CFG.urls.taskBase + e.item.getAttribute("data-task") + "/update/", { my_day: day }).then(function (res) {
                    if (res && res.ok === false) toast(res.error || t("error", "Couldn't save."), "warn");
                  });
                  self.count();
                },
              });
            });
            self.count();
          }
          setup();
        },
        count: function () {
          var total = 0;
          this.$root.querySelectorAll("[data-day]").forEach(function (list) {
            var col = list.closest(".wwk-col"), mins = 0;
            list.querySelectorAll("[data-task]:not(.is-done)").forEach(function (c) { mins += +c.getAttribute("data-est") || 0; });
            var p = col.querySelector("[data-planned]"); if (p) p.textContent = hm(mins * 60);
            var target = +col.getAttribute("data-target") || 0, bar = col.querySelector(".wwk-load");
            if (bar && target) { bar.querySelector("i").style.width = Math.min(100, Math.round(100 * mins * 60 / target)) + "%"; bar.classList.toggle("is-over", mins * 60 > target); }
            var c = col.querySelector("[data-count]"); if (c) c.textContent = list.children.length;
            if (list.getAttribute("data-day") && !list.hasAttribute("data-past")) total += mins;
          });
          var w = d.querySelector("[data-week-planned]"); if (w) w.textContent = hm(total * 60);
        },
        add: function (e, day) {
          var self = this, box = e.target.elements.text, text = box.value.trim(); if (!text) return;
          box.value = "";
          api(CFG.urls.taskAdd, { text: text, my_day: day }).then(function (res) {
            if (!res.ok) { toast(res.error || t("notSaved", "Not saved."), "warn"); return; }
            if (res.card) { e.target.previousElementSibling.insertAdjacentHTML("beforeend", res.card); self.count(); }
          });
        },
      };
    });

    /* ── Day planner: drag tasks onto the day's hours (time blocking) ──── */
    Alpine.data("workPlan", function (initial, opts) {
      var PPM = 1.2, SLOT = 15;     // pixels per minute; snap to quarter hours
      function pad(n) { return (n < 10 ? "0" : "") + n; }
      function hhmm(min) { return pad(Math.floor(min / 60) % 24) + ":" + pad(min % 60); }
      function snap(min) { return Math.max(0, Math.min(24 * 60 - SLOT, Math.round(min / SLOT) * SLOT)); }
      function nowMinute() { var n = new Date(); return n.getHours() * 60 + n.getMinutes(); }
      return {
        plan: initial, ppm: PPM, picked: null, open: null, drag: null, ghost: null, now: nowMinute(),
        isToday: opts.isToday, dayStart: opts.dayStart, dayEnd: opts.dayEnd, busy: false, pickTime: "",
        init: function () {
          var self = this;
          setInterval(function () { self.now = nowMinute(); }, 60000);
          this.$nextTick(function () {
            var box = self.$refs.scroll; if (!box) return;
            var at = self.isToday ? Math.max(Math.min(self.now - 60, self.dayEnd - 120), self.dayStart - 30) : self.dayStart - 30;
            box.scrollTop = Math.max(0, at * PPM);
          });
        },
        hours: function () { var out = []; for (var h = 0; h < 24; h++) out.push(h); return out; },
        label: function (h) { return pad(h) + ":00"; },
        hhmm: hhmm,
        get laid() {      // side by side when blocks overlap
          var items = this.plan.blocks.slice().sort(function (a, b) { return a.start - b.start || b.length - a.length; });
          var out = [], cluster = [], colsEnd = [], clusterEnd = -1;
          function close() { var n = colsEnd.length || 1; cluster.forEach(function (b) { b.cols = n; }); cluster = []; colsEnd = []; }
          items.forEach(function (b) {
            var item = Object.assign({}, b), end = b.start + b.length;
            if (b.start >= clusterEnd) { close(); clusterEnd = -1; }
            var col = colsEnd.findIndex(function (e) { return e <= b.start; });
            if (col < 0) { col = colsEnd.length; colsEnd.push(end); } else colsEnd[col] = end;
            item.col = col; cluster.push(item); out.push(item); clusterEnd = Math.max(clusterEnd, end);
          });
          close();
          return out;
        },
        blockStyle: function (b) {
          var w = 100 / (b.cols || 1);
          return "top:" + (b.start * PPM) + "px;height:" + Math.max(b.length * PPM - 2, 18) + "px;left:calc(" + (b.col * w) + "% + 2px);width:calc(" + w + "% - 4px)";
        },
        entryStyle: function (e) { return "top:" + (e.start * PPM) + "px;height:" + Math.max((e.end - e.start) * PPM, 3) + "px"; },
        get planned() { return this.plan.blocks.reduce(function (s, b) { return s + (b.done ? 0 : b.length); }, 0); },
        get tracked() { return this.plan.entries.reduce(function (s, e) { return s + Math.max(0, e.end - e.start); }, 0); },
        get windowMinutes() { return Math.max(0, this.dayEnd - this.dayStart); },
        get overbooked() { return this.planned > this.windowMinutes && this.windowMinutes > 0; },
        hm: function (min) { return hm(min * 60); },
        task: function (id) {
          return this.plan.blocks.find(function (b) { return b.id === id; }) || this.plan.unplanned.find(function (b) { return b.id === id; });
        },
        /* Saving */
        place: function (id, start) {
          var self = this, item = this.task(id); if (!item) return;
          start = snap(start);
          this.plan.unplanned = this.plan.unplanned.filter(function (b) { return b.id !== id; });
          var existing = this.plan.blocks.find(function (b) { return b.id === id; });
          if (existing) existing.start = start; else this.plan.blocks.push(Object.assign({}, item, { start: start }));
          this.picked = null; this.pickTime = "";
          return api(CFG.urls.taskBase + id + "/update/", { scheduled_at: this.plan.date + "T" + hhmm(start) }).then(function (res) {
            if (res && res.ok === false) { toast(res.error || t("error", "Couldn't save."), "warn"); }
            return res;
          });
        },
        resize: function (id, length) {
          var b = this.plan.blocks.find(function (x) { return x.id === id; }); if (!b) return;
          b.length = Math.max(SLOT, Math.round(length / SLOT) * SLOT); b.estimate = b.length;
          api(CFG.urls.taskBase + id + "/update/", { estimate_minutes: b.length });
        },
        unplan: function (id) {
          var b = this.plan.blocks.find(function (x) { return x.id === id; }); if (!b) return;
          this.plan.blocks = this.plan.blocks.filter(function (x) { return x.id !== id; });
          if (!b.done) this.plan.unplanned.unshift(Object.assign({}, b, { length: b.estimate || 30 }));
          this.open = null;
          api(CFG.urls.taskBase + id + "/update/", { scheduled_at: "" });
        },
        done: function (id) {
          var b = this.task(id); if (!b) return;
          b.done = !b.done; this.open = null;
          if (b.done) play(CFG.sound ? "chime" : "");
          if (b.done) this.plan.unplanned = this.plan.unplanned.filter(function (x) { return x.id !== id; });
          api(CFG.urls.taskBase + id + "/done/", { done: b.done ? "1" : "0" });
        },
        timer: function (id) {
          var b = this.task(id), tm = Alpine.store("timer"); if (!b) return;
          this.open = null;
          if (tm.isFor(id)) tm.stop(); else tm.start({ task: id, label: b.title });
        },
        setTime: function (id, value) {
          var m = /^(\d{1,2}):(\d{2})$/.exec(value || ""); if (!m) return;
          this.place(id, +m[1] * 60 + +m[2]); this.open = null;
        },
        act: function (action) {
          var self = this; if (this.busy) return;
          if (action === "clear" && !window.confirm(t("clearPlan", "Take every open task off the timeline? They stay on the day's list."))) return;
          this.busy = true;
          api(CFG.urls.planAction, { action: action, date: this.plan.date }).then(function (res) {
            self.busy = false;
            if (!res || !res.ok || res.queued) return;
            self.plan = res.plan;
            if (action === "fill") {
              var tomorrow = self.isToday && !res.placed && res.left ? { label: t("planTomorrow", "Plan tomorrow"), run: function () { location.href = CFG.urls.plan + "?date=" + isoDay(1); } } : null;
              toast(res.placed ? t("planned", "Planned") + ": " + res.placed + (res.left ? " · " + t("noRoom", "no room for") + " " + res.left : "")
                               : (res.left ? t("dayFull", "No free time left in your work day.") : t("nothingToPlan", "Nothing left to plan.")), res.placed ? "good" : "warn", tomorrow);
            }
          });
        },
        /* Pointer: drag a task or block onto the timeline, or stretch a block */
        minuteAt: function (clientY) {
          var grid = this.$refs.grid.getBoundingClientRect();
          return (clientY - grid.top) / PPM;
        },
        overGrid: function (x, y) {
          var r = this.$refs.scroll.getBoundingClientRect();
          return x >= r.left && x <= r.right && y >= r.top && y <= r.bottom;
        },
        down: function (e, id, kind) {
          if (e.button !== undefined && e.button !== 0) return;
          var item = this.task(id); if (!item) return;
          var offset = 0;
          if (kind === "block") offset = this.minuteAt(e.clientY) - item.start;
          this.drag = { id: id, kind: kind, x: e.clientX, y: e.clientY, offset: offset, moved: false, length: item.length, start: item.start, el: e.currentTarget, pid: e.pointerId };
          try { e.currentTarget.setPointerCapture(e.pointerId); } catch (err) { /* old browser */ }
        },
        move: function (e) {
          var g = this.drag; if (!g) return;
          if (!g.moved && Math.abs(e.clientX - g.x) + Math.abs(e.clientY - g.y) < 6) return;
          g.moved = true; e.preventDefault();
          this.autoscroll(e.clientY);
          if (g.kind === "resize") {
            var b = this.plan.blocks.find(function (x) { return x.id === g.id; });
            g.length = Math.max(SLOT, Math.round((this.minuteAt(e.clientY) - b.start) / SLOT) * SLOT);
            this.ghost = { start: b.start, length: g.length, title: b.title };
            return;
          }
          if (this.overGrid(e.clientX, e.clientY)) {
            this.ghost = { start: snap(this.minuteAt(e.clientY) - g.offset), length: g.length, title: this.task(g.id).title };
          } else this.ghost = null;
        },
        up: function (e) {
          var g = this.drag; if (!g) return;
          this.drag = null;
          try { g.el.releasePointerCapture(g.pid); } catch (err) { /* fine */ }
          var ghost = this.ghost; this.ghost = null;
          if (!g.moved) {             // a tap
            if (g.kind === "block") this.open = this.open === g.id ? null : g.id;
            else if (g.kind === "item") this.picked = this.picked === g.id ? null : g.id;
            return;
          }
          if (g.kind === "resize") { this.resize(g.id, g.length); return; }
          if (ghost) this.place(g.id, ghost.start);
        },
        autoscroll: function (y) {
          var box = this.$refs.scroll, r = box.getBoundingClientRect();
          if (y < r.top + 40) box.scrollTop -= 12; else if (y > r.bottom - 40) box.scrollTop += 12;
        },
        gridClick: function (e) {
          if (this.picked) { this.place(this.picked, Math.floor(this.minuteAt(e.clientY) / SLOT) * SLOT); return; }
          this.open = null;
        },
        isRunning: function (id) { var tm = Alpine.store("timer"); return tm && tm.isFor(id); },
      };
    });

    /* ── Command palette (Ctrl+K): pages, commands and everything you made ─ */
    Alpine.data("workPalette", function () {
      var RECENT = "work-recent:" + ME;
      return {
        open: false, q: "", active: 0, found: [], loading: false, ctl: null, timer: null, icons: {},
        init: function () {
          var self = this;
          this.$root.querySelectorAll("template[data-icon]").forEach(function (tp) { self.icons[tp.getAttribute("data-icon")] = tp.innerHTML; });
          d.addEventListener("work:palette", function () { self.open ? self.close() : self.show(); });
        },
        show: function () { this.open = true; this.q = ""; this.found = []; this.active = 0; var self = this; this.$nextTick(function () { self.$refs.q.focus(); }); },
        close: function () { this.open = false; if (this.ctl) this.ctl.abort(); },
        get commands() {
          var tm = Alpine.store("timer");
          return (CFG.commands || []).filter(function (c) {
            return c.when === "running" ? !!tm.running : c.when === "idle" ? !tm.running : true;
          });
        },
        get items() {
          var q = this.q.trim(), cmdOnly = q.charAt(0) === ">", text = (cmdOnly ? q.slice(1) : q).trim().toLowerCase();
          var cmds = this.commands.filter(function (c) { return !text || match(c.title + " " + (c.words || ""), text); })
            .map(function (c) { return Object.assign({ key: "c:" + c.id, group: T.kindCommand || "Command" }, c); });
          if (!q) {
            var recent = recall(RECENT, []).map(function (r) { return Object.assign({ key: "r:" + r.url, group: T.kindRecent || "Recent" }, r); });
            return recent.concat(cmds).slice(0, 40);
          }
          if (cmdOnly) return cmds;
          var hits = this.found.map(function (r) { return Object.assign({ key: "f:" + r.url, group: (T.kinds || {})[r.kind] || r.kind }, r); });
          var adds = [
            { key: "a:task", kind: "add", action: "add:task", title: (T.addTask || "Add task") + ": " + q, group: T.kindCreate || "Create" },
            { key: "a:note", kind: "add-note", action: "add:note", title: (T.addNote || "Save as a note") + ": " + q, group: T.kindCreate || "Create" },
            { key: "a:time", kind: "add-time", action: "add:time", title: (T.trackThis || "Start the timer for") + ": " + q, group: T.kindCreate || "Create" },
          ];
          return cmds.slice(0, 6).concat(hits, adds);
        },
        search: function () {
          var self = this, q = this.q.trim();
          this.active = 0; clearTimeout(this.timer);
          if (q.length < 2 || q.charAt(0) === ">") { this.found = []; return; }
          this.timer = setTimeout(function () {
            if (self.ctl) self.ctl.abort();
            self.ctl = ("AbortController" in window) ? new AbortController() : null;
            self.loading = true;
            fetch(CFG.urls.search + "?q=" + encodeURIComponent(q), { credentials: "same-origin", headers: { "Accept": "application/json" }, signal: self.ctl && self.ctl.signal })
              .then(function (r) { return r.json(); }).then(function (data) { if (self.q.trim() === q) { self.found = data.results || []; self.loading = false; } })
              .catch(function () { self.loading = false; });
          }, 110);
        },
        move: function (step) {
          var n = this.items.length; if (!n) return;
          this.active = (this.active + step + n) % n;
          var el = this.$refs.list.children[this.active + 1]; if (el && el.scrollIntoView) el.scrollIntoView({ block: "nearest" });
        },
        icon: function (it) { return this.icons[it.icon || it.kind] || this.icons.arrow || ""; },
        go: function (i) {
          var it = this.items[i]; if (!it) return;
          var q = this.q.trim();
          if (it.url) {
            if (it.kind && it.kind !== "page") {
              var recent = recall(RECENT, []).filter(function (r) { return r.url !== it.url; });
              recent.unshift({ url: it.url, title: it.title, kind: it.kind, meta: it.meta || "" }); store(RECENT, recent.slice(0, 6));
            }
            this.close(); location.href = it.url; return;
          }
          this.close();
          var a = it.action || "";
          if (a === "add:task") api(CFG.urls.taskAdd, { text: q }).then(function (res) { if (res.ok) { toast(res.queued ? t("savedOffline", "Saved on this device") : t("taskAdded", "Task added")); d.dispatchEvent(new CustomEvent("work:task-added", { detail: res })); } else toast(res.error || t("notSaved", "Not saved."), "warn"); });
          else if (a === "add:note") api(CFG.urls.noteSave, { body: q }).then(function (res) { if (res.ok) toast(t("noteSaved", "Note saved")); });
          else if (a === "add:time") Alpine.store("timer").start({ description: q, label: q });
          else if (a.indexOf("capture:") === 0) d.dispatchEvent(new CustomEvent("work:capture", { detail: a.slice(8) }));
          else if (a === "timer:stop") Alpine.store("timer").stop();
          else if (a === "help") d.dispatchEvent(new CustomEvent("work:help"));
          else if (a === "copy:url") copyText(location.href);
        },
      };
    });

    /* ── "You were away": time the timer ran while nobody was there ────── */
    Alpine.data("workIdle", function () {
      return {
        open: false, since: 0, until: 0, label: "", run: null,
        get awayText() { return hm((this.until - this.since) / 1000); },
        get sinceText() { var x = new Date(this.since); return pad(x.getHours()) + ":" + pad(x.getMinutes()); },
        init: function () {
          var self = this;
          d.addEventListener("work:idle", function (e) {
            var tm = Alpine.store("timer"); if (!tm.running || self.open) return;
            self.since = e.detail.since; self.until = e.detail.until || Date.now();
            self.run = JSON.parse(JSON.stringify(tm.running)); self.label = tm.running.label; self.open = true;
            play(); notify(t("stillWorking", "Still working on this?"), self.label, location.pathname, "idle");
          });
        },
        stopAt: function () {
          var tm = Alpine.store("timer"), at = new Date(this.since).toISOString();
          this.open = false; tm.running = null; tm.share(); tm.title();
          api(CFG.urls.timerStop, { at: at }).then(function () { tm.sync(); });
        },
        trim: function () {
          var tm = Alpine.store("timer"), r = this.run, at = new Date(this.since).toISOString();
          this.open = false;
          api(CFG.urls.timerStop, { at: at }).then(function () {
            return api(CFG.urls.timerStart, { task: r.task || "", project: r.project || "", description: r.description || "", at: new Date().toISOString() });
          }).then(function () { tm.sync(); });
        },
        keep: function () { this.open = false; },
      };
    });

    /* ── Learning: +progress, start, finish ───────────────────────────── */
    Alpine.data("workLearn", function (id, progress, total, unit, status) {
      var UNITS = (CFG.text && CFG.text.units) || {};
      return {
        p: progress, total: total, unit: unit, status: status,
        get step() { return unit === "percent" ? 10 : 1; },
        get pct() { return this.status === "done" ? 100 : unit === "percent" ? Math.min(this.p, 100) : (this.total ? Math.min(100, Math.round(100 * this.p / this.total)) : 0); },
        get label() { return unit === "percent" ? this.p + "%" : this.p + (this.total ? " / " + this.total : "") + " " + (UNITS[unit] || unit); },
        send: function (data) {
          var self = this;
          return api(CFG.urls.learningBase + id + "/", data).then(function (res) {
            if (res.ok && !res.queued) { self.p = res.progress; self.status = res.status; }
            return res;
          });
        },
        add: function (n) {
          this.p = Math.max(0, this.p + n); if (this.total) this.p = Math.min(this.p, this.total); if (unit === "percent") this.p = Math.min(this.p, 100);
          if (this.status === "queued") this.status = "active";
          this.send({ add: n });
        },
        set: function (st) {
          this.status = st;
          if (st === "done") { play(CFG.sound ? "chime" : ""); if (this.total) this.p = this.total; }
          this.send({ status: st });
        },
      };
    });

    /* ── Checklist on a task ──────────────────────────────────────────── */
    Alpine.data("workChecklist", function (taskId) {
      return {
        text: "",
        add: function () {
          var self = this, text = this.text.trim(); if (!text) return;
          this.text = "";
          api(CFG.urls.taskBase + taskId + "/checklist/", { text: text }).then(function (res) {
            if (!res.ok) return;
            var li = d.createElement("li"); li.className = "work-check"; li.setAttribute("data-item", res.id || "");
            li.innerHTML = '<label><input type="checkbox"><span></span></label><button type="button" class="icon-btn" aria-label="×">×</button>';
            li.querySelector("span").textContent = text;
            self.$refs.list.appendChild(li); self.bind(li); self.progress();
          });
        },
        bind: function (li) {
          var self = this, id = li.getAttribute("data-item");
          li.querySelector("input").addEventListener("change", function (e) { li.classList.toggle("is-done", e.target.checked); if (id) api(CFG.urls.checklist + id + "/", { done: e.target.checked ? "1" : "0" }); self.progress(); });
          li.querySelector("button").addEventListener("click", function () { if (id) api(CFG.urls.checklist + id + "/", { action: "delete" }); li.remove(); self.progress(); });
        },
        init: function () { var self = this; this.$refs.list.querySelectorAll("li").forEach(function (li) { self.bind(li); }); this.progress(); },
        progress: function () {
          var all = this.$refs.list.querySelectorAll("li").length, done = this.$refs.list.querySelectorAll("input:checked").length;
          var bar = this.$root.querySelector("[data-progress]"); if (bar) { bar.style.setProperty("--p", all ? (100 * done / all) + "%" : "0%"); bar.setAttribute("data-label", done + "/" + all); }
        },
      };
    });

    /* ── Notes: autosave, a copy on this device, Markdown preview ─────── */
    Alpine.data("workNote", function (initial) {
      return {
        id: initial.id || null, title: initial.title || "", body: initial.body || "", tags: initial.tags || "", project: initial.project || "",
        state: "saved", savedAt: initial.saved || "", preview: false, timer: null, inflight: null, again: false,
        making: false, suggest: [], pick: 0, dgOpen: false, dgItems: [], dgQ: "", dgLoading: false,
        histOpen: false, histLoading: false, versions: [], shown: null,
        /* Earlier versions: kept before each round of writing; one can be read and brought back */
        openHistory: function () {
          var self = this; if (!this.id) return;
          this.histOpen = true; this.histLoading = true; this.shown = null;
          Promise.resolve(this.saveNow()).then(function () {
            return fetch(CFG.urls.noteBase + self.id + "/versions/", { credentials: "same-origin", headers: { Accept: "application/json" } });
          }).then(function (r) { return r.json(); }).then(function (res) { self.versions = res.versions || []; self.shown = self.versions[0] || null; })
            .catch(function () { self.versions = []; }).then(function () { self.histLoading = false; });
        },
        restoreVersion: function (v) {
          if (!v || !confirm(t("restoreNote", "Bring back this version? What's there now is kept as a version too."))) return;
          var self = this;
          api(CFG.urls.noteBase + this.id + "/", { action: "restore", version: v.id }).then(function (res) {
            if (res.ok && res.url) { store(self.draftKey, null); location.href = res.url; }
          });
        },
        forgetVersion: function (v) {
          var self = this;
          api(CFG.urls.noteBase + this.id + "/", { action: "forget", version: v.id }).then(function (res) {
            if (!res.ok) return;
            self.versions = self.versions.filter(function (x) { return x.id !== v.id; });
            if (self.shown && self.shown.id === v.id) self.shown = self.versions[0] || null;
          });
        },
        /* Put a diagram in the note: its picture, linking to it (it stays up to date as the diagram changes) */
        openDiagrams: function () {
          this.dgOpen = !this.dgOpen; if (this.dgOpen) this.findDiagrams();
        },
        findDiagrams: function () {
          var self = this; this.dgLoading = true;
          fetch(CFG.urls.diagramList + "?q=" + encodeURIComponent(this.dgQ), { credentials: "same-origin", headers: { Accept: "application/json" } })
            .then(function (r) { return r.json(); }).then(function (res) { self.dgItems = res.items || []; })
            .catch(function () { self.dgItems = []; }).then(function () { self.dgLoading = false; });
        },
        insertDiagram: function (item) {
          var title = String(item.title).replace(/[\[\]]/g, "");
          this.dgOpen = false; this.preview = false;
          this.insert("\n[![" + title + "](" + item.picture + ")](" + item.url + ")\n", "");
        },
        titles: (function () { try { return JSON.parse((d.getElementById("note-titles") || {}).textContent || "[]"); } catch (e) { return []; } })(),
        get todoCount() {      // open "- [ ] …" lines that aren't tasks yet
          return (this.body.match(/^[ \t]*[-*+][ \t]+\[ \][ \t]+\S.*$/gm) || []).filter(function (l) { return l.indexOf("/work/tasks/") < 0; }).length;
        },
        todosToTasks: function () {
          var self = this; if (!this.id || this.making) return;
          this.making = true;
          Promise.resolve(this.saveNow()).then(function () {
            return api(CFG.urls.noteBase + self.id + "/", { action: "todos" });
          }).then(function (res) {
            self.making = false;
            if (!res || !res.ok) { if (res && res.error) toast(res.error, "warn"); return; }
            if (res.queued) return;
            self.body = res.body; self.savedAt = res.saved;
            toast(t("tasksMade", "Tasks made") + ": " + res.count, "good", { label: t("openTasks", "See them"), run: function () { location.href = CFG.urls.tasks; } });
          });
        },
        /* [[Note title]]: suggest the person's notes while typing a link */
        linkLookup: function () {
          var ta = this.$refs.body, before = this.body.slice(0, ta.selectionStart), m = /\[\[([^\]\n]{0,60})$/.exec(before);
          if (!m) { this.suggest = []; return; }
          var q = m[1].toLowerCase(), me = this.title;
          this.suggest = this.titles.filter(function (x) { return x !== me && x.toLowerCase().indexOf(q) >= 0; }).slice(0, 7);
          this.pick = 0;
        },
        chooseLink: function (title) {
          var ta = this.$refs.body, at = ta.selectionStart, before = this.body.slice(0, at), after = this.body.slice(at);
          var start = before.lastIndexOf("[[");
          var close = after.indexOf("]]") === 0 ? "" : "]]";
          this.body = before.slice(0, start) + "[[" + title + close + after;
          var pos = start + 2 + title.length + 2;
          this.suggest = [];
          var self = this; this.$nextTick(function () { ta.focus(); ta.setSelectionRange(pos, pos); });
        },
        linkKey: function (e) {
          if (this.suggest.length) {
            if (e.key === "ArrowDown") { e.preventDefault(); this.pick = (this.pick + 1) % this.suggest.length; return; }
            if (e.key === "ArrowUp") { e.preventDefault(); this.pick = (this.pick - 1 + this.suggest.length) % this.suggest.length; return; }
            if (e.key === "Enter" || e.key === "Tab") { e.preventDefault(); this.chooseLink(this.suggest[this.pick]); return; }
            if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); this.suggest = []; return; }
          }
          if (e.key === "Tab") { e.preventDefault(); this.insert("  "); }
        },
        get draftKey() { return "work-note-draft:" + ME + ":" + (this.id || "new"); },
        init: function () {
          var draft = recall(this.draftKey, null), self = this;
          if (draft && draft.at > (initial.updated || 0) && (draft.body !== this.body || draft.title !== this.title)) {
            this.title = draft.title; this.body = draft.body; this.state = "dirty"; this.queue();
          }
          ["title", "body", "tags", "project"].forEach(function (k) { self.$watch(k, function () { self.changed(); }); });
          this.$watch("preview", function (on) { if (!on) self.$nextTick(function () { self.grow(); }); });
          this.$nextTick(function () { self.grow(); });
          window.addEventListener("beforeunload", function (e) { if (self.state === "dirty" || self.state === "saving") { self.saveNow(); } });
          this.$el.addEventListener("keydown", function (e) { if ((e.ctrlKey || e.metaKey) && e.key === "s") { e.preventDefault(); self.saveNow(); } });
        },
        changed: function () { this.state = "dirty"; store(this.draftKey, { title: this.title, body: this.body, at: Date.now() }); this.queue(); },
        queue: function () { clearTimeout(this.timer); var self = this; this.timer = setTimeout(function () { self.saveNow(); }, 900); },
        saveNow: function () {
          var self = this;
          if (!this.id && !this.title.trim() && !this.body.trim()) { this.state = "saved"; return; }
          // One save at a time: a second one before the first answers would make a new note twice.
          if (this.inflight) { this.again = true; return this.inflight; }
          this.state = "saving";
          var key = this.draftKey;
          this.inflight = api(CFG.urls.noteSave, { id: this.id || "", title: this.title, body: this.body, tags: this.tags, project: this.project }).then(function (res) {
            self.inflight = null;
            if (self.again) { self.again = false; if (res.ok && res.id) self.id = res.id; setTimeout(function () { self.saveNow(); }, 0); }
            if (!res.ok) { self.state = "error"; return; }
            if (res.queued) { self.state = "offline"; return; }
            store(key, null);
            if (!self.id && res.id) { self.id = res.id; history.replaceState(null, "", res.url); }
            self.savedAt = res.saved; self.state = "saved";
            var item = d.querySelector('[data-note-id="' + self.id + '"] .work-note-item-title'); if (item) item.textContent = res.title;
          });
          return this.inflight;
        },
        get html() { return renderMarkdown(this.body); },
        action: function (name) {
          var self = this;
          if (!this.id) return;
          api(CFG.urls.noteBase + this.id + "/", { action: name }).then(function (res) {
            if (name === "delete") { store(self.draftKey, null); undoable(t("noteDeleted", "Note deleted"), res.undo, function () { location.href = CFG.urls.notes + self.id + "/"; }); setTimeout(function () { location.href = CFG.urls.notes; }, 350); }
            else if (name === "to_task" && res.url) location.href = res.url;
            else if (name === "cards") {
              if (res.ok && !res.queued) toast(t("cardsMade", "Flashcards made") + ": " + res.count, "good", { label: t("seeCards", "See them"), run: function () { location.href = res.url; } });
              else if (!res.ok) toast(res.error || t("noPairs", ""), "warn");
            }
            else location.reload();
          });
        },
        insert: function (before, after) {
          var ta = this.$refs.body, s = ta.selectionStart, e = ta.selectionEnd, sel = this.body.slice(s, e);
          this.body = this.body.slice(0, s) + before + sel + (after || "") + this.body.slice(e);
          var self = this; this.$nextTick(function () { ta.focus(); ta.setSelectionRange(s + before.length, s + before.length + sel.length); self.grow(); });
        },
        /* "## ", "- ", "> "…: put a mark at the start of each chosen line, or take it off when every line has it */
        line: function (mark) {
          var ta = this.$refs.body, s = ta.selectionStart, e = ta.selectionEnd;
          var from = this.body.lastIndexOf("\n", s - 1) + 1, to = this.body.indexOf("\n", e); if (to < 0) to = this.body.length;
          var lines = this.body.slice(from, to).split("\n");
          var all = lines.every(function (l) { return l.indexOf(mark) === 0; });
          var out = lines.map(function (l) { return all ? l.slice(mark.length) : l.replace(/^(#{1,6} |[-*+] \[[ xX]\] |[-*+] |> )/, "") .replace(/^/, mark); }).join("\n");
          this.body = this.body.slice(0, from) + out + this.body.slice(to);
          // several lines chosen: keep them chosen, so the same button can take the marks off again
          var a = s === e ? from + out.length : from, z = from + out.length;
          var self = this; this.$nextTick(function () { ta.focus(); ta.setSelectionRange(a, z); self.grow(); });
        },
        /* The writing box grows with the note (the page scrolls, not the box) where CSS field-sizing can't do it */
        grow: function () {
          if (GROWS) return;
          var ta = this.$refs.body; if (!ta) return;
          ta.style.height = "auto"; ta.style.height = ta.scrollHeight + "px";
        },
        get words() { var m = this.body.match(/[^\s#>*`_\-\[\]()]+/g); return m ? m.length : 0; },
        get readMins() { return Math.max(1, Math.round(this.words / 200)); },
        get todoTotal() { return (this.body.match(/^[ \t]*[-*+][ \t]+\[[ xX]\]/gm) || []).length; },
        get todoDone() { return (this.body.match(/^[ \t]*[-*+][ \t]+\[[xX]\]/gm) || []).length; },
      };
    });

    /* ── Journal: autosave each box ───────────────────────────────────── */
    Alpine.data("workJournal", function (day) {
      return {
        state: "", timers: {},
        save: function (field, value) {
          var self = this; clearTimeout(this.timers[field]); this.state = "dirty";
          this.timers[field] = setTimeout(function () {
            self.state = "saving"; var data = { date: day }; data[field] = value;
            api(CFG.urls.journal, data).then(function (res) { self.state = res.queued ? "offline" : (res.ok ? "saved" : "error"); });
          }, 700);
        },
      };
    });

    /* ── Focus (Pomodoro) ─────────────────────────────────────────────── */
    Alpine.data("workFocus", function (opts) {
      var KEY = "work-focus:" + ME;
      return {
        mode: "focus", running: false, endsAt: 0, startedAt: 0, left: 0, done: 0, task: opts.task || "", taskTitle: opts.taskTitle || "",
        lengths: { focus: CFG.focus || 25, short: CFG.short || 5, long: CFG.long || 15 },
        init: function () {
          var saved = recall(KEY, null), self = this;
          if (saved) Object.assign(this, saved);
          if (!this.running) this.left = this.lengths[this.mode] * 60;
          setInterval(function () { self.step(); }, 250);
          d.addEventListener("keydown", function (e) { if (!typing(e) && e.code === "Space" && !e.ctrlKey) { e.preventDefault(); self.toggle(); } });
        },
        save: function () { store(KEY, { mode: this.mode, running: this.running, endsAt: this.endsAt, startedAt: this.startedAt, left: this.left, done: this.done, task: this.task, taskTitle: this.taskTitle }); },
        get total() { return this.lengths[this.mode] * 60; },
        get pct() { return 100 - Math.round(100 * this.left / this.total); },
        get text() { return clock(this.left); },
        step: function () {
          if (!this.running) return;
          var before = Math.ceil(this.left);
          this.left = Math.max(0, (this.endsAt - Date.now()) / 1000);
          if (CFG.tick && this.mode === "focus" && Math.ceil(this.left) !== before) tick();
          d.title = d.title.replace(/^[🍅☕] [^·]+ · /, "");
          d.title = (this.mode === "focus" ? "🍅 " : "☕ ") + clock(this.left) + " · " + d.title;
          if (this.left <= 0) this.finish();
        },
        start: function () {
          if (this.running) return;
          askNotify();
          this.running = true; this.endsAt = Date.now() + this.left * 1000;
          if (!this.startedAt) this.startedAt = Date.now();
          this.save();
        },
        pause: function () { if (!this.running) return; this.step(); this.running = false; this.save(); d.title = d.title.replace(/^[🍅☕] [^·]+ · /, ""); },
        toggle: function () { this.running ? this.pause() : this.start(); },
        reset: function () { this.running = false; this.startedAt = 0; this.left = this.total; this.save(); d.title = d.title.replace(/^[🍅☕] [^·]+ · /, ""); },
        set: function (mode) { this.mode = mode; this.reset(); },
        skip: function () { this.finish(true); },
        finish: function (skipped) {
          var was = this.mode, self = this;
          this.running = false; d.title = d.title.replace(/^[🍅☕] [^·]+ · /, "");
          if (was === "focus") {
            var started = new Date(this.startedAt || (Date.now() - this.total * 1000)), ended = new Date();
            if (!skipped || (ended - started) > 60000) {
              this.done += 1;
              api(CFG.urls.focus, { started_at: started.toISOString(), ended_at: ended.toISOString(), task: this.task || "", description: this.task ? "" : t("focusSession", "Focus session") })
                .then(function (res) { if (res.today != null) Alpine.store("timer").today = res.today; });
            }
            if (!skipped) { play(); notify(t("focusDone", "Focus session done"), t("takeBreak", "Time for a break."), location.pathname, "focus"); }
            this.mode = (this.done % (CFG.every || 4) === 0) ? "long" : "short";
          } else {
            if (!skipped) { play(); notify(t("breakOver", "Break's over"), t("backToWork", "Ready to focus again?"), location.pathname, "focus"); }
            this.mode = "focus";
          }
          this.startedAt = 0; this.left = this.total; this.save();
          var auto = this.mode === "focus" ? CFG.autoFocus : CFG.autoBreaks;
          if (auto && !skipped) setTimeout(function () { self.start(); }, 1200);
        },
        pick: function (e) { var o = e.target.selectedOptions[0]; this.task = e.target.value; this.taskTitle = o && e.target.value ? o.textContent.trim() : ""; this.save(); },
      };
    });
  });

  function match(hay, needle) {
    hay = hay.toLowerCase();
    return needle.split(/\s+/).every(function (w) {
      if (hay.indexOf(w) >= 0) return true;
      var i = 0; for (var k = 0; k < hay.length && i < w.length; k++) if (hay[k] === w[i]) i++;
      return i === w.length && w.length > 2;
    });
  }
  function copyText(text) {
    var done = function () { toast(t("copied", "Copied")); };
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(done, function () { prompt("", text); });
    else prompt("", text);
  }
  function isoDay(offset) { var x = new Date(); x.setDate(x.getDate() + (offset || 0)); return x.getFullYear() + "-" + pad(x.getMonth() + 1) + "-" + pad(x.getDate()); }

  /* ── Task rows: one handler for every row on the page ────────────────── */
  function rowOf(el) { return el && el.closest ? el.closest("[data-task]") : null; }
  function markTimer(taskId) {
    var id = taskId == null ? "" : String(taskId);
    d.querySelectorAll(".wt-play.is-on").forEach(function (b) { var r = rowOf(b); if (!r || r.getAttribute("data-task") !== id) b.classList.remove("is-on"); });
    if (id) d.querySelectorAll('[data-task="' + id + '"] .wt-play').forEach(function (b) { b.classList.add("is-on"); });
  }
  function freshRow(row, html) {
    var tmp = d.createElement("ul"); tmp.innerHTML = html;
    var fresh = tmp.firstElementChild; if (!fresh) return row;
    if (row.hasAttribute("data-hide-done")) fresh.setAttribute("data-hide-done", "");
    row.replaceWith(fresh);
    var tm = window.Alpine && Alpine.store("timer"); markTimer(tm && tm.running ? tm.running.task : null);
    return fresh;
  }
  function taskDone(row) {
    var id = row.getAttribute("data-task"), on = !row.classList.contains("is-done");
    row.classList.toggle("is-done", on);
    if (on) play(CFG.sound ? "chime" : "");
    api(CFG.urls.taskBase + id + "/done/", { done: on ? "1" : "0" }).then(function (res) {
      if (res.next && res.next.html) { row.insertAdjacentHTML("afterend", res.next.html); toast(t("repeatMade", "Next one added") + (res.next.due ? " · " + res.next.due : "")); }
      if (on) { var tm = window.Alpine && Alpine.store("timer"); if (tm && tm.isFor(id)) { tm.running = null; tm.share(); tm.sync(); } }
    });
    if (on && row.hasAttribute("data-hide-done")) setTimeout(function () { row.classList.add("is-leaving"); setTimeout(function () { row.remove(); }, 260); }, 700);
  }
  function taskTimer(row) {
    var tm = window.Alpine && Alpine.store("timer"); if (!tm) return;
    var id = row.getAttribute("data-task");
    if (tm.isFor(id)) tm.stop(); else tm.start({ task: id, label: row.getAttribute("data-title"), project: row.getAttribute("data-project") });
  }
  function taskUpdate(row, field, value) {
    var data = {}; data[field] = value;
    return api(CFG.urls.taskBase + row.getAttribute("data-task") + "/update/", data).then(function (res) {
      if (res.ok && res.html && row.isConnected) freshRow(row, res.html);
      return res;
    });
  }
  function taskDelete(row) {
    row.classList.add("is-leaving");
    api(CFG.urls.taskBase + row.getAttribute("data-task") + "/delete/", {}).then(function (res) {
      setTimeout(function () { row.remove(); }, 250);
      undoable(t("taskDeleted", "Task deleted"), res.undo);
    });
  }

  var menu = null, menuRow = null, menuBtn = null, menuAt = 0;
  function closeMenu(refocus) {
    if (!menu || menu.hidden) return;
    menu.hidden = true;
    if (refocus && menuBtn) menuBtn.focus({ preventScroll: true });
    menuRow = menuBtn = null;
  }
  function openMenu(btn) {
    menu = menu || d.getElementById("work-task-menu");
    var row = rowOf(btn); if (!menu || !row) return;
    if (menuRow === row && !menu.hidden) return closeMenu();
    menuRow = row; menuBtn = btn; menuAt = Date.now();
    var label = function (name, on) { var el = menu.querySelector('[data-menu="' + name + '"] span'); el.textContent = el.getAttribute(on ? "data-label-on" : "data-label-off"); };
    label("myday", row.hasAttribute("data-myday"));
    label("doing", row.getAttribute("data-status") === "doing");
    label("waiting", row.hasAttribute("data-waiting"));
    menu.querySelectorAll("[data-menu-form]").forEach(function (f) { f.hidden = true; });
    menu.querySelector("[data-needs-link]").hidden = !row.getAttribute("data-link");
    menu.hidden = false;
    var r = btn.getBoundingClientRect(), w = menu.offsetWidth, h = menu.offsetHeight;
    var top = r.bottom + 4; if (top + h > innerHeight - 8) top = Math.max(8, r.top - h - 4);
    menu.style.left = Math.min(Math.max(8, r.right - w), innerWidth - w - 8) + "px"; menu.style.top = top + "px";
    var first = menu.querySelector(".menu-item"); if (first) first.focus({ preventScroll: true });
  }
  function menuAction(row, name, value) {
    var id = row.getAttribute("data-task"), link = row.getAttribute("data-link") || "";
    if (name === "myday") taskUpdate(row, "my_day", row.hasAttribute("data-myday") ? "0" : "1");
    else if (name === "today") taskUpdate(row, "due_date", isoDay(0));
    else if (name === "tomorrow") taskUpdate(row, "due_date", isoDay(1));
    else if (name === "doing") taskUpdate(row, "status", row.getAttribute("data-status") === "doing" ? "todo" : "doing");
    else if (name === "prio") taskUpdate(row, "priority", value);
    else if (name === "waiting") taskUpdate(row, "waiting_for", "");
    else if (name === "open-link" && link) window.open(link, "_blank", "noopener");
    else if (name === "copy") copyText(row.getAttribute("data-title") + (link ? " " + link : ""));
    else if (name === "time") location.href = CFG.urls.entry_new + "?task=" + id;
    else if (name === "focus") location.href = CFG.urls.focus_page + "?task=" + id;
    else if (name === "delete") taskDelete(row);
  }
  d.addEventListener("click", function (e) {
    var item = e.target.closest("[data-menu]");
    if (item && menu && menu.contains(item)) {
      if (item.getAttribute("data-menu") === "later" && menuRow) {   // pick the day, right in the menu
        var lf = menu.querySelector("[data-menu-form=later]"); lf.hidden = false;
        lf.querySelector("input").min = isoDay(1); lf.querySelector("input").value = isoDay(1); lf.querySelector("[data-later]").focus(); return;
      }
      if (item.getAttribute("data-menu") === "waiting" && menuRow && !menuRow.hasAttribute("data-waiting")) {   // ask who, right in the menu
        var wf = menu.querySelector("[data-menu-form=waiting]"); wf.hidden = false; wf.querySelector("input").value = ""; wf.querySelector("input").focus(); return;
      }
      var row = menuRow; closeMenu(); if (row) menuAction(row, item.getAttribute("data-menu"), item.getAttribute("data-value")); return;
    }
    var quick = e.target.closest("[data-later]");
    if (quick && menu && menu.contains(quick)) { var qrow = menuRow; closeMenu(); if (qrow) later(qrow, isoDay(+quick.getAttribute("data-later"))); return; }
    var act = e.target.closest("[data-act]"), target = act && rowOf(act);
    if (target && act.getAttribute("data-act") === "done" && target.closest(".is-selecting")) { e.preventDefault(); pick(target, e.shiftKey); return; }
    if (target) {
      e.preventDefault();
      var a = act.getAttribute("data-act");
      if (a === "done") taskDone(target); else if (a === "timer") taskTimer(target); else if (a === "menu") openMenu(act);
      return;
    }
    if (menu && !menu.hidden && !menu.contains(e.target)) closeMenu();
  });
  d.addEventListener("keydown", function (e) {
    if (!menu || menu.hidden) return;
    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); closeMenu(true); return; }
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      var all = Array.prototype.slice.call(menu.querySelectorAll("button:not([hidden])")), i = all.indexOf(d.activeElement);
      e.preventDefault(); all[(i + (e.key === "ArrowDown" ? 1 : -1) + all.length) % all.length].focus();
    }
  }, true);
  window.addEventListener("scroll", function (e) {   // the page scrolled away from the row (not the menu itself, nor the scroll that brought the row into view)
    if (menu && !menu.contains(e.target) && Date.now() - menuAt > 250) closeMenu();
  }, { passive: true, capture: true });
  window.addEventListener("resize", function () { closeMenu(); });
  function later(row, day) {          // snooze: out of sight until that day (a due date that has come moves along)
    var id = row.getAttribute("data-task"), leave = !!row.closest("[data-today-list]") || row.hasAttribute("data-hide-done");
    api(CFG.urls.taskBase + id + "/update/", { my_day: day, later: "1" }).then(function (res) {
      if (!res.ok) return;
      toast(t("later", "Moved to") + " " + new Date(day + "T00:00").toLocaleDateString(d.documentElement.lang || undefined, { weekday: "short", day: "numeric", month: "short" }));
      var cur = d.querySelector('.wt-task[data-task="' + id + '"]') || row;
      if (leave) { cur.classList.add("is-leaving"); setTimeout(function () { cur.remove(); }, 260); }
      else if (res.html && cur.isConnected) freshRow(cur, res.html);
    });
  }
  d.addEventListener("submit", function (e) {
    var lf = e.target.closest("[data-menu-form=later]");
    if (lf) { e.preventDefault(); var lrow = menuRow, day = lf.querySelector("input").value; closeMenu(); if (lrow && day) later(lrow, day); return; }
    var wf = e.target.closest("[data-menu-form=waiting]"); if (!wf) return;
    e.preventDefault();
    var who = wf.querySelector("input").value.trim(), row = menuRow; closeMenu();
    if (row && who) taskUpdate(row, "waiting_for", who);
  });

  /* ── Phones: swipe a task right for done, left for tomorrow ─────────── */
  (function () {
    if (!("ontouchstart" in window)) return;
    var sw = null, LIMIT = 84;
    function reset(row) { row.classList.remove("is-swiping"); row.style.removeProperty("--sx"); row.removeAttribute("data-swipe"); row.removeAttribute("data-later-label"); }
    d.addEventListener("touchstart", function (e) {
      var row = e.target.closest && e.target.closest(".wt-task");
      if (!row || e.touches.length !== 1 || row.closest(".is-selecting") || e.target.closest("input, textarea, .menu")) { sw = null; return; }
      sw = { row: row, x: e.touches[0].clientX, y: e.touches[0].clientY, dx: 0, on: false };
    }, { passive: true });
    d.addEventListener("touchmove", function (e) {
      if (!sw) return;
      var dx = e.touches[0].clientX - sw.x, dy = e.touches[0].clientY - sw.y;
      if (!sw.on) {
        if (Math.abs(dy) > 12 && Math.abs(dy) > Math.abs(dx)) { sw = null; return; }      // scrolling the page
        if (Math.abs(dx) < 14 || Math.abs(dx) < Math.abs(dy) * 1.5) return;
        sw.on = true; sw.row.classList.add("is-swiping"); sw.row.setAttribute("data-later-label", t("tomorrow", "Tomorrow"));
      }
      e.preventDefault();
      if (dx > 0 && sw.row.classList.contains("is-done")) dx = Math.min(dx, 24);
      sw.dx = Math.max(-130, Math.min(130, dx));
      sw.row.style.setProperty("--sx", sw.dx + "px");
      sw.row.setAttribute("data-swipe", sw.dx > 0 ? "done" : "later");
      sw.row.classList.toggle("is-armed", Math.abs(sw.dx) >= LIMIT);
    }, { passive: false });
    function end() {
      if (!sw) return;
      var cur = sw; sw = null;
      if (!cur.on) return;
      var row = cur.row, armed = Math.abs(cur.dx) >= LIMIT;
      row.classList.remove("is-armed"); reset(row);
      if (!armed) return;
      if (navigator.vibrate) { try { navigator.vibrate(12); } catch (err) { /* fine */ } }
      if (cur.dx > 0) taskDone(row); else later(row, isoDay(1));
      var stop = function (ev) { ev.preventDefault(); ev.stopPropagation(); };   // the finger lifting isn't a tap on the row
      row.addEventListener("click", stop, { capture: true, once: true });
      setTimeout(function () { row.removeEventListener("click", stop, { capture: true }); }, 400);
    }
    d.addEventListener("touchend", end, { passive: true });
    d.addEventListener("touchcancel", function () { if (sw) { reset(sw.row); sw = null; } }, { passive: true });
  })();

  /* ── Select many tasks (the task list's "Select" mode) ─────────────────── */
  var lastPicked = null;
  function bulkRoot() { return d.querySelector("[data-bulk-root]"); }
  function bulkCount() {
    var root = bulkRoot(); if (!root) return;
    var n = root.querySelectorAll(".wt-task.is-selected").length, bar = d.querySelector("[data-bulkbar]");
    if (bar) { bar.querySelector("[data-bulk-count]").textContent = n; bar.classList.toggle("has-some", n > 0); }
  }
  function bulkMode(on) {
    var root = bulkRoot(), bar = d.querySelector("[data-bulkbar]"); if (!root || !bar) return;
    root.classList.toggle("is-selecting", on); bar.hidden = !on;
    d.querySelectorAll("[data-bulk-toggle]").forEach(function (b) { b.setAttribute("aria-pressed", on ? "true" : "false"); });
    if (!on) root.querySelectorAll(".wt-task.is-selected").forEach(function (r) { r.classList.remove("is-selected"); });
    lastPicked = null; bulkCount();
  }
  function pick(row, shift) {
    var rows = Array.prototype.filter.call(bulkRoot().querySelectorAll(".wt-task"), function (r) { return r.offsetParent !== null; });
    var on = !row.classList.contains("is-selected");
    if (shift && lastPicked && rows.indexOf(lastPicked) >= 0) {
      var a = rows.indexOf(lastPicked), b = rows.indexOf(row);
      rows.slice(Math.min(a, b), Math.max(a, b) + 1).forEach(function (r) { r.classList.toggle("is-selected", on); });
    } else row.classList.toggle("is-selected", on);
    lastPicked = row; bulkCount();
  }
  function bulkRun(action, value) {
    var ids = Array.prototype.map.call(bulkRoot().querySelectorAll(".wt-task.is-selected"), function (r) { return r.getAttribute("data-task"); });
    if (!ids.length) { toast(t("pickSome", "Select some tasks first."), "warn"); return; }
    if (action === "delete" && !confirm(t("confirmBulkDelete", "Delete the selected tasks?"))) return;
    if (action === "done") play(CFG.sound ? "chime" : "");
    api(CFG.urls.taskBulk, { ids: ids.join(","), action: action, value: value || "" }).then(function (res) {
      if (!res.ok) { toast(res.error || t("notSaved", "Not saved."), "warn"); return; }
      toast(t("changed", "Updated") + (res.count ? " · " + res.count : ""));
      if (!res.queued) setTimeout(function () { location.reload(); }, 350);
    });
  }
  d.addEventListener("click", function (e) {
    var el = e.target.closest("[data-bulk-toggle], [data-bulk-cancel], [data-bulk-all], button[data-bulk]");
    if (!el) return;
    if (el.hasAttribute("data-bulk-toggle")) bulkMode(!bulkRoot().classList.contains("is-selecting"));
    else if (el.hasAttribute("data-bulk-cancel")) bulkMode(false);
    else if (el.hasAttribute("data-bulk-all")) {
      var rows = Array.prototype.filter.call(bulkRoot().querySelectorAll(".wt-task"), function (r) { return r.offsetParent !== null; });
      var all = rows.every(function (r) { return r.classList.contains("is-selected"); });
      rows.forEach(function (r) { r.classList.toggle("is-selected", !all); }); bulkCount();
    } else bulkRun(el.getAttribute("data-bulk"));
  });
  d.addEventListener("change", function (e) {
    var sel = e.target.closest("select[data-bulk]"); if (!sel || !sel.value) return;
    var action = sel.getAttribute("data-bulk"), v = sel.value;
    if (action === "due") v = { today: isoDay(0), tomorrow: isoDay(1), week: isoDay(7), none: "" }[v];
    if (v === "none") v = "";
    bulkRun(action, v); sel.value = "";
  });
  window.Work.taskUpdate = taskUpdate;

  /* ── Ctrl+K: the palette (instead of the app-wide search, while here) ── */
  window.addEventListener("keydown", function (e) {
    if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && (e.key || "").toLowerCase() === "k") {
      e.preventDefault(); e.stopPropagation(); d.dispatchEvent(new CustomEvent("work:palette"));
    }
  }, true);

  /* ── Idle time: the computer slept, the browser was closed, or (with the
   *    browser's permission) nobody touched the computer for a while ────── */
  (function () {
    var BEAT = "work-beat:" + ME, mins = CFG.idle || 0;
    if (!mins) return;
    var limit = mins * 60000, asked = false;
    function running() { var tm = window.Alpine && Alpine.store("timer"); return tm && tm.running ? new Date(tm.running.started_at).getTime() : 0; }
    function ask(since, until) {
      var started = running();
      if (asked || !started || since <= started) return;
      asked = true; d.dispatchEvent(new CustomEvent("work:idle", { detail: { since: since, until: until } }));
    }
    function beat() {
      var now = Date.now(), last = recall(BEAT, 0);
      if (last && now - last > limit) ask(last, now);     // a gap: asleep or closed
      store(BEAT, now);
    }
    d.addEventListener("alpine:initialized", function () { setTimeout(beat, 300); setInterval(beat, 20000); });
    d.addEventListener("visibilitychange", function () { if (!d.hidden) beat(); });
    d.addEventListener("work:timer", function () { asked = false; });
    // Away from the keyboard: Chrome's idle detection, once allowed in Settings.
    if ("IdleDetector" in window && navigator.permissions) {
      navigator.permissions.query({ name: "idle-detection" }).then(function (p) {
        if (p.state !== "granted") return;
        var det = new IdleDetector(), idleSince = 0;
        det.addEventListener("change", function () {
          if (det.userState === "idle") idleSince = Date.now() - Math.max(limit, 60000);
          else if (idleSince) { var since = idleSince; idleSince = 0; ask(since, Date.now()); }
        });
        det.start({ threshold: Math.max(limit, 60000) }).catch(function () {});
      }).catch(function () {});
    }
    window.Work.allowIdle = function () {
      return ("IdleDetector" in window) ? IdleDetector.requestPermission() : Promise.resolve("unsupported");
    };
  })();

  /* ── A focus session running on another page still ends on time ─────── */
  (function () {
    var KEY = "work-focus:" + ME;
    if (d.querySelector("[data-focus-page]")) return;
    setInterval(function () {
      var f = recall(KEY, null);
      if (!f || !f.running || Date.now() < f.endsAt) return;
      f.running = false; f.left = 0; store(KEY, f);
      play(); notify(f.mode === "focus" ? t("focusDone", "Focus session done") : t("breakOver", "Break's over"), "", CFG.urls.focus_page, "focus");
      var bar = d.querySelector("[data-focus-pill]"); if (bar) bar.hidden = true;
    }, 1000);
  })();

  /* ── Markdown (notes, task notes) ───────────────────────────────────── */
  function wikiLinks(text) {      // [[Note title]] → a link that opens (or starts) that note
    if (!CFG.urls || !CFG.urls.noteGo) return text;
    return (text || "").replace(/\[\[([^\[\]\n]{1,200})\]\]/g, function (all, title) {
      return "[" + title.replace(/([\\*_`])/g, "\\$1") + "](" + CFG.urls.noteGo + "?title=" + encodeURIComponent(title.trim()).replace(/\(/g, "%28").replace(/\)/g, "%29") + ")";
    });
  }
  function renderMarkdown(text) {
    text = wikiLinks(text);
    if (window.marked && window.DOMPurify) {
      var html = marked.parse(text || "", { gfm: true, breaks: true });
      return DOMPurify.sanitize(html);
    }
    var esc = (text || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    return "<p>" + esc.replace(/\n\n+/g, "</p><p>").replace(/\n/g, "<br>") + "</p>";
  }
  window.Work.markdown = renderMarkdown;

  /* ── Mermaid: diagrams written as text (Diagrams, and ```mermaid blocks in notes) ── */
  var MERMAID = "https://cdn.jsdelivr.net/npm/mermaid@11.4.1/dist/mermaid.min.js", mermaidLoading = null, mermaidTheme = "";
  window.Work.loadMermaid = function () {
    if (window.mermaid && mermaidTheme) return Promise.resolve(window.mermaid);
    if (!mermaidLoading) mermaidLoading = new Promise(function (resolve, reject) {
      var s = d.createElement("script"); s.src = MERMAID; s.async = true;
      s.onload = function () { mermaidTheme = ""; Work.mermaidTheme(root.getAttribute("data-theme") === "dark" ? "dark" : "default"); resolve(window.mermaid); };
      s.onerror = function () { mermaidLoading = null; s.remove(); reject(new Error("mermaid-load")); };
      d.head.appendChild(s);
    });
    return mermaidLoading;
  };
  // Strict: no clicks or scripts from the text; plain SVG labels, so a picture can be exported.
  window.Work.mermaidTheme = function (theme, look) {
    var key = theme + "/" + (look || "");
    if (!window.mermaid || mermaidTheme === key) return;
    mermaidTheme = key;
    // The app's own colours (teal ink on paper; light text on deep green in the dark).
    var dark = theme === "dark", vars = dark ? {
      darkMode: true, background: "#16201c", primaryColor: "#1f3a33", primaryTextColor: "#e8efe9", primaryBorderColor: "#3fbfa8",
      secondaryColor: "#2a2f45", tertiaryColor: "#3a2f1f", lineColor: "#9fb3ab", textColor: "#e8efe9", mainBkg: "#1f3a33", nodeBorder: "#3fbfa8",
      clusterBkg: "#1b2925", clusterBorder: "#4d6b62", edgeLabelBackground: "#16201c", noteBkgColor: "#4a3f16", noteTextColor: "#f6e7a6", noteBorderColor: "#7a6421",
      actorBkg: "#1f3a33", actorBorder: "#3fbfa8", actorTextColor: "#e8efe9", signalColor: "#cfdcd6", signalTextColor: "#e8efe9", labelBoxBkgColor: "#1f3a33",
    } : {
      primaryColor: "#e2efe9", primaryTextColor: "#1f2a24", primaryBorderColor: "#0f5c4d", secondaryColor: "#e7e8f6", tertiaryColor: "#fff4e0",
      lineColor: "#5b6b64", textColor: "#1f2a24", mainBkg: "#e2efe9", nodeBorder: "#0f5c4d", clusterBkg: "#f4f7f5", clusterBorder: "#9fb3ab",
      edgeLabelBackground: "#ffffff", noteBkgColor: "#fff4bf", noteTextColor: "#5c4a00", noteBorderColor: "#f0c36d",
      actorBkg: "#e2efe9", actorBorder: "#0f5c4d", actorTextColor: "#1f2a24", signalColor: "#33413b", signalTextColor: "#1f2a24", labelBoxBkgColor: "#e2efe9",
    };
    vars.fontFamily = "system-ui, -apple-system, 'Segoe UI', Roboto, 'Noto Sans Bengali', sans-serif"; vars.fontSize = "15px";
    mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: "base", themeVariables: vars, htmlLabels: false, look: look || "classic",
                         flowchart: { htmlLabels: false, curve: "basis" }, gantt: { useWidth: 960 } });
  };
  var mermaidSeq = 0;
  // Every ```mermaid block inside `el` becomes its diagram (a mistake shows as the text with a note).
  window.Work.mermaidIn = function (el) {
    var blocks = el ? el.querySelectorAll("pre > code.language-mermaid") : [];
    if (!blocks.length) return Promise.resolve();
    return Work.loadMermaid().then(function (mm) {
      Work.mermaidTheme(root.getAttribute("data-theme") === "dark" ? "dark" : "default");
      return Array.prototype.reduce.call(blocks, function (p, code) {
        return p.then(function () {
          var id = "wmn-" + (++mermaidSeq), box = d.createElement("div");
          box.className = "wn-mermaid";
          return mm.render(id, code.textContent).then(function (res) { box.innerHTML = res.svg; code.parentNode.replaceWith(box); })
            .catch(function () { code.parentNode.classList.add("is-bad-diagram"); d.querySelectorAll("#d" + id + ", #" + id).forEach(function (n) { n.remove(); }); });
        });
      }, Promise.resolve());
    }).catch(function () { /* offline and never loaded: the text stays */ });
  };
  d.addEventListener("DOMContentLoaded", function () {
    d.querySelectorAll("[data-render-markdown]").forEach(function (el) {
      var draw = function () {
        el.innerHTML = renderMarkdown(el.getAttribute("data-render-markdown"));
        Work.mermaidIn(el);
        if (window.hljs) el.querySelectorAll("pre code:not(.language-mermaid)").forEach(function (c) { hljs.highlightElement(c); });
      };
      if (window.marked) draw(); else setTimeout(draw, 300);
    });
  });

  /* ── Quick-add preview chips: what "#tag @project !high tomorrow" means ── */
  function parseChips(text) {
    var out = [];
    text = text || "";
    var every = /\bevery\s+(day|weekday|workday|work\s+day|week|month|mon(day)?|tue(sday)?|wed(nesday)?|thu(rsday)?|fri(day)?|sat(urday)?|sun(day)?)\b/i.exec(text);
    if (every) { out.push({ k: "repeat", v: "↻ " + every[0].toLowerCase() }); text = text.replace(every[0], " "); }
    var at = /\bat\s+(\d{1,2}(:\d{2})?\s*(am|pm)?)\b/i.exec(text);
    if (at && (at[2] || at[3])) { out.push({ k: "remind", v: "⏰ " + at[1] }); text = text.replace(at[0], " "); }
    text.split(/\s+/).forEach(function (w) {
      var low = w.toLowerCase();
      if (/^\d{1,2}(:\d{2})?(am|pm)$|^\d{1,2}:\d{2}$/.test(low)) { out.push({ k: "remind", v: "⏰ " + low }); return; }
      if (/^snooze:\S+/.test(low)) { out.push({ k: "later", v: "💤 " + low.slice(7) }); return; }
      if (/^#[^\s\d#]/.test(w)) out.push({ k: "tag", v: w });
      else if (/^@\S/.test(w)) out.push({ k: "project", v: w.slice(1).replace(/_/g, " ") });
      else if (/^!(urgent|high|medium|med|low|[1-4])$/.test(low)) out.push({ k: "priority", v: low.slice(1) });
      else if (/^~\d+(\.\d+)?(m|min|h|hr)?$/.test(low)) out.push({ k: "estimate", v: low.slice(1) });
      else if (w === "*") out.push({ k: "myday", v: t("myDay", "My Day") });
      else if (/^https?:\/\/\S+\.\S+/.test(w)) out.push({ k: "link", v: t("link", "Link") });
      else if (/^(today|tomorrow|tmr|nextweek|monday|tuesday|wednesday|thursday|friday|saturday|sunday)$/.test(low) || /^\+\d{1,3}[dw]$/.test(low) || /^\d{4}-\d{2}-\d{2}$/.test(low) || /^due:\S+/.test(low)) out.push({ k: "due", v: low.replace(/^due:/, "") });
    });
    return out;
  }
  window.Work.parseChips = parseChips;

  /* ── Keyboard: the whole module without a mouse ─────────────────────── */
  var pending = null;
  var GO = { h: "today", t: "tasks", b: "board", p: "projects", i: "time", f: "focus_page", n: "notes", s: "snippets", a: "habits", j: "journal", r: "reports", ",": "settings",
             c: "calendar", o: "goals", l: "learning", v: "review", d: "plan", w: "week", m: "diagrams", k: "cards" };
  d.addEventListener("keydown", function (e) {
    if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey || typing(e)) return;
    var k = e.key;
    if (pending === "g") {
      pending = null;
      var where = GO[k.toLowerCase()];
      if (where && CFG.urls[where]) { e.preventDefault(); location.href = CFG.urls[where]; }
      return;
    }
    if (k === "g") { pending = "g"; setTimeout(function () { pending = null; }, 1200); return; }
    var focused = rowOf(d.activeElement);
    if (k === "j" || k === "k" || k === "ArrowDown" && focused || k === "ArrowUp" && focused) {
      var rows = Array.prototype.filter.call(d.querySelectorAll(".wt-task"), function (r) { return r.offsetParent !== null; });
      if (!rows.length) return;
      var down = k === "j" || k === "ArrowDown", i = rows.indexOf(focused);
      i = i < 0 ? (down ? 0 : rows.length - 1) : Math.max(0, Math.min(rows.length - 1, i + (down ? 1 : -1)));
      e.preventDefault(); rows[i].querySelector(".wt-task-title").focus(); rows[i].scrollIntoView({ block: "nearest" });
      return;
    }
    if (focused && (k === "x" || k === "p" || k === "m" || k === "e")) {
      e.preventDefault();
      if (k === "x") { if (focused.closest(".is-selecting")) pick(focused, e.shiftKey); else taskDone(focused); } else if (k === "p") taskTimer(focused);
      else if (k === "m") openMenu(focused.querySelector('[data-act="menu"]')); else location.href = focused.querySelector(".wt-task-title").href;
      return;
    }
    if (k === "c" || k === "t") { e.preventDefault(); d.dispatchEvent(new CustomEvent("work:capture", { detail: "task" })); }
    else if (k === "n") { e.preventDefault(); d.dispatchEvent(new CustomEvent("work:capture", { detail: "note" })); }
    else if (k === "s" && window.Alpine) { e.preventDefault(); var tm = Alpine.store("timer"); tm.running ? tm.stop() : d.dispatchEvent(new CustomEvent("work:capture", { detail: "time" })); }
    else if (k === "/") {
      var box = d.querySelector("[data-work-search]"); e.preventDefault(); e.stopPropagation();
      if (box) { box.focus(); if (box.select) box.select(); } else d.dispatchEvent(new CustomEvent("work:palette"));
    }
    else if (k === "?") { e.preventDefault(); d.dispatchEvent(new CustomEvent("work:help")); }
  });

  d.addEventListener("DOMContentLoaded", function () { badge(); flush(); });

  /* ── Looks: start sideways strips at today, stagger lists in ─────────── */
  // A strip of days (habits, the year's heatmap) opens at its newest end — today.
  function scrollEnds(scope) {
    (scope || d).querySelectorAll("[data-scroll-end]").forEach(function (el) { el.scrollLeft = el.scrollWidth; });
  }
  // Browsers without sibling-index() get each row's place as --i for the stagger delay (see work.css "Motion").
  var STAGGER = ".work > *, .wt-list > .wt-task, .wn-items > li, .we-list > li, .wg-grid > *, .wpj-grid > *, .wl-grid > *, .wsn-list > *, .wh-today > *, .wwk-days > *";
  var HAS_INDEX = !!(window.CSS && CSS.supports && CSS.supports("animation-delay: calc(sibling-index() * 1s)"));
  function staggerIndex(scope) {
    if (HAS_INDEX) return;
    (scope || d).querySelectorAll(STAGGER).forEach(function (el) {
      var i = 1, n = el; while ((n = n.previousElementSibling) && i < 14) i++;
      el.style.setProperty("--i", i);
    });
  }
  d.addEventListener("DOMContentLoaded", function () { scrollEnds(); staggerIndex(); });
})();
