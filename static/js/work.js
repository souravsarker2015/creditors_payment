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
    return el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName));
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
          d.addEventListener("work:capture", function (e) { self.show(e.detail || "task"); });
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
            } else if (self.mode === "note") { toast(t("noteSaved", "Note saved")); }
            if (!self.keepOpen) self.hide();
          });
        },
        myDay: false, keepOpen: false,
      };
    });

    /* ── Tasks: tick off, edit inline, My Day, delete with undo ───────── */
    Alpine.data("workTasks", function () {
      return {
        init: function () {
          var self = this;
          d.addEventListener("work:task-added", function (e) {
            var list = self.$root.querySelector("[data-new-tasks]");
            if (list && e.detail.html) { list.insertAdjacentHTML("afterbegin", e.detail.html); list.closest("[data-empty-wrap]") && list.closest("[data-empty-wrap]").classList.add("has-items"); }
          });
        },
        done: function (id, el) {
          var row = el.closest("[data-task]"), on = !row.classList.contains("is-done");
          row.classList.toggle("is-done", on);
          if (on) play(CFG.sound ? "chime" : "");
          api(CFG.urls.taskBase + id + "/done/", { done: on ? "1" : "0" }).then(function (res) {
            if (res.next && res.next.html) { row.insertAdjacentHTML("afterend", res.next.html); toast(t("repeatMade", "Next one added") + (res.next.due ? " · " + res.next.due : "")); }
          });
          if (on && row.hasAttribute("data-hide-done")) setTimeout(function () { row.classList.add("is-leaving"); setTimeout(function () { row.remove(); }, 260); }, 700);
        },
        update: function (id, field, value, el) {
          var data = {}; data[field] = value;
          return api(CFG.urls.taskBase + id + "/update/", data).then(function (res) {
            if (res.ok && res.html && el) { var row = el.closest("[data-task]"); if (row) row.outerHTML = res.html; }
            return res;
          });
        },
        rename: function (id, el) {
          var text = el.textContent.trim();
          if (!text) { el.textContent = el.getAttribute("data-was"); return; }
          if (text !== el.getAttribute("data-was")) { el.setAttribute("data-was", text); this.update(id, "title", text); }
        },
        remove: function (id, el) {
          var row = el.closest("[data-task]"); row.classList.add("is-leaving");
          api(CFG.urls.taskBase + id + "/delete/", {}).then(function (res) {
            setTimeout(function () { row.remove(); }, 250);
            undoable(t("taskDeleted", "Task deleted"), res.undo);
          });
        },
        timer: function (id, label, project) { var tm = Alpine.store("timer"); return tm.isFor(id) ? tm.stop() : tm.start({ task: id, label: label, project: project }); },
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
        state: "saved", savedAt: initial.saved || "", preview: false, timer: null,
        get draftKey() { return "work-note-draft:" + ME + ":" + (this.id || "new"); },
        init: function () {
          var draft = recall(this.draftKey, null), self = this;
          if (draft && draft.at > (initial.updated || 0) && (draft.body !== this.body || draft.title !== this.title)) {
            this.title = draft.title; this.body = draft.body; this.state = "dirty"; this.queue();
          }
          ["title", "body", "tags", "project"].forEach(function (k) { self.$watch(k, function () { self.changed(); }); });
          window.addEventListener("beforeunload", function (e) { if (self.state === "dirty" || self.state === "saving") { self.saveNow(); } });
          this.$el.addEventListener("keydown", function (e) { if ((e.ctrlKey || e.metaKey) && e.key === "s") { e.preventDefault(); self.saveNow(); } });
        },
        changed: function () { this.state = "dirty"; store(this.draftKey, { title: this.title, body: this.body, at: Date.now() }); this.queue(); },
        queue: function () { clearTimeout(this.timer); var self = this; this.timer = setTimeout(function () { self.saveNow(); }, 900); },
        saveNow: function () {
          var self = this;
          if (!this.id && !this.title.trim() && !this.body.trim()) { this.state = "saved"; return; }
          this.state = "saving";
          var key = this.draftKey;
          return api(CFG.urls.noteSave, { id: this.id || "", title: this.title, body: this.body, tags: this.tags, project: this.project }).then(function (res) {
            if (!res.ok) { self.state = "error"; return; }
            if (res.queued) { self.state = "offline"; return; }
            store(key, null);
            if (!self.id && res.id) { self.id = res.id; history.replaceState(null, "", res.url); }
            self.savedAt = res.saved; self.state = "saved";
            var item = d.querySelector('[data-note-id="' + self.id + '"] .work-note-item-title'); if (item) item.textContent = res.title;
          });
        },
        get html() { return renderMarkdown(this.body); },
        action: function (name) {
          var self = this;
          if (!this.id) return;
          api(CFG.urls.noteBase + this.id + "/", { action: name }).then(function (res) {
            if (name === "delete") { store(self.draftKey, null); undoable(t("noteDeleted", "Note deleted"), res.undo, function () { location.href = CFG.urls.notes + self.id + "/"; }); setTimeout(function () { location.href = CFG.urls.notes; }, 350); }
            else if (name === "to_task" && res.url) location.href = res.url;
            else location.reload();
          });
        },
        insert: function (before, after) {
          var ta = this.$refs.body, s = ta.selectionStart, e = ta.selectionEnd, sel = this.body.slice(s, e);
          this.body = this.body.slice(0, s) + before + sel + (after || "") + this.body.slice(e);
          var self = this; this.$nextTick(function () { ta.focus(); ta.setSelectionRange(s + before.length, s + before.length + sel.length); });
        },
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
  function renderMarkdown(text) {
    if (window.marked && window.DOMPurify) {
      var html = marked.parse(text || "", { gfm: true, breaks: true });
      return DOMPurify.sanitize(html);
    }
    var esc = (text || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    return "<p>" + esc.replace(/\n\n+/g, "</p><p>").replace(/\n/g, "<br>") + "</p>";
  }
  window.Work.markdown = renderMarkdown;
  d.addEventListener("DOMContentLoaded", function () {
    d.querySelectorAll("[data-render-markdown]").forEach(function (el) {
      var draw = function () { el.innerHTML = renderMarkdown(el.getAttribute("data-render-markdown")); if (window.hljs) el.querySelectorAll("pre code").forEach(function (c) { hljs.highlightElement(c); }); };
      if (window.marked) draw(); else setTimeout(draw, 300);
    });
  });

  /* ── Quick-add preview chips: what "#tag @project !high tomorrow" means ── */
  function parseChips(text) {
    var out = [];
    (text || "").split(/\s+/).forEach(function (w) {
      var low = w.toLowerCase();
      if (/^#[^\s\d#]/.test(w)) out.push({ k: "tag", v: w });
      else if (/^@\S/.test(w)) out.push({ k: "project", v: w.slice(1).replace(/_/g, " ") });
      else if (/^!(urgent|high|medium|med|low|[1-4])$/.test(low)) out.push({ k: "priority", v: low.slice(1) });
      else if (/^~\d+(\.\d+)?(m|min|h|hr)?$/.test(low)) out.push({ k: "estimate", v: low.slice(1) });
      else if (w === "*") out.push({ k: "myday", v: t("myDay", "My Day") });
      else if (/^(today|tomorrow|tmr|nextweek|monday|tuesday|wednesday|thursday|friday|saturday|sunday)$/.test(low) || /^\+\d{1,3}[dw]$/.test(low) || /^\d{4}-\d{2}-\d{2}$/.test(low) || /^due:\S+/.test(low)) out.push({ k: "due", v: low.replace(/^due:/, "") });
    });
    return out;
  }
  window.Work.parseChips = parseChips;

  /* ── Keyboard: the whole module without a mouse ─────────────────────── */
  var pending = null;
  var GO = { h: "today", t: "tasks", b: "board", p: "projects", i: "time", f: "focus_page", n: "notes", s: "snippets", a: "habits", j: "journal", r: "reports", ",": "settings" };
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
    if (k === "c" || k === "t") { e.preventDefault(); d.dispatchEvent(new CustomEvent("work:capture", { detail: "task" })); }
    else if (k === "n") { e.preventDefault(); d.dispatchEvent(new CustomEvent("work:capture", { detail: "note" })); }
    else if (k === "s" && window.Alpine) { e.preventDefault(); var tm = Alpine.store("timer"); tm.running ? tm.stop() : d.dispatchEvent(new CustomEvent("work:capture", { detail: "time" })); }
    else if (k === "/") { var box = d.querySelector("[data-work-search]"); if (box) { e.preventDefault(); box.focus(); box.select && box.select(); } }
    else if (k === "?") { e.preventDefault(); d.dispatchEvent(new CustomEvent("work:help")); }
  });

  d.addEventListener("DOMContentLoaded", function () { badge(); flush(); });
})();
