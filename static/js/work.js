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
  function store(k, v) { try { if (v === null || v === undefined) localStorage.removeItem(k); else localStorage.setItem(k, JSON.stringify(v)); return true; } catch (e) { return false; /* storage off or full */ } }
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
  // Signed out meanwhile: the server sends the save to the sign-in page, and that page isn't an answer that it was saved.
  function signedOut(res) { return res.redirected && /\/accounts\/login\//.test(res.url); }
  var toldSignedOut = 0;
  // _ft_same: a save that replaces the one before it (a note, as it's written): what's waiting to go for it isn't sent as well.
  // _ft_draft: the local draft that this save makes needless. Without these, every pause while writing offline would queue a whole
  // copy of the note, fill the device's storage, and — for a new note — make a new note each time.
  var api = function (url, data) {
    var fields = Object.assign({}, data || {}, { _ft_key: uid(), _ft_user: ME });
    if (fields._ft_same && queued().some(function (x) { return x.fields._ft_same === fields._ft_same; })) {
      store(OUTBOX, queued().filter(function (x) { return x.fields._ft_same !== fields._ft_same; }));
    }
    function keep() {
      var box = queued(); box.push({ url: url, fields: fields, at: Date.now() });
      if (!store(OUTBOX, box)) { toast(t("deviceFull", "This device's storage is full, so this wasn't kept. Check your connection and try again."), "warn"); return { ok: false }; }
      badge();
      return { ok: true, queued: true };
    }
    return post(url, fields).then(function (res) {
      if (signedOut(res)) {
        if (Date.now() - toldSignedOut > 60000) {
          toldSignedOut = Date.now();
          toast(t("signedOut", "You're signed out. What you wrote is kept on this device and is sent once you sign in."), "warn",
                { label: t("signIn", "Sign in"), run: function () { location.href = res.url.split("?")[0] + "?next=" + encodeURIComponent(location.pathname + location.search); } });
        }
        return keep();
      }
      if (res.status === 403) return { ok: false, error: t("noAccess", "Not allowed.") };
      return res.json().catch(function () { return { ok: res.ok }; });
    }).catch(function () {
      var kept = keep();
      if (kept.ok) toast(t("savedOffline", "Saved on this device — it will sync when you're online."), "warn");
      return kept;
    });
  };
  /* A question to the server that isn't a change (a preview): nothing to keep for later. null when it can't be asked now. */
  function ask(url, data) {
    return post(url, data).then(function (res) {
      return signedOut(res) ? null : res.json().catch(function () { return null; });
    }).catch(function () { return null; });
  }
  function reached(item, ans) {              // this save has reached the server
    var f = item.fields, kept = f._ft_draft ? recall(f._ft_draft, null) : null;
    if (kept && kept.at <= item.at && (!kept.same || kept.same === f._ft_same)) store(f._ft_draft, null);
    if (f._ft_same) d.dispatchEvent(new CustomEvent("work:synced", { detail: { same: f._ft_same, location: ans.location, rev: ans.rev } }));
  }
  var flushing = false;
  function flush() {
    if (flushing || !navigator.onLine) return Promise.resolve();
    var box = queued(); if (!box.length) return Promise.resolve();
    flushing = true;
    var sent = 0, lost = 0;
    function others(item) { return queued().filter(function (x) { return x.fields._ft_key !== item.fields._ft_key; }); }
    function next() {
      var item = queued()[0];
      if (!item) return Promise.resolve();
      return post(item.url, item.fields, true).then(function (res) {
        if (signedOut(res)) return { ok: false, why: "signin" };
        // (the host's own error page, a deploy under way say: the server never saw this, so it isn't an answer)
        if (res.status >= 500 || res.status === 429) return { ok: false, why: "error" };
        return res.json().catch(function () { return { ok: res.ok }; });
      }).then(function (ans) {
        var retry = !ans.ok && (ans.why === "busy" || ans.why === "error" || ans.why === "signin");
        if (retry) throw new Error("later");
        if (ans.why === "gone" && item.url === CFG.urls.noteSave && item.fields.body !== undefined) {
          // the note was deleted elsewhere: what was written on it comes back as a note of its own
          store(OUTBOX, [{ url: item.url, fields: Object.assign({}, item.fields, { id: "", rev: "", _ft_key: uid() }), at: item.at }].concat(others(item)));
          return next();
        }
        store(OUTBOX, others(item));
        if (ans.ok) { sent++; reached(item, ans); } else lost++;
        return next();
      });
    }
    return next().catch(function () { /* still offline: try again later */ }).then(function () {
      flushing = false; badge();
      if (lost) toast(t("syncLost", "A change made offline couldn't be saved: what it belonged to is gone or was refused."), "warn");
      if (sent) { toast(t("synced", "Synced changes made offline.")); if (d.querySelector("[data-work-refresh]")) location.reload(); }
    });
  }
  window.addEventListener("online", flush);
  setInterval(flush, 60000);
  setTimeout(flush, 1500);              // what was kept last time (signed in again, say)

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
  // a short burst of filtered noise: the knock of a clock's tick, a wood block
  function knock(c, freq, start, length, gain, q) {
    var n = Math.floor(c.sampleRate * length), buf = c.createBuffer(1, n, c.sampleRate), data = buf.getChannelData(0);
    for (var i = 0; i < n; i++) data[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / n, 6);
    var src = c.createBufferSource(), f = c.createBiquadFilter(), g = c.createGain();
    src.buffer = buf; f.type = "bandpass"; f.frequency.value = freq; f.Q.value = q || 8; g.gain.value = gain;
    src.connect(f); f.connect(g); g.connect(c.destination); src.start(c.currentTime + start);
  }
  /* Every sound is made here, in the browser — nothing to download, and it works offline. Each one lasts about two
     seconds (RING_GAP), so ringing again and again (Work.ring, static/js/clock.js) doesn't overlap. */
  var SOUNDS = {
    chime: function (c, v) { [523.25, 659.25, 783.99, 1046.5].forEach(function (f, i) { tone(c, f, i * 0.16, 1.1, "sine", v * 0.5); }); },
    bell: function (c, v) { [880, 1760, 2640].forEach(function (f, i) { tone(c, f, 0, 2.2 - i * 0.5, "triangle", v * (0.45 - i * 0.12)); }); tone(c, 880, 0.9, 1.6, "triangle", v * 0.3); },
    digital: function (c, v) { for (var i = 0; i < 3; i++) { tone(c, 1046.5, i * 0.22, 0.12, "square", v * 0.18); } },
    soft: function (c, v) { tone(c, 392, 0, 1.4, "sine", v * 0.4); tone(c, 523.25, 0.35, 1.6, "sine", v * 0.35); },
    marimba: function (c, v) { [523.25, 659.25, 783.99, 659.25, 1046.5].forEach(function (f, i) { tone(c, f, i * 0.13, 0.45, "sine", v * 0.45); tone(c, f * 4, i * 0.13, 0.12, "sine", v * 0.08); }); },
    ding: function (c, v) { tone(c, 1318.5, 0, 1.8, "sine", v * 0.45); tone(c, 2637, 0, 0.9, "sine", v * 0.1); },
    harp: function (c, v) { [392, 493.88, 587.33, 783.99, 987.77, 1174.66].forEach(function (f, i) { tone(c, f, i * 0.09, 1.3, "triangle", v * 0.28); }); },
    gong: function (c, v) { [110, 164.8, 220, 277, 330].forEach(function (f, i) { tone(c, f, 0.02 * i, 2.4, i ? "sine" : "triangle", v * (0.5 - i * 0.08)); }); },
    kitchen: function (c, v) { for (var i = 0; i < 14; i++) { tone(c, 2200, i * 0.07, 0.05, "square", v * 0.12); tone(c, 2900, i * 0.07 + 0.035, 0.03, "square", v * 0.08); } },
    birds: function (c, v) {
      [0, 0.32, 0.9, 1.2].forEach(function (at) {
        var o = c.createOscillator(), g = c.createGain(), s0 = c.currentTime + at;
        o.type = "sine"; o.frequency.setValueAtTime(2600, s0); o.frequency.exponentialRampToValueAtTime(4200, s0 + 0.08); o.frequency.exponentialRampToValueAtTime(3000, s0 + 0.16);
        g.gain.setValueAtTime(0.0001, s0); g.gain.exponentialRampToValueAtTime(v * 0.2, s0 + 0.02); g.gain.exponentialRampToValueAtTime(0.0001, s0 + 0.18);
        o.connect(g); g.connect(c.destination); o.start(s0); o.stop(s0 + 0.2);
      });
    },
    alarm: function (c, v) { for (var i = 0; i < 4; i++) { tone(c, 988, i * 0.26, 0.1, "square", v * 0.16); tone(c, 988, i * 0.26 + 0.12, 0.1, "square", v * 0.16); } },
  };
  var RING_GAP = 2400;
  function vol() { return Math.max(0.05, (CFG.volume == null ? 70 : CFG.volume) / 100); }
  function play(kind, force) {
    var name = kind || CFG.sound;
    if (!name && !force) return;
    var c = ctx(); if (!c) return;
    (SOUNDS[name] || SOUNDS.chime)(c, vol());
  }
  /* The ticking of a running focus session: a clock's tick-tock (a lower "tock" every other second), a soft tick or
     a wood block — quiet, under whatever else is playing. `n`: which second it is. */
  function tick(n, style) {
    var c = ctx(); if (!c) return;
    var v = vol(), st = style || CFG.tickStyle || "clock";
    if (st === "soft") tone(c, 1800, 0, 0.03, "square", 0.02 * v);
    else if (st === "wood") knock(c, n % 2 ? 900 : 1100, 0, 0.06, 0.9 * v, 6);
    else knock(c, n % 2 ? 2600 : 3400, 0, 0.035, 0.7 * v, 12);
  }

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

  /* ── Pictures in Markdown boxes (textarea[data-paste-images]): paste, drop
        or pick one → it's uploaded and ![…](its address) goes in at the cursor ── */
  function shrinkImage(file) {      // big photos get smaller first; screenshots and small pictures go up as they are
    return new Promise(function (resolve) {
      if (!/^image\/(jpeg|png|webp)$/.test(file.type) || file.size < 1.5 * 1024 * 1024) return resolve(file);
      var img = new Image(), url = URL.createObjectURL(file);
      img.onload = function () {
        var k = Math.min(1, 2000 / Math.max(img.width, img.height)), c = d.createElement("canvas");
        c.width = Math.round(img.width * k); c.height = Math.round(img.height * k);
        c.getContext("2d").drawImage(img, 0, 0, c.width, c.height); URL.revokeObjectURL(url);
        c.toBlob(function (b) { resolve(b && b.size < file.size ? new File([b], (file.name || "image").replace(/\.\w+$/, "") + ".jpg", { type: "image/jpeg" }) : file); }, "image/jpeg", 0.85);
      };
      img.onerror = function () { URL.revokeObjectURL(url); resolve(file); };
      img.src = url;
    });
  }
  function setText(ta, value, caret) {
    ta.value = value; if (caret != null) ta.selectionStart = ta.selectionEnd = caret;
    ta.dispatchEvent(new Event("input", { bubbles: true }));          // x-model and autosave pick it up
  }
  function putImages(ta, files) {
    files = Array.prototype.filter.call(files || [], function (f) { return /^image\//.test(f.type); });
    if (!files.length || !CFG.urls.imageUpload) return false;
    files.forEach(function (file) {
      var mark = "![" + t("uploading", "Uploading…") + " " + uid().slice(0, 8) + "]()", s0 = ta.selectionStart, e0 = ta.selectionEnd;
      var before = ta.value.slice(0, s0), pad = before && !/\n$/.test(before) ? "\n" : "";
      setText(ta, before + pad + mark + "\n" + ta.value.slice(e0), s0 + pad.length + mark.length + 1);
      var done = function (text, error) {
        var i = ta.value.indexOf(mark); if (i < 0) return;
        var end = i + mark.length + (text ? 0 : 1);
        setText(ta, ta.value.slice(0, i) + text + ta.value.slice(end), null);
        if (error) toast(error, "warn");
      };
      shrinkImage(file).then(function (f) {
        var fd = new FormData(); fd.append("image", f, f.name || "image"); fd.append("name", file.name || "");
        if (ta.getAttribute("data-note")) fd.append("note", ta.getAttribute("data-note"));
        return fetch(CFG.urls.imageUpload, { method: "POST", body: fd, credentials: "same-origin",
                                             headers: { "X-CSRFToken": csrf(), "X-Requested-With": "fetch", Accept: "application/json" } })
          .then(function (r) { return r.json(); });
      }).then(function (res) {
        if (res && res.ok) done(res.markdown); else done("", (res && res.error) || t("imageFailed", "The picture couldn't be uploaded."));
      }).catch(function () { done("", t("imageOffline", "Pictures need a connection — try again when you're online.")); });
    });
    return true;
  }
  function pictureBox(e) { return e.target && e.target.closest && e.target.closest("textarea[data-paste-images]"); }
  d.addEventListener("paste", function (e) {
    var ta = pictureBox(e); if (ta && e.clipboardData && putImages(ta, e.clipboardData.files)) e.preventDefault();
  });
  d.addEventListener("dragover", function (e) {
    var ta = pictureBox(e); if (!ta || !e.dataTransfer || Array.prototype.indexOf.call(e.dataTransfer.types, "Files") < 0) return;
    e.preventDefault(); ta.classList.add("is-dropping");
  });
  d.addEventListener("dragleave", function (e) { var ta = pictureBox(e); if (ta) ta.classList.remove("is-dropping"); });
  d.addEventListener("drop", function (e) {
    var ta = pictureBox(e); if (!ta) return;
    ta.classList.remove("is-dropping");
    if (e.dataTransfer && putImages(ta, e.dataTransfer.files)) e.preventDefault();
  });

  /* ── Full screen: "page" (no menus — every page, Shift+F) or "write" (a
        note and nothing else, Ctrl+Shift+F in the editor). The browser's own
        full screen too, where it's allowed; Esc leaves both. ──────────────── */
  var zenAsked = false;
  function zenOn(mode) {
    root.setAttribute("data-zen", mode || "page");
    try { sessionStorage.setItem("ft-zen", mode || "page"); } catch (e) { /* storage off */ }
    var el = d.documentElement;
    if (el.requestFullscreen && !d.fullscreenElement) { zenAsked = true; el.requestFullscreen({ navigationUI: "hide" }).catch(function () { zenAsked = false; }); }
    window.dispatchEvent(new Event("resize"));
  }
  function zenOff() {
    root.removeAttribute("data-zen");
    try { sessionStorage.removeItem("ft-zen"); } catch (e) { /* storage off */ }
    if (d.fullscreenElement && d.exitFullscreen) d.exitFullscreen().catch(function () {});
    zenAsked = false;
    window.dispatchEvent(new Event("resize"));
  }
  function zenToggle(mode) {
    var now = root.getAttribute("data-zen");
    if (now && (!mode || now === mode)) zenOff(); else zenOn(mode);
  }
  d.addEventListener("fullscreenchange", function () {   // left the browser's full screen (Esc, F11): leave ours too
    if (!d.fullscreenElement && zenAsked && root.getAttribute("data-zen")) { zenAsked = false; zenOff(); }
  });
  d.addEventListener("click", function (e) {
    var on = e.target.closest && e.target.closest("[data-zen-toggle]");
    if (on) { zenToggle(on.getAttribute("data-zen-toggle")); return; }
    if (e.target.closest && e.target.closest("[data-zen-off]")) zenOff();
  });
  function dialogOpen() {
    return Array.prototype.some.call(d.querySelectorAll('[role="dialog"]'), function (el) { return el.offsetParent !== null || getComputedStyle(el).position === "fixed" && getComputedStyle(el).display !== "none"; });
  }
  d.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && root.getAttribute("data-zen") && !e.defaultPrevented && !dialogOpen()) { zenOff(); return; }
    if ((e.key === "F" || e.key === "f") && e.shiftKey && !e.altKey) {
      if (e.ctrlKey || e.metaKey) { if (d.querySelector(".wn-body")) { e.preventDefault(); zenToggle("write"); } return; }
      if (typing(e)) return;
      e.preventDefault(); zenToggle("page");
    }
  });

  /* ── Numbers on stat cards count up when they come into view ───────────── */
  (function countUp() {
    if (!window.IntersectionObserver || (window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches)) return;
    var NUM = /\d[\d,]*(\.\d+)?/g;
    function run(el) {
      var text = el.textContent, parts = [], m;
      NUM.lastIndex = 0;
      while ((m = NUM.exec(text))) parts.push({ at: m.index, raw: m[0], value: parseFloat(m[0].replace(/,/g, "")), dec: (m[1] || "").length - (m[1] ? 1 : 0), comma: m[0].indexOf(",") >= 0 });
      if (!parts.length || parts.every(function (p) { return !p.value; })) return;
      var start = performance.now(), dur = 750;
      function fmt(p, v) {
        var str = p.dec ? v.toFixed(p.dec) : String(Math.round(v));
        if (p.comma) str = Number(str).toLocaleString("en-IN", { minimumFractionDigits: p.dec, maximumFractionDigits: p.dec });
        return str;
      }
      (function frame(now) {
        var t = Math.min(1, (now - start) / dur), k = 1 - Math.pow(1 - t, 3), out = "", last = 0;
        parts.forEach(function (p) { out += text.slice(last, p.at) + (t < 1 ? fmt(p, p.value * k) : p.raw); last = p.at + p.raw.length; });
        el.textContent = out + text.slice(last);
        if (t < 1) requestAnimationFrame(frame);
      })(start);
    }
    var seen = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) { if (en.isIntersecting) { seen.unobserve(en.target); run(en.target); } });
    }, { threshold: 0.4 });
    d.addEventListener("DOMContentLoaded", function () {
      d.querySelectorAll(".work .stat-value, .work .wfc-stat b, .work .wfr-sum dd:not([x-text])").forEach(function (el) {
        if (el.children.length || el.hasAttribute("x-text")) return;     // only plain numbers; live (Alpine) ones are left alone
        if (/[০-৯]/.test(el.textContent)) return;
        seen.observe(el);
      });
    });
  })();

  /* ── Expose for the page components ──────────────────────────────────── */
  window.Work = { api: api, ask: ask, toast: toast, undoable: undoable, play: play, tick: tick, ringGap: RING_GAP, sounds: Object.keys(SOUNDS), notify: notify, askNotify: askNotify, clock: clock, hm: hm, cfg: CFG, flush: flush, recall: recall, store: store, putImages: putImages, shrinkImage: shrinkImage, zen: { on: zenOn, off: zenOff, toggle: zenToggle } };

  /* ── Focus (Pomodoro): one engine for every page ──────────────────────
   * The session lives in localStorage (by its end time), so it keeps going
   * through page changes, other tabs and a sleeping phone. Whichever page is
   * open when it ends finishes it: saves the focus time to the timesheet,
   * plays the sound, starts the break. A session that ended while no page of
   * the app was open is saved the next time one opens. Tabs keep in step
   * through "storage" events; a Web Lock (and the server, by start time)
   * makes sure a session is saved once. */
  var Focus = (function () {
    var KEY = "work-focus:" + ME, subs = [], TITLE = /^(?:🍅|☕|⏲️?|⏱️?) [^·]+ · /u;     // (⏲ ⏱: a timer, the stopwatch — clock.js)
    function lengths() { return { focus: CFG.focus || 25, short: CFG.short || 5, long: CFG.long || 15 }; }
    function blank() { return { mode: "focus", running: false, endsAt: 0, startedAt: 0, left: lengths().focus * 60, done: 0, day: isoDay(0), task: "", taskTitle: "" }; }
    function load() {
      var x = Object.assign(blank(), recall(KEY, {}) || {});
      if (x.day !== isoDay(0) && !x.running) { x.done = 0; x.day = isoDay(0); }     // the session dots start again each day
      if (!x.running && !(x.left > 0)) x.left = lengths()[x.mode] * 60;
      return x;
    }
    var S = load();
    function total() { return lengths()[S.mode] * 60; }
    function left() { return S.running ? Math.max(0, (S.endsAt - Date.now()) / 1000) : S.left; }
    function emit() { subs.forEach(function (fn) { try { fn(S); } catch (e) { /* a page part that's gone */ } }); }
    function save() { store(KEY, S); emit(); }
    function title() {
      var base = d.title.replace(TITLE, "");
      d.title = S.running ? (S.mode === "focus" ? "🍅 " : "☕ ") + clock(left()) + " · " + base : base;
    }
    function start() {
      S = load(); if (S.running) return;
      askNotify();
      S.running = true; S.endsAt = Date.now() + S.left * 1000;
      if (!S.startedAt) S.startedAt = Date.now();
      save(); title();
    }
    function pause() { S = load(); if (!S.running) return; S.left = left(); S.running = false; save(); title(); }
    function reset() { S = load(); S.running = false; S.startedAt = 0; S.left = total(); if (S.kept) delete S.kept[S.mode]; save(); title(); }
    /* Focus, short break, long break: switching never throws time away. The one left keeps its time (its tab shows
       it) and carries on from there when you come back; if it was running, the one switched to starts at once. */
    function setMode(mode) {
      S = load();
      if (mode === S.mode) return;
      var was = S.mode, wasRunning = S.running, nowLeft = left();
      S.kept = S.kept || {};
      if (nowLeft > 0 && nowLeft < total() - 1) S.kept[was] = { left: nowLeft, startedAt: S.startedAt }; else delete S.kept[was];
      S.mode = mode; S.running = false; S.endsAt = 0;
      var k = S.kept[mode]; delete S.kept[mode];
      S.left = k ? k.left : total(); S.startedAt = k ? k.startedAt : 0;
      save(); title();
      if (wasRunning) start();
      if (S.kept[was] && was === "focus") toast(t("focusKept", "Focus paused at %(time)s — it waits under Focus.").replace("%(time)s", clock(S.kept[was].left)), "",
                                               { label: t("backToFocus", "Back to focus"), run: function () { setMode("focus"); } });
    }
    function kept(mode) { var x = load().kept || {}; return x[mode] ? x[mode].left : 0; }
    function setTask(id, label) { S = load(); S.task = id || ""; S.taskTitle = id ? (label || "") : ""; save(); }
    // `skipped`: the Skip button. Otherwise the time ran out — maybe while no page was open (`late`).
    function finish(skipped) {
      S = load();
      var was = S.mode, endedAt = skipped ? Date.now() : (S.endsAt || Date.now()), late = !skipped && Date.now() - endedAt > 60000;
      if (!skipped && !S.running) return;
      S.running = false;
      if (was === "focus") {
        // the time actually spent focusing (a pause or a break in between isn't counted), ending now
        var focused = skipped ? Math.max(0, total() - left()) : total(), started = endedAt - focused * 1000;
        if (S.kept) delete S.kept.focus;
        if (!skipped || focused > 60) {
          S.done += 1;
          api(CFG.urls.focus, { started_at: new Date(started).toISOString(), ended_at: new Date(endedAt).toISOString(), task: S.task || "",
                                description: S.task ? "" : t("focusSession", "Focus session") })
            .then(function (res) { if (res && res.today != null && window.Alpine && Alpine.store("timer")) Alpine.store("timer").today = res.today; });
        }
        S.mode = (S.done % (CFG.every || 4) === 0) ? "long" : "short";
      } else {
        S.mode = "focus";
      }
      var back = S.kept && S.kept[S.mode];          // a focus session left for this break goes on where it was
      if (S.kept) delete S.kept[S.mode];
      S.startedAt = back ? back.startedAt : 0; S.left = back ? back.left : total(); S.endsAt = 0;
      save(); title();
      if (late) {   // it ended while the app was closed: say so quietly, don't start a break that's long over
        toast(was === "focus" ? t("focusSavedLate", "A focus session finished while you were away — it's in your timesheet.") : t("breakOver", "Break's over"));
        return;
      }
      if (!skipped) {
        var head = was === "focus" ? t("focusDone", "Focus session done") : t("breakOver", "Break's over");
        var body = was === "focus" ? t("takeBreak", "Time for a break.") : t("backToWork", "Ready to focus again?");
        // rings once, three times or until stopped (Work.ring: static/js/clock.js), with the sound for what just ended
        if (window.Work.ring) Work.ring("focus", { title: head, text: body, sound: was === "focus" ? CFG.sound : CFG.breakSound, icon: was === "focus" ? "🍅" : "☕" });
        else play(was === "focus" ? CFG.sound : CFG.breakSound);
        if (d.hidden || !window.Work.ring) notify(head, body, CFG.urls.focus_page, "focus");      // (in sight: the ring's card or toast says it)
      }
      var auto = S.mode === "focus" ? CFG.autoFocus : CFG.autoBreaks;
      if (auto && !skipped) setTimeout(start, 1200);
    }
    function due() { var x = recall(KEY, null); return x && x.running && Date.now() >= x.endsAt; }
    function check() {
      if (!due()) return;
      if (navigator.locks && navigator.locks.request) {      // one tab finishes it, the others just follow
        navigator.locks.request(KEY, { ifAvailable: true }, function (lock) { if (lock && due()) finish(false); });
      } else finish(false);
    }
    setInterval(function () { if (S.running) title(); check(); }, 1000);
    window.addEventListener("storage", function (e) { if (e.key === KEY) { S = load(); emit(); title(); } });
    d.addEventListener("visibilitychange", function () { if (!d.hidden) { S = load(); check(); emit(); title(); } });
    setTimeout(check, 0);
    // the lengths were changed (the focus page's settings): one not started yet takes its new length at once
    function lengthsChanged(was) {
      S = load();
      if (!S.running && (!S.startedAt || Math.round(S.left) === (was[S.mode] || 0) * 60)) { S.left = total(); S.startedAt = 0; }
      save(); title();
    }
    return {
      get state() { return S; }, left: left, total: total, start: start, pause: pause, reset: reset, set: setMode, setTask: setTask, kept: kept, lengthsChanged: lengthsChanged,
      skip: function () { finish(true); }, toggle: function () { load().running ? pause() : start(); },
      subscribe: function (fn) { subs.push(fn); fn(S); },
    };
  })();
  window.Work.focus = Focus;

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
          if (res.ok && res.running && res.running.left_off) toast(t("leftOffAt", "You left off:") + " " + res.running.left_off);
          return res;
        });
      },
      stop: function () {
        if (!this.running) return Promise.resolve();
        var self = this, at = new Date().toISOString();
        this.today += this.elapsedToday(); var label = this.running.label, took = this.text, task = this.running.task, leftOff = this.running.left_off;
        this.running = null; this.share(); this.title();
        return api(CFG.urls.timerStop, { at: at }).then(function (res) {
          if (res.ok && !res.queued) self.today = res.today;
          toast(t("tracked", "Tracked") + " " + took + " · " + label);
          d.dispatchEvent(new CustomEvent("work:timer", { detail: null }));
          if (task && CFG.leftOff) d.dispatchEvent(new CustomEvent("work:left-off", { detail: { task: task, label: label, text: leftOff || "" } }));
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

    /* ── Job search board: drag an application to its new stage (SortableJS), as on the task board ── */
    Alpine.data("jobBoard", function () {
      return {
        init: function () {
          var self = this, base = this.$root.getAttribute("data-move-url");
          function setup() {
            if (!window.Sortable) return setTimeout(setup, 80);
            self.$root.querySelectorAll("[data-column]").forEach(function (col) {
              Sortable.create(col, {
                group: "jobs", animation: 160, ghostClass: "is-ghost", dragClass: "is-dragging", delay: 120, delayOnTouchOnly: true,
                onEnd: function (e) {
                  var ids = Array.prototype.map.call(e.to.children, function (c) { return c.getAttribute("data-job"); });
                  api(base + e.item.getAttribute("data-job") + "/move/", { stage: e.to.getAttribute("data-column"), order: ids.join(",") }).then(function (res) {
                    if (res && res.ok && !res.queued && e.from !== e.to) toast(t("jobMoved", "Moved"), "good");
                  });
                  self.$root.querySelectorAll("[data-column]").forEach(function (c) { var n = c.parentElement.querySelector("[data-count]"); if (n) n.textContent = c.children.length; });
                },
              });
            });
          }
          setup();
        },
      };
    });

    /* ── STAR stories: a behavioural question at random, two minutes to tell a story out loud, then the
       story to check it against — or, when none answers it, a link to write one ── */
    Alpine.data("storyPractice", function () {
      var P = {}; try { P = JSON.parse(d.getElementById("story-practice").textContent); } catch (e) { P = { deck: [], stories: [] }; }
      return {
        q: null, shown: null, running: false, left: 120, timer: null, last: -1,
        get matches() { var q = this.q; return q ? P.stories.filter(function (s) { return (s.shows || []).indexOf(q.key) >= 0; }) : []; },
        init: function () { this.next(); },
        next: function () {
          this.stop(); this.left = 120; this.shown = null;
          if (!P.deck.length) return;
          var i; do { i = Math.floor(Math.random() * P.deck.length); } while (P.deck.length > 1 && i === this.last);
          this.last = i; this.q = P.deck[i];
        },
        toggle: function () {
          if (this.running) return this.stop();
          var self = this, end = Date.now() + this.left * 1000;
          this.running = true;
          this.timer = setInterval(function () {
            self.left = Math.round((end - Date.now()) / 1000);
            if (self.left <= 0) { self.stop(); play(CFG.sound ? "chime" : ""); }
          }, 250);
        },
        stop: function () { clearInterval(this.timer); this.running = false; },
        clock: function () { var n = Math.max(0, this.left); return Math.floor(n / 60) + ":" + String(n % 60).padStart(2, "0"); },
        practised: function (s) {
          api(P.practisedUrl, { action: "practised", story: s.id }).then(function (r) { if (r && r.ok) toast(t("storyTold", "Nice — counted"), "good"); });
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
                  }).then(function (res) { Work.timerFollowed(res); });
                  self.count();
                  if (status === "doing" && e.from !== e.to && CFG.wip && e.to.children.length > CFG.wip)
                    toast(t("wipOver", "“In progress” is over your limit.").replace("%(n)s", CFG.wip), "warn");
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
        count: function () {
          this.$root.querySelectorAll("[data-column]").forEach(function (col) {
            var c = col.parentElement.querySelector("[data-count]"), n = col.children.length;
            if (!c) return;
            var limit = col.getAttribute("data-column") === "doing" && CFG.wip;
            c.textContent = limit ? n + " / " + limit : n;
            col.parentElement.classList.toggle("is-over", !!limit && n > limit);
          });
        },
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
          if (action === "clear") return FT.ask(t("clearPlan", "Take every open task off the timeline? They stay on the day's list.")).then(function (sure) { if (sure) self.send(action); });
          this.send(action);
        },
        send: function (action) {
          var self = this;
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
          if ((q.length < 2 && !/^\d$/.test(q)) || q.charAt(0) === ">") { this.found = []; return; }
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
    /* ── Subtasks on a task's page ─────────────────────────────────────── */
    Alpine.data("workSubtasks", function (taskId) {
      return {
        text: "",
        add: function () {
          var text = this.text.trim(), self = this;
          if (!text) return;
          this.text = "";
          api(CFG.urls.taskBase + taskId + "/subtasks/", { text: text }).then(function (res) {
            if (res.ok && res.html) { self.$refs.list.insertAdjacentHTML("beforeend", res.html); self.$refs.count.textContent = res.counts || ""; }
            else if (res.error) { toast(res.error, "warn"); self.text = text; }
          });
        },
      };
    });

    /* ── A task's reminder, picked from its due date (on the day, a day or a week before — at the work day's start) ── */
    Alpine.data("workRemind", function (dueId, remindId, dayStart) {
      return {
        due: "", has: false,
        init: function () {
          var self = this, due = d.getElementById(dueId), remind = d.getElementById(remindId);
          this.dueEl = due; this.remindEl = remind;
          var read = function () { self.due = due ? due.value : ""; self.has = !!(remind && remind.value); };
          read();
          if (due) { due.addEventListener("input", read); due.addEventListener("change", read); }
          if (remind) remind.addEventListener("input", read);
        },
        put: function (when) {
          var pad = function (n) { return (n < 10 ? "0" : "") + n; };
          this.remindEl.value = when ? when.getFullYear() + "-" + pad(when.getMonth() + 1) + "-" + pad(when.getDate()) + "T" + pad(when.getHours()) + ":" + pad(when.getMinutes()) : "";
          this.remindEl.dispatchEvent(new Event("input", { bubbles: true }));
          this.has = !!when;
        },
        at: function (day) {
          var hm = (dayStart || "09:00").split(":");
          day.setHours(+hm[0] || 0, +hm[1] || 0, 0, 0);
          return day;
        },
        before: function (days) {
          var p = this.due.split("-");
          if (p.length !== 3) return;
          this.put(this.at(new Date(+p[0], +p[1] - 1, +p[2] - days)));
        },
        inHours: function (h) { var w = new Date(Date.now() + h * 3600000); w.setSeconds(0, 0); this.put(w); },
        tomorrow: function () { var w = new Date(); w.setDate(w.getDate() + 1); this.put(this.at(w)); },
        clear: function () { this.put(null); },
      };
    });

    /* ── The timeline: drag a bar to move a task's dates, or an end to change one.
          With a finger only the ends move (the bar itself scrolls and opens the task). ── */
    Alpine.data("workTimeline", function (days) {
      var shift = function (iso, n) {
        if (!iso) return "";
        var p = iso.split("-"), x = new Date(Date.UTC(+p[0], +p[1] - 1, +p[2] + n));
        return x.toISOString().slice(0, 10);
      };
      return {
        init: function () {
          var root = this.$el, drag = null, swallow = false;
          root.addEventListener("pointerdown", function (e) {
            var bar = e.target.closest(".wtl-bar-item[data-task]"); if (!bar || e.button > 0) return;
            var edge = e.target.closest(".wtl-h"); edge = edge ? edge.getAttribute("data-edge") : "move";
            if (edge === "move" && e.pointerType === "touch") return;
            drag = { bar: bar, edge: edge, x: e.clientX, n: 0, left: parseFloat(bar.style.left), width: parseFloat(bar.style.width),
                     px: bar.parentElement.getBoundingClientRect().width / days, id: e.pointerId };
            bar.setPointerCapture(e.pointerId);
            if (edge !== "move") e.preventDefault();
          });
          root.addEventListener("pointermove", function (e) {
            if (!drag || e.pointerId !== drag.id) return;
            var n = Math.round((e.clientX - drag.x) / drag.px), step = 100 / days, b = drag.bar;
            if (Math.abs(e.clientX - drag.x) > 4) b.classList.add("is-dragging");
            var span = Math.round(drag.width / step);      // days the bar covers
            if (drag.edge === "start") n = Math.min(n, span - 1);
            if (drag.edge === "end") n = Math.max(n, 1 - span);
            if (n === drag.n) return;
            drag.n = n;
            if (drag.edge === "move") b.style.left = (drag.left + n * step) + "%";
            else if (drag.edge === "start") { b.style.left = (drag.left + n * step) + "%"; b.style.width = (drag.width - n * step) + "%"; }
            else b.style.width = (drag.width + n * step) + "%";
          });
          var end = function (e) {
            if (!drag || e.pointerId !== drag.id) return;
            var g = drag; drag = null;
            g.bar.classList.remove("is-dragging");
            if (!g.n) return;
            swallow = true; setTimeout(function () { swallow = false; }, 0);
            var start = g.bar.getAttribute("data-start"), due = g.bar.getAttribute("data-due"), data = {};
            if (g.edge === "move") { if (start) data.start_date = shift(start, g.n); if (due) data.due_date = shift(due, g.n); }
            else if (g.edge === "start") data.start_date = shift(start || due, g.n);
            else data.due_date = shift(due || start, g.n);
            if (e.type === "pointercancel") { location.reload(); return; }
            api(CFG.urls.taskBase + g.bar.getAttribute("data-task") + "/update/", data).then(function (res) {
              if (res.queued) toast(t("savedOffline", "Saved on this device — it will sync when you're online."));
              else if (res.ok) location.reload(); else { toast(res.error, "warn"); location.reload(); }
            });
          };
          root.addEventListener("pointerup", end);
          root.addEventListener("pointercancel", end);
          root.addEventListener("click", function (e) { if (swallow && e.target.closest(".wtl-bar-item")) e.preventDefault(); }, true);
        },
      };
    });

    /* ── The month calendar: a task dragged to another day (or given one in the day's list) is due then ── */
    Alpine.data("workCalendar", function (pick) {
      return {
        pick: pick, dragging: null, over: "",
        grab: function (e, id) {
          this.dragging = id;
          e.dataTransfer.effectAllowed = "move";
          e.dataTransfer.setData("text/plain", String(id));
        },
        drop: function (day) {
          var id = this.dragging; this.dragging = null; this.over = "";
          if (id) this.move(id, day);
        },
        move: function (id, day) {
          if (!day) return;
          api(CFG.urls.taskBase + id + "/update/", { due_date: day }).then(function (res) {
            if (res.queued) toast(t("savedOffline", "Saved on this device — it will sync when you're online."));
            else if (res.ok) location.reload(); else toast(res.error, "warn");
          });
        },
      };
    });

    /* ── A task's files: picked or dropped, uploaded straight away (needs a connection) ── */
    Alpine.data("workFiles", function (taskId) {
      return {
        over: false, busy: false,
        init: function () {
          var self = this;
          this.$el.addEventListener("click", function (e) {
            var b = e.target.closest("[data-remove-file]"); if (!b) return;
            FT.ask({ message: t("removeFile", "Remove this file? It can't be brought back."), danger: true, ok: t("remove", "Remove") }).then(function (sure) {
              if (!sure) return;
              api(CFG.urls.fileBase + b.getAttribute("data-remove-file") + "/delete/", {}).then(function (res) {
                if (!res.ok) return toast(res.error, "warn");
                b.closest("[data-file]").remove(); self.$refs.count.textContent = res.count || "";
              });
            });
          });
        },
        send: function (files) {
          files = Array.prototype.slice.call(files || []);
          if (!files.length || this.busy) return;
          var self = this, fd = new FormData();
          files.forEach(function (f) { fd.append("file", f, f.name); });
          this.busy = true;
          fetch(CFG.urls.taskBase + taskId + "/files/", { method: "POST", body: fd, credentials: "same-origin",
                                                         headers: { "X-CSRFToken": csrf(), "X-Requested-With": "fetch", Accept: "application/json" } })
            .then(function (r) { return r.json(); })
            .then(function (res) {
              if (res.ok) { self.$refs.list.insertAdjacentHTML("afterbegin", res.html); self.$refs.count.textContent = res.count || ""; }
              else toast(res.error, "warn");
            })
            .catch(function () { toast(t("fileOffline", "Files need a connection — try again when you're online."), "warn"); })
            .then(function () { self.busy = false; });
        },
      };
    });

    /* ── Saved views: the task list's filters, kept under a name ───────── */
    Alpine.data("workSavedViews", function (query) {
      return {
        save: function () {
          FT.ask({ title: t("viewName", "Name this view:"), input: {} }).then(function (name) {
            name = (name || "").trim();
            if (!name) return;
            api(CFG.urls.viewSave, { name: name, query: query }).then(function (res) {
              if (res.ok && res.url) { toast(t("viewSaved", "View saved")); location.href = res.url; }
              else if (res.error) toast(res.error, "warn");
            });
          });
        },
        drop: function (id) {
          var chip = this.$root.querySelector('[data-view="' + id + '"]'), active = chip && chip.classList.contains("is-active");
          FT.ask({ message: t("viewDelete", "Remove this saved view?"), danger: true, after: "gone", ok: t("remove", "Remove") }).then(function (sure) {
            if (!sure) return;
            api(CFG.urls.viewBase + id + "/", { action: "delete" }).then(function (res) {
              if (!res.ok) return;
              if (active) location.href = CFG.urls.tasks; else if (chip) chip.remove();
            });
          });
        },
      };
    });

    /* ── A task's blockers ("Blocked by") and its activity / comments ──── */
    Alpine.data("workLeftOff", function () {
      return {
        task: null, label: "", text: "", leave: null,
        ask: function (o) {
          var self = this;
          this.task = o.task; this.label = o.label; this.text = o.text;
          this.keep(30000);
          this.$nextTick(function () { if (d.activeElement === d.body) self.$refs.line.focus(); });      // never out of something being typed
        },
        keep: function (ms) {       // goes by itself, unless it's being written in
          var self = this;
          clearTimeout(this.leave);
          this.leave = setTimeout(function () { self.close(); }, typeof ms === "number" ? ms : 60000);
        },
        close: function () { clearTimeout(this.leave); this.task = null; },
        save: function () {
          var task = this.task;
          this.close();
          if (task) api(CFG.urls.taskBase + task + "/update/", { left_off: this.text });
        },
      };
    });

    Alpine.data("workBlockers", function (taskId) {
      return {
        init: function () {
          var self = this;
          this.$el.addEventListener("click", function (e) {
            var b = e.target.closest("[data-remove]"); if (!b) return;
            self.send({ remove: b.getAttribute("data-remove") });
          });
        },
        add: function () {
          var pick = this.$refs.pick; if (!pick || !pick.value) return;
          var opt = pick.selectedOptions[0];
          this.send({ add: pick.value }).then(function (res) { if (res.ok && opt) { opt.remove(); pick.value = ""; } });
        },
        send: function (data) {
          var self = this;
          return api(CFG.urls.taskBase + taskId + "/blockers/", data).then(function (res) {
            if (res.ok && res.html != null) self.$refs.box.innerHTML = res.html;
            else if (res.error) toast(res.error, "warn");
            return res;
          });
        },
      };
    });
    Alpine.data("workComments", function (taskId) {
      return {
        busy: false,
        init: function () {
          this.$el.querySelectorAll("[data-md-text]").forEach(Work.paintMarkdown);
          this.$el.addEventListener("click", function (e) {
            var b = e.target.closest("[data-delete-comment]"); if (!b) return;
            var li = b.closest("li");
            FT.ask({ message: t("deleteComment", "Delete this comment?"), danger: true, after: "gone" }).then(function (sure) {
              if (sure) api(CFG.urls.commentBase + b.getAttribute("data-delete-comment") + "/delete/", {}).then(function (res) { if (res.ok && li) li.remove(); });
            });
          });
        },
        send: function () {
          var box = this.$refs.text, text = box.value.trim(), self = this;
          if (!text || this.busy) return;
          this.busy = true;
          api(CFG.urls.taskBase + taskId + "/comment/", { text: text }).then(function (res) {
            self.busy = false;
            if (res.ok && res.html) {
              self.$refs.list.insertAdjacentHTML("afterbegin", res.html); box.value = "";
              var made = self.$refs.list.querySelector("[data-md-text]"); if (made) Work.paintMarkdown(made);
            }
            else if (res.queued) box.value = "";
            else if (res.error) toast(res.error, "warn");
          });
        },
      };
    });

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
      return Work.withCategories({
        categories: (initial.categories || []).slice(), reading: false,
        id: initial.id || null, title: initial.title || "", icon: initial.icon || "", body: initial.body || "", tags: initial.tags || "", project: initial.project || "", rev: initial.rev || "",
        linkedTitle: initial.title || "", examOpen: false, examSubject: "", examName: "", same: "note:" + (initial.id || uid()),
        state: "saved", savedAt: initial.saved || "", preview: false, split: false, timer: null, inflight: null, again: false,
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
          if (!v) return;
          var self = this;
          FT.ask(t("restoreNote", "Bring back this version? What's there now is kept as a version too.")).then(function (sure) {
            if (!sure) return;
            api(CFG.urls.noteBase + self.id + "/", { action: "restore", version: v.id }).then(function (res) {
              if (res.ok && res.url) { store(self.draftKey, null); location.href = res.url; }
            });
          });
        },
        forgetVersion: function (v) {
          var self = this;
          FT.ask({ message: t("forgetVersion", "Delete this version?"), danger: true, after: "gone" }).then(function (sure) {
            if (!sure) return;
            api(CFG.urls.noteBase + self.id + "/", { action: "forget", version: v.id }).then(function (res) {
              if (!res.ok) return;
              self.versions = self.versions.filter(function (x) { return x.id !== v.id; });
              if (self.shown && self.shown.id === v.id) self.shown = self.versions[0] || null;
            });
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
            self.body = res.body; self.savedAt = res.saved; self.rev = res.rev;
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
          // (Tab, Enter in lists and the other writing keys: static/js/writing.js)
        },
        get draftKey() { return Work.noteDraftKey(this.id || "new"); },
        init: function () {
          var draft = recall(this.draftKey, null), self = this;
          if (draft && draft.at > (initial.updated || 0) && (draft.body !== this.body || draft.title !== this.title)) {
            this.title = draft.title; this.body = draft.body; this.same = draft.same || this.same; this.state = "dirty"; this.queue();
          }
          d.addEventListener("work:synced", function (e) { self.synced(e.detail); });
          ["title", "body", "tags", "project"].forEach(function (k) { self.$watch(k, function () { self.changed(); }); });
          this.$watch("preview", function (on) { if (!on) self.$nextTick(function () { self.grow(); }); });
          this.$nextTick(function () { self.grow(); });
          var asked = new URLSearchParams(location.search).get("mode");      // ?mode=write (a list's Edit button), view…
          var seen = /^(write|split|preview|view)$/.test(asked || "") ? asked : this.id ? recall("work-note-view", "write") : "write";    // as it was last read
          this.preview = seen === "preview" || seen === "view"; this.reading = seen === "view"; this.split = seen === "split";
          if (asked) { var u = new URL(location.href); u.searchParams.delete("mode"); history.replaceState(history.state, "", u.pathname + u.search + u.hash); }
          this.cats = initial.cats || []; this.catN = initial.catN || {};
          d.addEventListener("keydown", function (e) {          // Ctrl+E: Write ⇄ Preview (as in Obsidian)
            if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && (e.key || "").toLowerCase() === "e" && !self.histOpen && !self.examOpen) {
              e.preventDefault(); self.view(self.preview ? "write" : recall("work-note-read", "preview"));
            }
          });
          window.addEventListener("beforeunload", function (e) { if (self.state === "dirty" || self.state === "saving") { self.saveNow(); } });
          this.$el.addEventListener("keydown", function (e) { if ((e.ctrlKey || e.metaKey) && e.key === "s") { e.preventDefault(); self.saveNow(); } });
          var heading = new URLSearchParams(location.search).get("heading");           // from a [[Note#Heading]] link
          if (heading) this.$nextTick(function () {
            var n = self.outline.findIndex(function (h) { return h.text.toLowerCase() === heading.toLowerCase(); });
            if (n < 0) return;
            self.preview = true;
            self.$nextTick(function () { self.goHeading(self.outline[n], n); });
          });
        },
        /* renamed (the title box left): the [[links]] in other notes follow */
        titleChanged: function () {
          var self = this, old = this.linkedTitle;
          if (!this.id || !old.trim() || old.trim() === this.title.trim()) return;
          this.linkedTitle = this.title;
          Promise.resolve(this.saveNow()).then(function () {
            return api(CFG.urls.noteBase + self.id + "/", { action: "relink", old: old });
          }).then(function (res) { if (res && res.ok && res.count) toast(t(res.count === 1 ? "linksUpdatedOne" : "linksUpdated", "Links updated: %(n)s").replace("%(n)s", res.count), "good"); });
        },
        /* the note's headings (or Q:/A: lines…) as exam questions */
        toExam: function () {
          var self = this, name = this.examName.trim();
          if (!name && !this.examSubject) return;
          Promise.resolve(this.saveNow()).then(function () {
            return api(CFG.urls.noteBase + self.id + "/", { action: "to_exam", subject: self.examSubject, name: name });
          }).then(function (res) {
            if (!res || !res.ok) { if (res && res.error) toast(res.error, "warn"); return; }
            if (res.queued) return;
            self.examOpen = false;
            toast(t(res.count === 1 ? "examMadeOne" : "examMade", "Questions added: %(n)s").replace("%(n)s", res.count), "good", { label: t("seeThem", "See them"), run: function () { location.href = res.url; } });
          });
        },
        changed: function () { this.state = "dirty"; store(this.draftKey, { title: this.title, body: this.body, at: Date.now(), same: this.same }); this.queue(); },
        /* what was written offline has reached the server: this page goes on from there */
        synced: function (x) {
          if (x.same !== this.same) return;
          this.rev = x.rev || "";
          var made = /\/notes\/(\d+)\//.exec(x.location || "");
          if (!this.id && made) { this.id = Number(made[1]); history.replaceState(null, "", x.location); }
          if (this.state === "offline") { var now = new Date(); this.state = "saved"; this.savedAt = pad(now.getHours()) + ":" + pad(now.getMinutes()); }
        },
        queue: function () { clearTimeout(this.timer); var self = this; this.timer = setTimeout(function () { self.saveNow(); }, 900); },
        saveNow: function () {
          var self = this;
          if (!this.id && !this.title.trim() && !this.body.trim()) { this.state = "saved"; return; }
          // One save at a time: a second one before the first answers would make a new note twice.
          if (this.inflight) { this.again = true; return this.inflight; }
          this.state = "saving";
          var key = this.draftKey;
          var sent = [this.title, this.body];
          this.inflight = api(CFG.urls.noteSave, { id: this.id || "", title: this.title, icon: this.icon, body: this.body, tags: this.tags, project: this.project, categories: this.categories.join(","),
                                                   rev: this.rev || "", _ft_same: this.same, _ft_draft: key }).then(function (res) {
            self.inflight = null;
            if (res.rev) self.rev = res.rev;
            if (res.conflict) toast(t("noteConflict", "This note was changed somewhere else too. That text is kept in History."), "warn");
            if (self.again) { self.again = false; if (res.ok && res.id) self.id = res.id; setTimeout(function () { self.saveNow(); }, 0); }
            if (!res.ok) { self.state = "error"; return; }
            if (res.queued) { self.state = "offline"; return; }
            if (self.title === sent[0] && self.body === sent[1]) store(key, null);        // (written on meanwhile: that draft stays)
            else store(Work.noteDraftKey(res.id), { title: self.title, body: self.body, at: Date.now() });
            if (!self.id && res.id) { self.id = res.id; history.replaceState(null, "", res.url); }
            self.savedAt = res.saved; self.state = self.title === sent[0] && self.body === sent[1] ? "saved" : "dirty";
            var item = d.querySelector('[data-note-id="' + self.id + '"] .work-note-item-title'); if (item) item.textContent = res.title;
          });
          return this.inflight;
        },
        get html() { return renderMarkdown(this.body); },
        /* its categories (the notes’ own tree, apart from the exam one): picked in the pop-up, saved with the note */
        pickNoteCats: function () { var self = this; this.pickCats(this.categories, function () { self.changed(); }); },
        dropNoteCat: function (id) { this.catRemove(this.categories, id); this.changed(); },
        setCategory: function (id) { location.href = CFG.urls.notes + (id === null ? "" : "?category=" + id); },
        /* Write, Split (side by side, on a wide screen) or Preview — where any part can be clicked to change it */
        view: function (mode) {
          var self = this;
          Work.liveDone();
          this.preview = mode === "preview" || mode === "view"; this.reading = mode === "view"; this.split = mode === "split";
          store("work-note-view", mode);
          if (this.preview) store("work-note-read", mode);
          if (mode !== "preview") this.$nextTick(function () { self.grow(); });
        },
        action: function (name) {
          var self = this;
          if (!this.id) return;
          api(CFG.urls.noteBase + this.id + "/", { action: name }).then(function (res) {
            if (name === "delete") { store(self.draftKey, null); undoable(t("noteDeleted", "Note deleted"), res.undo, function () { location.href = CFG.urls.notes + self.id + "/"; }); setTimeout(function () { location.href = CFG.urls.notes; }, 350); }
            else if ((name === "to_task" || name === "mindmap" || name === "duplicate") && res.url) location.href = res.url;
            else if (name === "mindmap" && !res.ok) toast(res.error || "", "warn");
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
        /* The note's headings (not those in a ``` block), to jump to one — Obsidian's outline */
        get outline() {
          var out = [], code = false;
          this.body.split("\n").forEach(function (line, i) {
            if (/^[ \t]*(```|~~~)/.test(line)) { code = !code; return; }
            var m = !code && /^(#{1,6})[ \t]+(.+?)[ \t#]*$/.exec(line);
            if (m) out.push({ level: m[1].length, text: m[2].replace(/[*_`]/g, ""), line: i });
          });
          return out;
        },
        goHeading: function (h, n) {
          if (this.preview) {
            var el = this.$root.querySelectorAll(".wn-md h1, .wn-md h2, .wn-md h3, .wn-md h4, .wn-md h5, .wn-md h6")[n];
            if (el) el.scrollIntoView({ block: "start", behavior: "smooth" });
            return;
          }
          var ta = this.$refs.body, pos = this.body.split("\n").slice(0, h.line).join("\n").length + (h.line ? 1 : 0);
          ta.focus({ preventScroll: true }); ta.setSelectionRange(pos, pos);
          var y = window.FTWriting ? FTWriting.caretXY(ta, pos).y : ta.getBoundingClientRect().top;
          var box = ta.closest(".wn-pane");
          if (box && box.scrollHeight > box.clientHeight + 1 && getComputedStyle(box).overflowY !== "visible") box.scrollTop += y - box.getBoundingClientRect().top - 80;
          else window.scrollTo({ top: window.scrollY + y - 140, behavior: "smooth" });
        },
        get words() { var m = this.body.match(/[^\s#>*`_\-\[\]()]+/g); return m ? m.length : 0; },
        get readMins() { return Math.max(1, Math.round(this.words / 200)); },
        get todoTotal() { return (this.body.match(/^[ \t]*[-*+][ \t]+\[[ xX]\]/gm) || []).length; },
        get todoDone() { return (this.body.match(/^[ \t]*[-*+][ \t]+\[[xX]\]/gm) || []).length; },
        /* Keep's list tools: ticked items to the bottom, untick all, delete the ticked ones — Undo on the toast */
        todoTool: function (how) {
          if (!window.FTWriting || !FTWriting.todos) return;
          var before = this.body, r = FTWriting.todos(before, how), self = this;
          if (!r.changed) { toast(t("todoNothing", "Nothing to change"), "warn"); return; }
          this.body = r.text;
          this.$nextTick(function () { self.grow(); });
          toast(t(how === "sink" ? "todoSunk" : how === "untick" ? "todoUnticked" : "todoDropped", "Done"), "good",
                { label: t("undo", "Undo"), run: function () { self.body = before; self.$nextTick(function () { self.grow(); }); } });
        },
        /* An emoji with the title, as a Notion page's icon: on the cards, in the list and here */
        chooseIcon: function (el) {
          var self = this;
          Work.pickIcon(el, this.icon).then(function (v) { if (v == null || v === self.icon) return; self.icon = v; self.saveNow(); });
        },
        /* Find (and replace) in the note: the Markdown is where the words are, so it opens in Write */
        openFind: function (replacing, q) {
          var self = this;
          if (this.preview) this.view("write");
          this.$nextTick(function () { if (window.FTWriting && FTWriting.find) FTWriting.find(self.$refs.body, replacing, q); });
        },
      }, CFG.urls.noteCategories);
    });

    /* ── A habit's day (Habits, Today) — as Loop and Streaks: a plain one is ticked on and off; one with
       an amount (8 glasses, 20 pages) goes up one a tap, and a long press or right-click asks how much.
       Done once the goal is reached; the streak and the week's count (the row's) follow. ── */
    Alpine.data("habitDay", function (o) {
      return {
        amount: o.amount || 0, target: o.target || 1, held: false, holdTimer: null,
        get done() { return this.amount >= this.target; },
        send: function (amount) {
          var self = this, was = this.amount;
          this.amount = amount;
          if (amount >= this.target && was < this.target) Work.play(Work.cfg.sound ? "soft" : "");
          api(o.url, { date: o.date, amount: String(amount) }).then(function (r) {
            if (r && r.ok) { if (r.streak != null) self.streak = r.streak; if (r.week != null) self.week = r.week; }
            else if (r && !r.queued) self.amount = was;
          });
        },
        click: function () {
          if (this.held) { this.held = false; return; }          // the end of a long press, not a tap
          this.send(this.target > 1 ? this.amount + 1 : (this.amount ? 0 : 1));
        },
        press: function () { var self = this; clearTimeout(this.holdTimer); this.holdTimer = setTimeout(function () { self.held = true; self.ask(); }, 550); },
        release: function () { clearTimeout(this.holdTimer); },
        ask: function () {
          var self = this;
          FT.ask({ message: o.name, text: t("habitHowMuch", "How much? The goal is %(n)s.").replace("%(n)s", this.target + (o.unit ? " " + o.unit : "")),
                   input: { value: String(this.amount), placeholder: "0" } }).then(function (v) {
            if (v == null) return;
            var n = parseInt(String(v).replace(/[^0-9]/g, ""), 10);
            if (!isNaN(n) && n !== self.amount) self.send(Math.min(n, 100000));
          });
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

    /* ── Focus (Pomodoro): the Focus page and the top-bar pill, over the engine ── */
    Alpine.store("focus", {
      mode: "focus", running: false, left: 0, total: 1, done: 0, startedAt: 0, task: "", taskTitle: "", kept: {},
      get text() { return clock(this.left); },
      get active() { return this.running || (this.startedAt && this.left < this.total); },   // running, or paused part-way
      get pct() { return 100 - Math.round(100 * this.left / this.total); },
      init: function () {
        var self = this;
        function pull() { var x = Focus.state; self.mode = x.mode; self.running = x.running; self.done = x.done; self.startedAt = x.startedAt;
                          self.task = x.task; self.taskTitle = x.taskTitle; self.total = Focus.total(); self.left = Focus.left();
                          self.kept = JSON.parse(JSON.stringify(x.kept || {})); }
        Focus.subscribe(pull);
        setInterval(function () { if (self.running) self.left = Focus.left(); }, 250);
      },
      toggle: function () { Focus.toggle(); },
    });
    Alpine.data("workFocus", function (opts) {
      return {
        get mode() { return Alpine.store("focus").mode; },
        get running() { return Alpine.store("focus").running; },
        get done() { return Alpine.store("focus").done; },
        get task() { return Alpine.store("focus").task; },
        get text() { return Alpine.store("focus").text; },
        get pct() { return Alpine.store("focus").pct; },
        len: { focus: CFG.focus, short: CFG.short, long: CFG.long, every: CFG.every || 4 },      // (the settings panel changes them: work:focus-settings)
        dotOn: function (i) { var n = this.len.every, k = this.done % n; return k >= i || (this.done && k === 0 && this.mode === "long"); },
        init: function () {
          var self = this;
          window.addEventListener("work:focus-settings", function (e) { var c = e.detail; self.len = { focus: c.focus, short: c.short, long: c.long, every: c.every || 4 }; });
          if (opts.task && !Focus.state.running) Focus.setTask(opts.task, opts.taskTitle);   // opened from a task's "Focus"
          // (the ticking: static/js/clock.js, here or on every page)
          d.addEventListener("keydown", function (e) {
            if (!typing(e) && e.code === "Space" && !e.ctrlKey && (!window.Clock || Clock.tab() === "focus")) { e.preventDefault(); self.toggle(); }
          });
        },
        start: function () { Focus.start(); },
        pause: function () { Focus.pause(); },
        toggle: function () { Focus.toggle(); },
        reset: function () { Focus.reset(); },
        set: function (mode) { Focus.set(mode); },
        kept: function (mode) { var k = this.mode !== mode && (Alpine.store("focus").kept || {})[mode]; return k ? clock(k.left) : ""; },
        skip: function () { Focus.skip(); },
        pick: function (e) { var o = e.target.selectedOptions[0]; Focus.setTask(e.target.value, o && e.target.value ? o.textContent.trim() : ""); },
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
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(done, function () { FT.showText(text); });
    else FT.showText(text);
  }
  ["change", "input"].forEach(function (type) {     // a task made a bug gets a bug report's headings, if its notes are empty
    d.addEventListener(type, function (e) {
      var sel = e.target; if (!sel || sel.name !== "kind" || sel.value !== "bug") return;
      var form = sel.closest("form[data-bug-template]"), notes = form && form.querySelector("textarea[name=notes]");
      if (!notes || notes.value.trim()) return;
      notes.value = form.getAttribute("data-bug-template");
      notes.dispatchEvent(new Event("input", { bubbles: true }));
    });
  });
  d.addEventListener("click", function (e) {         // a link with [data-copy-first]: its text is copied as it opens (a pull request's description)
    var a = e.target.closest("a[data-copy-first]"); if (!a) return;
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(a.getAttribute("data-copy-first")).then(function () { toast(t("copied", "Copied")); }, function () {});
  });
  d.addEventListener("click", function (e) {         // [data-copy="text"]: a branch name, a commit message, release notes…
    var b = e.target.closest("[data-copy]"); if (!b) return;
    e.preventDefault(); copyText(b.getAttribute("data-copy"));
  });
  /* A task's branch name and commit message (the same as dev.py makes on the task's page). */
  function devName(what, id, kind, title) {
    var dev = CFG.dev || {}, key = (dev.prefix || "T") + "-" + id;
    if (what === "commit") {
      var type = { feature: "feat", bug: "fix", docs: "docs" }[kind] || "chore";
      var tt = title.trim(); if (tt.slice(0, 2) !== tt.slice(0, 2).toUpperCase()) tt = tt.charAt(0).toLowerCase() + tt.slice(1);
      return type + ": " + tt + " (" + key + ")";
    }
    var slug = title.normalize("NFKD").replace(/[^\x00-\x7f]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 40).replace(/-+$/, "") || "task";
    var prefix = { feature: "feat", bug: "fix", chore: "chore", research: "spike", docs: "docs" }[kind] || "task";
    var name = (dev.branch || "{type}/{key}-{slug}").split("{type}").join(prefix).split("{key}").join(key).split("{id}").join(String(id)).split("{slug}").join(slug);
    return name.replace(/[\s~^:?*\[\\]+/g, "-").replace(/-{2,}/g, "-").replace(/^[-\/.]+|[-\/.]+$/g, "");
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
      if (res.unblocked && res.unblocked.length) toast(t("unblocked", "Ready to start now:") + " " + res.unblocked.join(", "));
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
      timerFollowed(res);
      return res;
    });
  }
  // the server started or stopped the timer with the task's status (Settings → the timer follows the status)
  function timerFollowed(res) {
    if (!res || !res.timer || !window.Alpine) return;
    Alpine.store("timer").sync();
    toast(res.timer === "started" ? t("timerStarted", "Timer started") : t("timerStopped", "Timer stopped"));
  }
  window.Work.timerFollowed = timerFollowed;
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
    label("review", row.getAttribute("data-status") === "review");
    label("waiting", row.hasAttribute("data-waiting"));
    menu.querySelectorAll("[data-menu-form]").forEach(function (f) { f.hidden = true; });
    menu.querySelector("[data-needs-link]").hidden = !row.getAttribute("data-link");
    menu.querySelector("[data-needs-sprint]").hidden = !row.closest("[data-sprint-page]");
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
    else if (name === "review") taskUpdate(row, "status", row.getAttribute("data-status") === "review" ? "doing" : "review");
    else if (name === "prio") taskUpdate(row, "priority", value);
    else if (name === "waiting") taskUpdate(row, "waiting_for", "");
    else if (name === "open-link" && link) window.open(link, "_blank", "noopener");
    else if (name === "copy") copyText(row.getAttribute("data-title") + (link ? " " + link : ""));
    else if (name === "branch" || name === "commit") copyText(devName(name, id, row.getAttribute("data-kind") || "task", row.getAttribute("data-title") || ""));
    else if (name === "duplicate") api(CFG.urls.taskBase + id + "/duplicate/", {}).then(function (res) {
      if (!res.ok) return;
      row.insertAdjacentHTML("afterend", res.html);
      toast(t("duplicated", "Copy made") + ": " + res.title, "good", { label: t("open", "Open"), run: function () { location.href = res.url; } });
    });
    else if (name === "unsprint") api(CFG.urls.taskBase + id + "/update/", { sprint: "" }).then(function (res) { if (res.ok) row.remove(); });
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
  // a new width (a phone turned, a window resized) — not a phone's keyboard coming up or going
  var menuW = window.innerWidth;
  window.addEventListener("resize", function () { if (window.innerWidth !== menuW) { menuW = window.innerWidth; closeMenu(); } });
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
    function send() {
      if (action === "done") play(CFG.sound ? "chime" : "");
      api(CFG.urls.taskBulk, { ids: ids.join(","), action: action, value: value || "" }).then(function (res) {
        if (!res.ok) { toast(res.error || t("notSaved", "Not saved."), "warn"); return; }
        toast(t("changed", "Updated") + (res.count ? " · " + res.count : ""));
        if (!res.queued) setTimeout(function () { location.reload(); }, 350);
      });
    }
    if (action === "delete") FT.ask({ message: t("confirmBulkDelete", "Delete the selected tasks?"), danger: true, after: "back" }).then(function (sure) { if (sure) send(); });
    else send();
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

  /* ── Markdown (notes, task notes) ───────────────────────────────────── */
  // [[Note title]] → a link that opens (or starts) that note; [[Note#Heading]] goes to the heading, [[Note|these words]] shows them
  function wikiLinks(text) {
    if (!CFG.urls || !CFG.urls.noteGo) return text;
    return (text || "").replace(/\[\[([^\[\]\n]{1,200})\]\]/g, function (all, inner) {
      var bar = inner.indexOf("|"), title = bar < 0 ? inner : inner.slice(0, bar), shown = (bar < 0 ? "" : inner.slice(bar + 1).trim()) || title.trim();
      return "[" + shown.replace(/([\\*_`\[\]])/g, "\\$1") + "](" + CFG.urls.noteGo + "?title=" + encodeURIComponent(title.trim()).replace(/\(/g, "%28").replace(/\)/g, "%29") + ")";
    });
  }
  /* ==highlighted== words (as Obsidian writes them), or in a colour: =={green}words== — outside code; on a review
     card's front they're the blanks (cloze). HL_RE finds them in Markdown; the n-th match is the n-th <mark> drawn. */
  var HL_COLORS = ["yellow", "green", "blue", "pink", "purple"];
  var HL_RE = /==(?:\{(yellow|green|blue|pink|purple)\})?(?=[^\s=])((?:[^=\n]|=(?!=))+?)(?<=\S)==/g;     // (one = inside is fine: a = b)
  var CODE_SPLIT = /(```[\s\S]*?(?:```|$)|~~~[\s\S]*?(?:~~~|$)|`[^`\n]+`)/;
  function highlights(text) {
    return String(text || "").split(CODE_SPLIT).map(function (part, i) {
      return i % 2 ? part : part.replace(HL_RE, function (all, color, words) {
        return "<mark" + (color && color !== "yellow" ? ' data-hl="' + color + '"' : "") + ">" + words + "</mark>";
      });
    }).join("");
  }
  /* ![[Another note]] (or ![[Note#Heading]]) on a line of its own: a box that Work.enrich fills with that
     note (a plain link until then, and where nothing fills it); written in a sentence it's just a link */
  function embeds(text) {
    if (!CFG.urls || !CFG.urls.noteGo) return text;
    return String(text || "").split(/(```[\s\S]*?(?:```|$)|~~~[\s\S]*?(?:~~~|$)|`[^`\n]+`)/).map(function (part, i) {
      return i % 2 ? part : part.replace(/^[ \t]*!\[\[([^\[\]\n]{1,300})\]\][ \t]*$/gm, function (all, ref) {
        var title = ref.split("#")[0].trim() || ref.trim(), attr = escAttr(ref.trim());
        return '\n<div class="wn-embed" data-embed="' + attr + '"><a class="wn-embed-link" href="' + CFG.urls.noteGo + "?title=" + encodeURIComponent(title) + '">' + escAttr(ref.trim()) + "</a></div>\n";
      }).replace(/!\[\[([^\[\]\n]{1,300})\]\]/g, "[[$1]]");
    }).join("");
  }
  function escAttr(v) { return String(v).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }
  /* Formulas ($…$, $$…$$, \(…\), \[…\] — what ChatGPT and Claude write) on pages that load KaTeX. Code is left as it
     is, and $HOME/$PATH stays shell, not maths: a closing $ can't have a letter or digit right after it. */
  function renderMarkdown(text) {
    if (!window.katex) return drawMarkdown(text);
    var maths = [];
    function keep(display) {
      return function (m, tex) { maths.push({ tex: tex, display: display }); return "@@KM" + (maths.length - 1) + "@@"; };
    }
    var parts = String(text || "").split(/(```[\s\S]*?(?:```|$)|~~~[\s\S]*?(?:~~~|$)|`[^`\n]+`)/);
    for (var i = 0; i < parts.length; i += 2) {
      parts[i] = parts[i]
        .replace(/\$\$([\s\S]+?)\$\$/g, keep(true))
        .replace(/\\\[([\s\S]+?)\\\]/g, keep(true))
        .replace(/\\\(([\s\S]+?)\\\)/g, keep(false))
        .replace(/(^|[^\\$\w])\$(?!\s)([^\n$]+?)(?<!\s)\$(?!\w)/g, function (m, pre, tex) { return pre + keep(false)(m, tex); });
    }
    return drawMarkdown(parts.join("")).replace(/@@KM(\d+)@@/g, function (m, n) {
      var x = maths[+n];
      try { return katex.renderToString(x.tex, { displayMode: x.display, throwOnError: false, output: "htmlAndMathml" }); }
      catch (e) { return m; }
    });
  }
  function drawMarkdown(text) {
    text = highlights(wikiLinks(embeds(text)));
    if (window.marked && window.DOMPurify) {
      var html = marked.parse(text || "", { gfm: true, breaks: true });
      // to-do boxes can be ticked where the preview allows it ([data-tick]); elsewhere CSS keeps them still
      return codeBoxes(DOMPurify.sanitize(html)).replace(/<input (?=[^>]*type="checkbox")(?=[^>]*disabled="")([^>]*)>/g, function (all, attrs) {
        return '<input type="checkbox" class="md-tick" tabindex="-1"' + (/checked=""/.test(attrs) ? ' checked=""' : "") + ">";
      });
    }
    var esc = (text || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    return "<p>" + esc.replace(/\n\n+/g, "</p><p>").replace(/\n/g, "<br>") + "</p>";
  }
  window.Work.markdown = renderMarkdown;
  window.Work.noteDraftKey = function (id) { return "work-note-draft:" + ME + ":" + id; };
  /* Ticking a box in a drawn note: the index-th to-do line of the Markdown is turned over
     (the same lines as services.todo_lines on the server: none inside a ``` block) */
  var CHECK_LINE = /^([ \t]*(?:>[ \t]?)*[ \t]*(?:[-*+]|\d+[.)])[ \t]+)\[( |x|X)\]/, FENCE = /^[ \t]*(```|~~~)/;
  window.Work.tickMarkdown = function (text, index) {
    var lines = String(text || "").split("\n"), code = false, n = -1;
    for (var i = 0; i < lines.length; i++) {
      if (FENCE.test(lines[i])) { code = !code; continue; }
      var m = !code && CHECK_LINE.exec(lines[i]);
      if (m && ++n === index) {
        var at = m[1].length + 1;
        lines[i] = lines[i].slice(0, at) + (m[2] === " " ? "x" : " ") + lines[i].slice(at + 1);
        return lines.join("\n");
      }
    }
    return text;
  };
  d.addEventListener("click", function (e) {
    var box = e.target.closest && e.target.closest("input.md-tick"), area = box && box.closest("[data-tick]");
    if (!area) return;
    e.preventDefault();               // the note changes, and is drawn again with the box ticked
    var index = Array.prototype.indexOf.call(area.querySelectorAll("input.md-tick"), box);
    area.dispatchEvent(new CustomEvent("md-tick", { detail: { index: index }, bubbles: true }));
  });


  /* ── An icon for a note (Notion's page icon): a grid of common ones, or any emoji typed or pasted;
     Work.pickIcon(button, now) → the one chosen, "" to take it off, or null when closed without one. ── */
  var ICONS = ("📝 📌 💡 ⭐ 🔥 ✅ 🎯 🧠 📚 📖 ✏️ 🎓 🧪 💻 🐍 ⚙️ 🐞 🚀 📊 💼 💰 🧾 🏦 🛒 🏠 🍳 💪 🏃 ✈️ 🌍 📅 ⏰ " +
               "🗂️ 📦 🔒 🔑 🎵 🎨 📷 🌱 ❤️ 😊 🙏 🎉 ⚡ 🧩 📣 💬").split(" ");
  window.Work.pickIcon = function (anchor, current) {
    return new Promise(function (resolve) {
      var pop = d.createElement("div"), done = false;
      pop.className = "wicon-pop"; pop.setAttribute("role", "dialog"); pop.setAttribute("aria-label", t("iconPick", "Pick an icon"));
      pop.innerHTML = '<div class="wicon-grid">' + ICONS.map(function (e) {
        return '<button type="button" class="wicon-btn' + (e === current ? " is-on" : "") + '" data-icon="' + e + '">' + e + "</button>"; }).join("") + "</div>" +
        '<div class="wicon-foot"><input type="text" class="form-input input-compact wicon-own" maxlength="16" autocomplete="off" placeholder="' + escAttr(t("iconType", "Or type / paste one")) + '">' +
        (current ? '<button type="button" class="btn btn-ghost btn-sm" data-icon="">' + escAttr(t("iconRemove", "Remove")) + "</button>" : "") + "</div>";
      d.body.appendChild(pop);
      var r = anchor.getBoundingClientRect(), w = pop.offsetWidth, h = pop.offsetHeight;
      pop.style.left = Math.max(8, Math.min(r.left, innerWidth - w - 8)) + "px";
      pop.style.top = (r.bottom + 6 + h > innerHeight - 8 ? Math.max(8, r.top - h - 6) : r.bottom + 6) + "px";
      function close(v) {
        if (done) return; done = true;
        pop.remove(); d.removeEventListener("mousedown", outside, true); d.removeEventListener("keydown", esc, true);
        if (anchor.focus) anchor.focus({ preventScroll: true });
        resolve(v);
      }
      function outside(e) { if (!pop.contains(e.target)) close(null); }
      function esc(e) { if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(null); } }
      pop.addEventListener("click", function (e) { var b = e.target.closest("[data-icon]"); if (b) close(b.getAttribute("data-icon")); });
      var own = pop.querySelector(".wicon-own");
      own.addEventListener("keydown", function (e) { if (e.key === "Enter") { e.preventDefault(); var v = own.value.replace(/\s+/g, ""); if (v) close(v.slice(0, 16)); } });
      own.addEventListener("input", function () {          // one emoji pasted or picked from the keyboard: that's it
        var v = own.value.trim();
        if (v && window.Intl && Intl.Segmenter && /\p{Extended_Pictographic}/u.test(v) && [...new Intl.Segmenter().segment(v)].length === 1) close(v);
      });
      setTimeout(function () { d.addEventListener("mousedown", outside, true); }, 0);
      d.addEventListener("keydown", esc, true);
      var on = pop.querySelector(".wicon-btn.is-on") || pop.querySelector(".wicon-btn"); if (on) on.focus({ preventScroll: true });
    });
  };

  /* ── Categories: the person's own tree, shared by notes and exam notes (Backend › Databases › Indexing).
     Work.categoryPicker(url) is mixed into a page's Alpine data: the pop-up to pick any number for a note
     (or one to show), chips, add / rename / move / delete. The page brings setCategory(id) and reload(). ── */
  window.Work.withCategories = function (obj, url) {      // into an object that has getters: only what it hasn't got
    var add = Work.categoryPicker(url);
    Object.keys(add).forEach(function (k) { if (!(k in obj)) obj[k] = add[k]; });
    return obj;
  };
  window.Work.categoryPicker = function (url) {
    return {
      cats: [], catN: {}, category: null, catOpen: false, catMode: "pick", catList: [], catThen: null,
      catQuery: "", catShut: {}, catManage: false, catUnder: null, catNewName: "", catEdit: null,
      t: function (key, fallback) { return t(key, fallback); },
        catOf: function (id) { return this.cats.find(function (c) { return c.id === id; }); },
        catChips: function (ids) { var self = this; return (ids || []).map(function (id) { return self.catOf(id); }).filter(Boolean); },
        catLabel: function () {
          if (this.category === null) return t("catAll", "All categories");
          if (this.category === "none") return t("catNone", "No category");
          var c = this.catOf(this.category);
          return c ? c.name : t("catAll", "All categories");
        },
        catBranch: function (id) {       // {id: true} for the category and what's under it
          var out = {}, cats = this.cats, grew = true;
          out[id] = true;
          while (grew) { grew = false; cats.forEach(function (c) { if (out[c.parent] && !out[c.id]) { out[c.id] = true; grew = true; } }); }
          return out;
        },
        catUp: function (ids) {          // these categories and all they're inside, each once
          var self = this, out = {};
          ids.forEach(function (id) { for (var c = self.catOf(id); c && !out[c.id]; c = self.catOf(c.parent)) out[c.id] = true; });
          return Object.keys(out);
        },
        catCount: function (c) { return this.catN[c.id] || 0; },
        catRows: function () {
          var q = this.catQuery.trim().toLowerCase(), shut = this.catShut, hidden = {};
          if (q) return this.cats.filter(function (c) { return c.path.toLowerCase().indexOf(q) >= 0; });
          return this.cats.filter(function (c) {
            if (hidden[c.parent] || shut[c.parent]) { hidden[c.id] = true; return false; }
            return true;
          });
        },
        catCanMake: function () {
          var q = this.catQuery.trim().toLowerCase();
          return !!q && !this.cats.some(function (c) { return c.name.toLowerCase() === q || c.path.toLowerCase() === q; });
        },
        catOpenUp: function () {
          var self = this;
          this.catOpen = true; this.catQuery = ""; this.catManage = false; this.catUnder = null; this.catEdit = null;
          fetch(url, { credentials: "same-origin", headers: { Accept: "application/json" } }).then(function (r) { return r.json(); })
            .then(function (r) { if (r.ok) { self.cats = r.categories; if (r.counts) self.catN = r.counts; } }).catch(function () { /* no signal: the ones on this page */ });
          this.$nextTick(function () { if (self.$refs.catFind && window.matchMedia("(min-width: 640px)").matches) self.$refs.catFind.focus(); });
        },
        pickCats: function (list, then) { this.catMode = "pick"; this.catList = list; this.catThen = then || null; this.catOpenUp(); },
        showCats: function () { this.catMode = "filter"; this.catThen = null; this.catOpenUp(); },
        catDone: function () { this.catOpen = false; var then = this.catThen; this.catThen = null; if (then) then(); },
        catRemove: function (list, id) { var i = list.indexOf(id); if (i >= 0) list.splice(i, 1); },
        catChoose: function (c) {
          if (this.catMode === "filter") { this.catOpen = false; this.setCategory(c.id); return; }
          var i = this.catList.indexOf(c.id);
          if (i >= 0) this.catList.splice(i, 1); else this.catList.push(c.id);
        },
        catEnter: function () {
          if (this.catCanMake()) return this.catMake(this.catQuery, "");
          var rows = this.catRows();
          if (this.catQuery.trim() && rows.length) { this.catChoose(rows[0]); this.catQuery = ""; }
        },
        /* what changes the tree needs the server: an answer with the new tree, or a word that it didn't happen */
        catSend: function (fields) {
          var self = this;
          return ask(url, fields).then(function (r) {
            if (!r) { toast(t("catOffline", "Adding or changing a category needs a connection."), "warn"); return null; }
            if (!r.ok) { toast(r.error || t("notSaved", "Not saved."), "warn"); return null; }
            self.cats = r.categories;
            return r;
          });
        },
        catMake: function (name, parent) {
          var self = this;
          this.catSend({ action: "add", name: name, parent: parent }).then(function (r) {
            if (!r) return;
            self.catQuery = ""; self.catUnder = null; self.catNewName = "";
            if (parent) self.catShut[parent] = false;
            if (self.catMode === "pick" && self.catList.indexOf(r.id) < 0) self.catList.push(r.id);
          });
        },
        catAddUnder: function (c) { this.catEdit = null; this.catNewName = ""; this.catUnder = c.id; },
        catStartEdit: function (c) { this.catUnder = null; this.catEdit = { id: c.id, name: c.name, parent: c.parent === null ? "" : String(c.parent) }; },
        catParents: function (c) {       // where it can go: anywhere but inside itself
          var mine = this.catBranch(c.id);
          return this.cats.filter(function (x) { return !mine[x.id]; });
        },
        catSaveEdit: function () {
          var self = this, e = this.catEdit;
          this.catSend({ action: "change", id: e.id, name: e.name, parent: e.parent }).then(function (r) { if (r) self.catEdit = null; });
        },
        catDelete: function (c) {
          var self = this;
          FT.ask({ message: t("catDeleteAsk", "Delete “%(name)s” and everything inside it?").replace("%(name)s", c.name), danger: true, after: "back" }).then(function (sure) {
            if (!sure) return;
            self.catSend({ action: "delete", id: c.id }).then(function (r) {
              if (!r) return;
              if (self.category !== null && !self.catOf(self.category) && self.category !== "none") self.category = null;
              self.catRemove(self.catList, c.id);
              if (self.reload) self.reload();
              undoable(t("catDeleted", "Category deleted"), r.undo, function () { self.catRefresh(); });
            });
          });
        },
        catRefresh: function () {
          var self = this;
          fetch(url, { credentials: "same-origin", headers: { Accept: "application/json" } }).then(function (r) { return r.json(); })
            .then(function (r) { if (r.ok) { self.cats = r.categories; if (self.reload) self.reload(); } });
        }
    };
  };

  /* ── Editing in the preview (Obsidian's live preview, Notion's blocks) ───────────────────────────
     Work.live(el, { text, set(text), note, attrs }) draws Markdown into el one block at a time (a paragraph,
     a list, a code block, a table, a formula…). Clicking a block turns it back into its own Markdown right
     there, the caret where it was clicked; Esc, Ctrl+Enter or clicking elsewhere draws it again. ↑ on its
     first line and ↓ on its last go to the block before or after; Backspace in an empty one removes it.
     Each block has a ⋮⋮ handle: add below, turn into a heading / list / to-do / quote / code, duplicate,
     move up or down, copy, delete (with Undo). The writing keys work in the block too (static/js/writing.js:
     lists, Tab, Ctrl+B, the "/" menu, pasting), and every change goes to set() as it's typed, so a note
     saves itself just as it does from the Write box. */
  var LIVE_SKIP = "a, button, input, select, textarea, label, summary, video, audio, iframe, .md-menu, .wn-embed, .wn-tasks, [data-no-edit]";
  var GRIP = '<svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor" aria-hidden="true"><circle cx="9" cy="6" r="1.6"/><circle cx="15" cy="6" r="1.6"/><circle cx="9" cy="12" r="1.6"/><circle cx="15" cy="12" r="1.6"/><circle cx="9" cy="18" r="1.6"/><circle cx="15" cy="18" r="1.6"/></svg>';
  var PLUS = '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>';
  var liveActive = null, liveMenuEl = null, liveMenuAt = 0;

  function liveHalf(b) {          // a formula or a <details> broken by an empty line: it goes on in the next block
    if (b.type === "code") return false;
    var md = b.md;
    return (md.match(/\$\$/g) || []).length % 2 === 1 || (md.match(/\\\[/g) || []).length > (md.match(/\\\]/g) || []).length ||
      (md.match(/<details\b/gi) || []).length > (md.match(/<\/details>/gi) || []).length;
  }
  function liveSplit(text) {
    var s = { head: "", blocks: [] }, toks = null;
    if (!text) return s;
    try { toks = window.marked && marked.lexer ? marked.lexer(text, { gfm: true }) : null; } catch (e) { toks = null; }
    (toks || []).forEach(function (tk) {
      var raw = tk.raw || "";
      if (tk.type === "space" || !raw.trim()) {
        if (s.blocks.length) s.blocks[s.blocks.length - 1].tail += raw; else s.head += raw;
        return;
      }
      var m = /^([\s\S]*?)(\n*)$/.exec(raw);
      s.blocks.push({ md: m[1], tail: m[2], type: tk.type });
    });
    if (!toks || liveJoin(s) !== text) {        // the parts must add up to the text exactly; if not, it's one block
      var w = /^(\n*)([\s\S]*?)(\n*)$/.exec(text);
      return { head: w[1], blocks: w[2] ? [{ md: w[2], tail: w[3], type: "all" }] : [] };
    }
    for (var i = 0; i < s.blocks.length - 1; i++) {
      var b = s.blocks[i];
      if (liveHalf(b)) { var n = s.blocks.splice(i + 1, 1)[0]; b.md += b.tail + n.md; b.tail = n.tail; i--; }
    }
    return s;
  }
  function newlines(v) { return (String(v).match(/\n/g) || []).length; }
  function liveJoin(s) {
    var list = s.blocks.filter(function (b) { return b.md.trim(); }), out = s.head;
    list.forEach(function (b, i) {
      var next = list[i + 1], tail = b.tail;
      if (next && (b.fresh || next.fresh) && newlines(tail) < 2) tail = "\n\n";   // a block that's new stands apart from its neighbours
      else if (!next && b.fresh) tail = "";
      out += b.md + tail;
    });
    return out;
  }
  function liveText(el) {
    var st = el._live; st.text = liveJoin(st.split);
    if (st.opts && st.opts.set) st.opts.set(st.text);
  }
  function liveDraw(el) {
    var st = el._live, html = "", grip = t("liveGrip", "Options for this part"), ro = !!st.opts.readOnly;
    st.split.blocks.forEach(function (b, i) {
      if (!b.md.trim()) return;
      html += ro ? '<div class="md-block" data-i="' + i + '">' + renderMarkdown(b.md) + "</div>"
        : '<div class="md-block" data-i="' + i + '" tabindex="0"><button type="button" class="md-handle" aria-haspopup="menu" aria-expanded="false" aria-label="' +
          escAttr(grip) + '" title="' + escAttr(grip) + '">' + GRIP + "</button>" + renderMarkdown(b.md) + "</div>";
    });
    if (!html) html = '<p class="md-empty">' + escAttr(ro ? t("emptyNote", "Nothing written yet.") : (st.opts.empty || t("liveEmpty", "Nothing here yet. Click to write."))) + "</p>";
    else if (!ro) html += '<button type="button" class="md-add">' + PLUS + "<span>" + escAttr(t("liveAdd", "Click to add more")) + "</span></button>";
    el.classList.toggle("is-read", ro);
    st.ro = ro;
    el.innerHTML = html;
    st.drawn = st.text;
    Work.enrich(el, { note: st.opts.note });
  }
  function fitBox(ta) { if (!GROWS) { ta.style.height = "auto"; ta.style.height = ta.scrollHeight + "px"; } }
  function caretFromClick(e) {            // the words either side of where the block was clicked
    var node = null, off = 0;
    if (d.caretRangeFromPoint) { var r = d.caretRangeFromPoint(e.clientX, e.clientY); if (r) { node = r.startContainer; off = r.startOffset; } }
    else if (d.caretPositionFromPoint) { var p = d.caretPositionFromPoint(e.clientX, e.clientY); if (p) { node = p.offsetNode; off = p.offset; } }
    if (!node || node.nodeType !== 3) return null;
    return { before: node.data.slice(Math.max(0, off - 20), off), after: node.data.slice(off, off + 20) };
  }
  function caretIn(md, hint) {
    if (hint === "start") return 0;
    if (!hint || hint === "end") return md.length;
    var both = hint.before + hint.after, at;
    if (both.trim() && (at = md.indexOf(both)) >= 0) return at + hint.before.length;
    if (hint.before.trim() && (at = md.lastIndexOf(hint.before)) >= 0) return at + hint.before.length;
    if (hint.after.trim() && (at = md.indexOf(hint.after)) >= 0) return at;
    return md.length;
  }
  function edgeRow(ta, pos, up) {          // is the caret on the box's first (up) or last line, as it wraps?
    var v = ta.value;
    if (up ? v.lastIndexOf("\n", pos - 1) >= 0 : v.indexOf("\n", pos) >= 0) return false;
    if (!window.FTWriting || !FTWriting.caretXY) return true;
    var r = ta.getBoundingClientRect(), cs = getComputedStyle(ta), lh = parseFloat(cs.lineHeight) || 24, y = FTWriting.caretXY(ta, pos).y;
    return up ? y - r.top <= parseFloat(cs.paddingTop) + lh * 1.5 : r.bottom - parseFloat(cs.paddingBottom) - y <= lh * 0.5;
  }

  function liveBegin(el, i, hint) {
    liveCommit(el);
    var st = el._live, b = st.split.blocks[i];
    var div = b && el.querySelector('.md-block[data-i="' + i + '"]');
    if (!div) return;
    liveCloseMenu();
    var ta = d.createElement("textarea");
    ta.className = "md-edit" + (/^\s*(```|~~~)/.test(b.md) ? " is-code" : "");
    ta.setAttribute("data-md", "");
    Object.keys(st.opts.attrs || {}).forEach(function (k) { if (st.opts.attrs[k] != null) ta.setAttribute(k, st.opts.attrs[k]); });
    ta.setAttribute("aria-label", t("liveEditing", "Editing this part — Esc when done"));
    ta.rows = 1; ta.value = b.md;
    div.classList.add("is-editing"); div.removeAttribute("tabindex"); div.innerHTML = ""; div.appendChild(ta);
    st.editing = { i: i, ta: ta }; liveActive = el;
    fitBox(ta);
    ta.focus({ preventScroll: true });
    var at = caretIn(b.md, hint); ta.setSelectionRange(at, at);
    var box = ta.getBoundingClientRect();
    if (box.top < 0 || box.bottom > innerHeight) ta.scrollIntoView({ block: "nearest" });
    ta.addEventListener("input", function () { b.md = ta.value; liveText(el); fitBox(ta); });
    ta.addEventListener("keydown", function (e) {
      if (e.isComposing) return;
      if (e.key === "Escape" || (e.key === "Enter" && (e.ctrlKey || e.metaKey))) {
        e.preventDefault(); e.stopPropagation(); liveFinish(el, true); return;
      }
      if (e.altKey || e.ctrlKey || e.metaKey || e.shiftKey || ta.selectionStart !== ta.selectionEnd) return;
      var pos = ta.selectionStart;
      if (e.key === "ArrowUp" && edgeRow(ta, pos, true)) { e.preventDefault(); liveStep(el, -1); }
      else if (e.key === "ArrowDown" && edgeRow(ta, pos, false)) { e.preventDefault(); liveStep(el, 1); }
      else if (e.key === "Backspace" && !ta.value) { e.preventDefault(); liveStep(el, -1); }
    });
    ta.addEventListener("focusout", function (e) {
      var to = e.relatedTarget;
      if (to && (el.contains(to) || (liveMenuEl && liveMenuEl.contains(to)))) return;     // another block, a handle: their own click takes over
      setTimeout(function () {
        if (st.editing && st.editing.ta === ta && d.activeElement !== ta && d.hasFocus()) liveFinish(el, false);
      }, 0);
    });
  }
  /* draws the block again (it may have become several, or none); returns how many blocks there are now more than before */
  function liveFinish(el, focus) {
    var st = el && el._live, e = st && st.editing;
    if (!e) return 0;
    st.editing = null; if (liveActive === el) liveActive = null;
    var blocks = st.split.blocks, b = blocks[e.i];
    b.md = e.ta.value.replace(/(\n[ \t]*)+$/, "");
    if (!b.md.trim() && e.i > 0 && newlines(b.tail) > newlines(blocks[e.i - 1].tail)) blocks[e.i - 1].tail = b.tail;    // what came after stays apart
    var before = blocks.length;
    liveText(el);
    st.split = liveSplit(st.text);
    liveDraw(el);
    liveCommit(el);
    if (focus) { var div = el.querySelector('.md-block[data-i="' + Math.min(e.i, st.split.blocks.length - 1) + '"]'); if (div) div.focus({ preventScroll: true }); }
    return st.split.blocks.length - before;
  }
  function liveStep(el, dir) {
    var i = el._live.editing.i, grew = liveFinish(el, false), n = el._live.split.blocks.length;
    var to = dir < 0 ? i - 1 : i + 1 + grew;
    if (to >= 0 && to < n) liveBegin(el, to, dir < 0 ? "end" : "start");
    else if (dir > 0) liveAppend(el);
    else if (n) liveBegin(el, 0, "start");
  }
  function liveAppend(el) {
    var st = el._live;
    if (st.editing) liveFinish(el, false);
    st.split.blocks.push({ md: "", tail: "", type: "paragraph", fresh: true });
    liveDraw(el);
    var i = st.split.blocks.length - 1, div = d.createElement("div");
    div.className = "md-block"; div.setAttribute("data-i", i);
    var add = el.querySelector(".md-add, .md-empty");
    if (add && add.classList.contains("md-empty")) add.remove();
    el.insertBefore(div, el.querySelector(".md-add"));
    liveBegin(el, i, "end");
  }
  /* ⋮⋮: what can be done with one block */
  var TURN = ["p", "h1", "h2", "h3", "bullet", "numbered", "todo", "quote", "code"];
  function turnInto(md, kind) {
    var fence = /^\s*(```|~~~)[^\n]*\n([\s\S]*?)\n?\s*(```|~~~)\s*$/.exec(md);
    var text = fence ? fence[2] : md;
    var lines = text.split("\n").map(function (l) {
      return l.replace(/^[ \t]*(#{1,6}[ \t]+|>[ \t]?|[-*+][ \t]+\[[ xX]\][ \t]+|[-*+][ \t]+|\d+[.)][ \t]+)/, "");
    });
    var done = text.split("\n").map(function (l) { return /^[ \t]*[-*+][ \t]+\[[xX]\]/.test(l); });
    if (kind === "code") return "```\n" + (fence ? fence[2] : md) + "\n```";
    if (/^h[123]$/.test(kind)) return "#".repeat(+kind.charAt(1)) + " " + lines.filter(function (l) { return l.trim(); }).join(" ");
    var n = 0;
    return lines.map(function (l, k) {
      if (!l.trim()) return l;
      if (kind === "bullet") return "- " + l;
      if (kind === "numbered") return (++n) + ". " + l;
      if (kind === "todo") return "- [" + (done[k] ? "x" : " ") + "] " + l;
      if (kind === "quote") return "> " + l;
      return l;
    }).join("\n");
  }
  function liveCloseMenu(back) {
    if (!liveMenuEl) return;
    var m = liveMenuEl; liveMenuEl = null; m.remove();
    if (m._handle) { m._handle.setAttribute("aria-expanded", "false"); if (back && m._handle.isConnected) m._handle.focus(); }
  }
  function liveMenu(el, i, handle) {
    var st = el._live, open = liveMenuEl && liveMenuEl._handle === handle;
    liveCloseMenu();
    if (open) return;
    var n = st.split.blocks.length, slash = T.slash || {};
    var names = { p: t("liveText", "Text"), h1: slash.h1 || "Heading 1", h2: slash.h2 || "Heading 2", h3: slash.h3 || "Heading 3", bullet: slash.bullet || "Bulleted list",
                  numbered: slash.numbered || "Numbered list", todo: slash.todo || "To-do", quote: slash.quote || "Quote", code: slash.code || "Code block" };
    function item(act, label, extra) { return '<button type="button" role="menuitem" data-act="' + act + '"' + (extra || "") + ">" + escAttr(label) + "</button>"; }
    var m = d.createElement("div");
    m.className = "md-menu"; m.setAttribute("role", "menu"); m._handle = handle;
    m.innerHTML = item("edit", t("liveEdit", "Edit")) + item("below", t("liveBelow", "Add below")) +
      '<p class="md-menu-label">' + escAttr(t("liveTurn", "Turn into")) + '</p><div class="md-turn">' +
      TURN.map(function (k) { return item("turn:" + k, names[k]); }).join("") + "</div>" +
      '<div class="md-menu-sep"></div>' + item("dup", t("liveDup", "Duplicate")) +
      item("up", t("liveUp", "Move up"), i <= 0 ? " disabled" : "") + item("down", t("liveDown", "Move down"), i >= n - 1 ? " disabled" : "") +
      item("copy", t("liveCopy", "Copy as Markdown")) + '<div class="md-menu-sep"></div>' + item("del", t("liveDelete", "Delete"), ' class="is-danger"');
    d.body.appendChild(m);
    liveMenuEl = m; liveMenuAt = Date.now(); handle.setAttribute("aria-expanded", "true");
    var r = handle.getBoundingClientRect(), w = m.offsetWidth, h = m.offsetHeight;
    m.style.left = Math.max(8, Math.min(r.left, innerWidth - w - 8)) + "px";
    m.style.top = (r.bottom + 4 + h > innerHeight - 8 ? Math.max(8, r.top - h - 4) : r.bottom + 4) + "px";
    var first = m.querySelector("button:not([disabled])"); if (first) first.focus({ preventScroll: true });
    m.addEventListener("keydown", function (e) {
      var all = Array.prototype.slice.call(m.querySelectorAll("button:not([disabled])")), at = all.indexOf(d.activeElement);
      if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); liveCloseMenu(true); }
      else if (e.key === "ArrowDown" || e.key === "ArrowRight") { e.preventDefault(); all[(at + 1) % all.length].focus(); }
      else if (e.key === "ArrowUp" || e.key === "ArrowLeft") { e.preventDefault(); all[(at - 1 + all.length) % all.length].focus(); }
      else if (e.key === "Tab") liveCloseMenu();
    });
    m.addEventListener("click", function (e) {
      var b = e.target.closest("button[data-act]"); if (!b || b.disabled) return;
      e.preventDefault(); e.stopPropagation();
      liveCloseMenu();
      liveDo(el, i, b.getAttribute("data-act"));
    });
  }
  function liveDo(el, i, act) {
    var st = el._live, blocks = st.split.blocks, b = blocks[i], was = st.text;
    if (!b) return;
    var redraw = function (focusAt) { liveText(el); st.split = liveSplit(st.text); liveDraw(el); liveCommit(el); var div = focusAt != null && el.querySelector('.md-block[data-i="' + focusAt + '"]'); if (div) div.focus({ preventScroll: true }); };
    var apart = function (k) { if (blocks[k] && newlines(blocks[k].tail) < 2) blocks[k].tail = "\n\n"; };
    if (act === "edit") return liveBegin(el, i, "end");
    if (act === "below") {
      blocks.splice(i + 1, 0, { md: "", tail: "", type: "paragraph", fresh: true });
      liveDraw(el);
      var div = d.createElement("div"), at = el.querySelector('.md-block[data-i="' + i + '"]');
      div.className = "md-block"; div.setAttribute("data-i", i + 1);
      at.parentNode.insertBefore(div, at.nextSibling);         // (the blocks after it were numbered from the list, new one included)
      return liveBegin(el, i + 1, "end");
    }
    if (act.indexOf("turn:") === 0) { b.md = turnInto(b.md, act.slice(5)); apart(i); return redraw(i); }
    if (act === "dup") { apart(i); blocks.splice(i + 1, 0, { md: b.md, tail: "\n\n", type: b.type, fresh: true }); return redraw(i + 1); }
    if (act === "up" || act === "down") {
      var j = act === "up" ? i - 1 : i + 1, o = blocks[j]; if (!o) return;
      apart(Math.min(i, j)); if (Math.max(i, j) < blocks.length - 1) apart(Math.max(i, j));
      var md = b.md, type = b.type; b.md = o.md; b.type = o.type; o.md = md; o.type = type;
      return redraw(j);
    }
    if (act === "copy") {
      var done = function () { toast(t("copied", "Copied"), "good"); };
      if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(b.md).then(done, function () { FT.showText(b.md); }); else FT.showText(b.md);
      return;
    }
    if (act === "del") {
      if (i > 0 && newlines(b.tail) > newlines(blocks[i - 1].tail)) blocks[i - 1].tail = b.tail;
      b.md = "";
      redraw(Math.max(0, i - 1));
      toast(t("liveDeleted", "Part deleted"), "", { label: t("undo", "Undo"), run: function () { undoStep(true); } });
    }
  }
  /* Dragging a part by its handle (Notion): a line shows where it will go, the page scrolls near the
     edges, and it moves there on letting go (Undo on the toast). A click on the handle is still its menu. */
  function liveMoveTo(el, from, to) {        // to: the gap it goes into, 0 (before the first) … n (after the last)
    var st = el._live, blocks = st.split.blocks, was = st.text;
    if (to === from || to === from + 1 || !blocks[from]) return false;
    var endTail = blocks[blocks.length - 1].tail;        // how the text ends stays as it was, whichever part is last now
    var b = blocks.splice(from, 1)[0];
    if (to > from) to--;
    blocks.splice(to, 0, b);
    blocks[blocks.length - 1].tail = endTail;
    [to - 1, to, from - 1, from].forEach(function (k) {         // where it left and where it landed stand apart
      if (k >= 0 && k < blocks.length - 1 && newlines(blocks[k].tail) < 2) blocks[k].tail = "\n\n";
    });
    liveText(el); st.split = liveSplit(st.text); liveDraw(el); liveCommit(el);
    var div = el.querySelector('.md-block[data-i="' + to + '"]');
    if (div) { div.classList.add("is-moved"); setTimeout(function () { div.classList.remove("is-moved"); }, 900); }
    toast(t("liveMoved", "Moved"), "", { label: t("undo", "Undo"), run: function () { undoStep(true); } });
    return true;
  }
  function liveDrag(el, e, handle) {
    var st = el._live, from = +handle.closest(".md-block").getAttribute("data-i"), x0 = e.clientX, y0 = e.clientY;
    var line = null, src = null, gap = null, timer = null, lastY = y0, id = e.pointerId;
    function gapAt(y) {                      // the gap nearest y, between the drawn parts
      var parts = el.querySelectorAll(".md-block[data-i]"), best = 0, top = null;
      for (var k = 0; k < parts.length; k++) {
        var r = parts[k].getBoundingClientRect();
        if (top === null) top = r.top;
        if (y > r.top + r.height / 2) best = k + 1;
      }
      var at = parts[Math.min(best, parts.length - 1)], ar = at.getBoundingClientRect();
      return { i: best, y: best >= parts.length ? ar.bottom + 2 : ar.top - 2, left: el.getBoundingClientRect().left, width: el.getBoundingClientRect().width };
    }
    function edge() {                        // near the top or bottom of the screen: the page scrolls along
      var v = window.visualViewport, top = v ? v.offsetTop : 0, bottom = top + (v ? v.height : innerHeight), dy = 0;
      if (lastY < top + 70) dy = -Math.ceil((top + 70 - lastY) / 4);
      else if (lastY > bottom - 70) dy = Math.ceil((lastY - bottom + 70) / 4);
      if (dy) { window.scrollTo({ top: window.scrollY + dy, behavior: "instant" }); place(); }
      timer = requestAnimationFrame(edge);
    }
    function place() {
      gap = gapAt(lastY);
      line.style.top = gap.y + "px"; line.style.left = gap.left + "px"; line.style.width = gap.width + "px";
      line.classList.toggle("is-same", gap.i === from || gap.i === from + 1);
    }
    function move(ev) {
      if (ev.pointerId !== id) return;
      lastY = ev.clientY;
      if (!line) {
        if (Math.abs(ev.clientY - y0) < 6 && Math.abs(ev.clientX - x0) < 6) return;
        liveCloseMenu();
        line = d.createElement("div"); line.className = "md-drop-line"; d.body.appendChild(line);
        src = handle.closest(".md-block"); src.classList.add("is-dragging");
        el.classList.add("is-dragging"); d.documentElement.classList.add("md-is-dragging");
        timer = requestAnimationFrame(edge);
      }
      ev.preventDefault();
      place();
    }
    function end(ev) {
      if (ev.pointerId !== id) return;
      window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", end); window.removeEventListener("pointercancel", end);
      if (!line) return;                     // no drag: the click opens the menu
      cancelAnimationFrame(timer); line.remove();
      if (src) src.classList.remove("is-dragging");
      el.classList.remove("is-dragging"); d.documentElement.classList.remove("md-is-dragging");
      st.dragged = Date.now();
      if (ev.type === "pointerup" && gap) liveMoveTo(el, from, gap.i);
    }
    window.addEventListener("pointermove", move, { passive: false });
    window.addEventListener("pointerup", end); window.addEventListener("pointercancel", end);
  }
  function liveWire(el) {
    el.addEventListener("pointerdown", function (e) {
      var st = el._live, handle = st && !st.ro && !st.editing && e.button === 0 && e.target.closest(".md-handle");
      if (handle && el.contains(handle)) liveDrag(el, e, handle);
    });
    el.addEventListener("click", function (e) {
      var st = el._live, tg = e.target;
      if (e.defaultPrevented || e.button || !st) return;
      var handle = !st.ro && tg.closest(".md-handle");
      if (handle && st.dragged && Date.now() - st.dragged < 400) { e.preventDefault(); return; }     // the end of a drag, not a click
      if (handle && el.contains(handle)) { e.preventDefault(); liveMenu(el, +handle.closest(".md-block").getAttribute("data-i"), handle); return; }
      if (!st.ro && tg.closest(".md-add, .md-empty")) { e.preventDefault(); liveAppend(el); return; }
      var tick = tg.closest("input.md-tick");
      if (tick) {                         // ticked here, in its own block (the blocks are drawn apart, so the page-wide count doesn't fit)
        e.preventDefault(); e.stopPropagation();
        var tb = tick.closest(".md-block");
        if (!tb || tick.closest(".wn-embed")) return;
        var i0 = +tb.getAttribute("data-i"), k = Array.prototype.indexOf.call(tb.querySelectorAll("input.md-tick"), tick);
        var ed = st.editing, grow = ed ? liveFinish(el, false) : 0, bi = ed && i0 > ed.i ? i0 + grow : i0, blk = st.split.blocks[bi];
        if (!blk) return;
        blk.md = Work.tickMarkdown(blk.md, k); liveText(el); st.split = liveSplit(st.text); liveDraw(el); liveCommit(el);
        return;
      }
      if (st.ro) return;                  // View: to read (a to-do can still be ticked, as on a Keep card)
      if (tg.closest(LIVE_SKIP) || tg.closest(".md-edit")) return;
      var sel = window.getSelection && window.getSelection();
      if (sel && !sel.isCollapsed && el.contains(sel.anchorNode)) return;          // choosing words to copy
      var blockEl = tg.closest(".md-block");
      if (!blockEl || !el.contains(blockEl)) {
        var last = el.querySelector(".md-block:last-of-type");
        if (!st.editing && (!last || e.clientY > last.getBoundingClientRect().bottom)) liveAppend(el);      // below the last block: write on
        return;
      }
      var hint = caretFromClick(e), i = +blockEl.getAttribute("data-i");
      if (st.editing) { if (st.editing.i === i) return; var ei = st.editing.i, g = liveFinish(el, false); if (i > ei) i += g; }
      liveBegin(el, i, hint);
    });
    el.addEventListener("keydown", function (e) {
      if (el._live.ro || !e.target.classList || !e.target.classList.contains("md-block") || e.target.closest(".md-live") !== el) return;
      var i = +e.target.getAttribute("data-i");
      if (e.key === "Enter" && !e.ctrlKey && !e.metaKey && !e.altKey) { e.preventDefault(); liveBegin(el, i, "end"); }
      else if ((e.key === "ArrowDown" || e.key === "ArrowUp") && !e.altKey) {
        var to = el.querySelector('.md-block[data-i="' + (i + (e.key === "ArrowDown" ? 1 : -1)) + '"]');
        if (to) { e.preventDefault(); to.focus(); }
      } else if (e.key === "ContextMenu" || (e.key === "F10" && e.shiftKey)) {
        var h = e.target.querySelector(".md-handle"); if (h) { e.preventDefault(); liveMenu(el, i, h); }
      }
    });
  }
  d.addEventListener("mousedown", function (e) { if (liveMenuEl && !liveMenuEl.contains(e.target) && !e.target.closest(".md-handle")) liveCloseMenu(); });
  var liveW = window.innerWidth;
  window.addEventListener("resize", function () { if (window.innerWidth !== liveW) { liveW = window.innerWidth; liveCloseMenu(); } });
  // (the page settling as a phone's keyboard goes away, just after the menu opened, doesn't close it)
  d.addEventListener("scroll", function (e) { if (liveMenuEl && !liveMenuEl.contains(e.target) && Date.now() - liveMenuAt > 500) liveCloseMenu(); }, true);

  window.Work.live = function (el, opts) {
    if (!el) return;
    var st = el._live;
    if (!st) { st = el._live = { split: { head: "", blocks: [] }, text: "", drawn: null, editing: null, committed: null }; el.classList.add("md-live"); liveWire(el); }
    st.opts = opts || {};
    var text = String(st.opts.text == null ? "" : st.opts.text).replace(/\r\n?/g, "\n");
    if (st.editing) {
      if (text === st.text) return;           // what's being typed, coming back: the block stays open
      st.editing = null; if (liveActive === el) liveActive = null;     // changed somewhere else (a version brought back…): drawn anew
    } else if (text === st.drawn && !!st.opts.readOnly === st.ro) return;
    if (st.opts.readOnly) liveCloseMenu();
    st.text = st.committed = text; st.split = liveSplit(text); liveDraw(el);      // (changed from outside — Write, a version: its own undo)
  };
  /* Before Write / Preview is switched: the block being changed is put back first */
  window.Work.liveDone = function () { liveCloseMenu(); if (liveActive) liveFinish(liveActive, false); };

  /* ── Undo and redo while reading (Notion, Obsidian): Ctrl+Z, Ctrl+Shift+Z or Ctrl+Y outside a text box take back a
     change made in the preview — a part edited and closed, ticked, moved, turned into something else, deleted — or a
     highlight, on a note or an answer. (In a text box the browser's own undo does it, as it always has.) ── */
  var undoDone = [], undoAhead = [];
  function undoPush(entry) {           // { undo(), redo(), alive() }
    undoDone.push(entry); if (undoDone.length > 100) undoDone.shift();
    undoAhead = [];
  }
  function undoStep(back) {
    var from = back ? undoDone : undoAhead, to = back ? undoAhead : undoDone, e;
    while ((e = from.pop()) && e.alive && !e.alive()) { /* (a box no longer on the page: skipped) */ }
    if (!e) { toast(back ? t("nothingToUndo", "Nothing to undo.") : t("nothingToRedo", "Nothing to redo.")); return; }
    (back ? e.undo : e.redo)();
    to.push(e);
    toast(back ? t("undone", "Undone") + " · " + t("redoHow", "Ctrl+Shift+Z redoes") : t("redone", "Redone"));
  }
  // a change made in the preview is kept once it's done: what the text was before it, and is now
  function liveCommit(el) {
    var st = el && el._live;
    if (!st || st.committed == null || st.text === st.committed) { if (st) st.committed = st.text; return; }
    var before = st.committed, after = st.text;
    st.committed = after;
    undoPush({ alive: function () { return d.contains(el); }, undo: function () { liveSetAll(el, before); }, redo: function () { liveSetAll(el, after); } });
  }
  function liveSetAll(el, text) {
    var st = el._live;
    if (st.editing) { st.editing = null; if (liveActive === el) liveActive = null; }
    st.text = st.committed = text; st.split = liveSplit(text); liveDraw(el);
    if (st.opts.set) st.opts.set(text);
  }
  d.addEventListener("keydown", function (e) {
    if (e.defaultPrevented || e.altKey || !(e.ctrlKey || e.metaKey) || (!undoDone.length && !undoAhead.length)) return;
    var k = (e.key || "").toLowerCase(), tg = e.target;
    if (k !== "z" && k !== "y") return;
    if (tg && tg.closest && tg.closest("input, textarea, select, [contenteditable=''], [contenteditable='true']")) return;
    if (d.querySelector("dialog[open]")) return;
    e.preventDefault();
    undoStep(k === "z" && !e.shiftKey);
  });

  /* ── Highlighting, as Kindle, Medium and Notion have it ───────────────────────────────────────────
     Choose words — in a Markdown box, or while reading a note, an answer, a card — and pick a colour from the
     small bar over them (Ctrl+Shift+H: the colour used last). Chosen words already highlighted get another
     colour, or the highlight taken off. In the Markdown it's ==words== (yellow) or =={green}words==.
     Reading: the words chosen are found in the Markdown of the part they're in (a block of Work.live, or a box
     drawn with Work.highlightable), so what's saved is the note itself — the same as writing the marks by hand. */
  var HL_KEY = "ft:hl";
  function hlLast() { try { var c = localStorage.getItem(HL_KEY); return HL_COLORS.indexOf(c) >= 0 ? c : "yellow"; } catch (e) { return "yellow"; } }
  function hlRemember(c) { try { localStorage.setItem(HL_KEY, c); } catch (e) { /* private window */ } }
  function hlOpen(c) { return "==" + (c && c !== "yellow" ? "{" + c + "}" : ""); }
  // the highlights in the Markdown (outside code), in order: [{s, e, inS, inE, color}] — s…e with the marks, inS…inE the words
  function hlSpans(src) {
    var out = [], pos = 0;
    String(src || "").split(CODE_SPLIT).forEach(function (part, i) {
      if (!(i % 2)) {
        var re = new RegExp(HL_RE.source, "g"), m;
        while ((m = re.exec(part))) {
          var s = pos + m.index, open = 2 + (m[1] ? m[1].length + 2 : 0);
          out.push({ s: s, e: s + m[0].length, inS: s + open, inE: s + m[0].length - 2, color: m[1] || "yellow" });
        }
      }
      pos += part.length;
    });
    return out;
  }
  var LINE_MARKS = /^[ \t]*(?:(?:>[ \t]?)+|#{1,6}[ \t]+|(?:[-*+]|\d+[.)])[ \t]+(?:\[[ xX]\][ \t]+)?)*/;
  /* src with s…e highlighted in `color` — or, with color null, its highlights taken off. A highlight can't cross
     a line, so each line chosen gets its own (without its "- " or "## "). Returns { text, s, e } (the words, chosen). */
  function hlApply(src, s, e, color) {
    src = String(src || "");
    var spans = hlSpans(src).filter(function (h) { return h.s < e && h.e > s; });
    var inside = spans.length === 1 && s >= spans[0].inS && e <= spans[0].inE;
    if (color && inside) {                                  // within one highlight: another colour
      var h = spans[0], open = hlOpen(color);
      return { text: src.slice(0, h.s) + open + src.slice(h.inS, h.inE) + "==" + src.slice(h.e), s: h.s + open.length, e: h.s + open.length + (h.inE - h.inS) };
    }
    // take off the highlights it touches (the words chosen grow to cover them all)
    spans.forEach(function (x) { s = Math.min(s, x.s); e = Math.max(e, x.e); });
    for (var k = spans.length - 1; k >= 0; k--) {
      var x = spans[k], cut = x.inS - x.s;
      var map = function (p) { return p <= x.s ? p : p < x.inS ? x.s : p <= x.inE ? p - cut : p < x.e ? x.inE - cut : p - cut - 2; };
      src = src.slice(0, x.s) + src.slice(x.inS, x.inE) + src.slice(x.e);
      s = map(s); e = map(e);
    }
    if (!color) return { text: src, s: s, e: Math.max(s, e) };
    var out = src.slice(0, s), first = -1, last = s, open2 = hlOpen(color);
    src.slice(s, e).split("\n").forEach(function (line, n, all) {
      var lead = n === 0 && s > 0 && src.charAt(s - 1) !== "\n" ? 0 : (LINE_MARKS.exec(line) || [""])[0].length;
      var body = line.slice(lead), l = body.length - body.trimStart().length, r = body.trimEnd().length;
      if (r > l && body.slice(l, r).indexOf("==") < 0) {     // (words with == in them can't be marked: it would end early)
        var words = body.slice(l, r);
        var piece = line.slice(0, lead + l) + open2 + words + "==" + body.slice(r);
        if (first < 0) first = out.length + lead + l + open2.length;
        out += piece; last = out.length - body.slice(r).length - 2;
      } else out += line;
      if (n < all.length - 1) out += "\n";
    });
    out += src.slice(e);
    return { text: out, s: first < 0 ? s : first, e: first < 0 ? s : last };
  }

  // Where words chosen while reading are in the Markdown: the same letters, with any marks (** _ ` == [ ]( ) between them
  var HL_GAP = "(?:[*_~`\\[]|\\]\\([^)\\s]*\\)|\\]|==(?:\\{[a-z]+\\})?)*";
  var HL_WS = HL_GAP + "\\s+(?:(?:>|[-*+]|\\d+[.)]|#{1,6}|\\[[ xX]\\])[ \\t]+)*" + HL_GAP;
  function hlFind(src, words, nth) {
    words = words.replace(/ /g, " ").trim();
    if (!words || words.length > 3000) return null;
    var pat = "";
    for (var i = 0; i < words.length; i++) {
      var c = words.charAt(i);
      if (/\s/.test(c)) { while (i + 1 < words.length && /\s/.test(words.charAt(i + 1))) i++; pat += HL_WS; continue; }
      pat += c.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + (i < words.length - 1 && !/\s/.test(words.charAt(i + 1)) ? HL_GAP : "");
    }
    var re, m, found = [];
    try { re = new RegExp(pat, "g"); } catch (e) { return null; }
    // only outside code, as highlights() draws them
    var pos = 0;
    src.split(CODE_SPLIT).forEach(function (part, k) {
      if (!(k % 2)) { re.lastIndex = 0; while ((m = re.exec(part))) { found.push([pos + m.index, pos + m.index + m[0].length]); if (!m[0].length) re.lastIndex++; } }
      pos += part.length;
    });
    if (!found.length) return null;
    var at = found[Math.min(nth, found.length - 1)], a = at[0], b = at[1];
    // the marks right around them come too: **bold** stays bold, inside the highlight
    function mark(ch, nb) { return ch === "*" || ch === "~" || ch === "`" || (ch === "_" && !/\w/.test(nb || "")); }
    while (a > 0 && mark(src.charAt(a - 1), src.charAt(a - 2))) a--;
    while (b < src.length && mark(src.charAt(b), src.charAt(b + 1))) b++;
    return [a, b];
  }
  function hlCount(hay, needle) {
    if (!needle) return 0;
    var n = 0, i = hay.indexOf(needle);
    while (i >= 0) { n++; i = hay.indexOf(needle, i + needle.length); }
    return n;
  }
  // the part being read that holds these words: { el (drawn from one piece of Markdown), get(), set(md) }
  function hlTarget(node) {
    var el = node && (node.nodeType === 1 ? node : node.parentElement);
    if (!el || !el.closest || el.closest(".md-edit, textarea, input, .wn-embed, .md-menu")) return null;
    var block = el.closest(".md-block"), live = block && block.closest(".md-live");
    if (block && live && live._live) {
      var st = live._live, i = +block.getAttribute("data-i"), b = st.split.blocks[i];
      if (!b || (st.editing && st.editing.i === i)) return null;
      return { el: block, get: function () { return b.md; }, set: function (md) {
        if (st.editing) liveFinish(live, false);
        b.md = md; liveText(live); st.split = liveSplit(st.text); liveDraw(live); liveCommit(live);
      } };
    }
    var own = el.closest("[data-hl-box]");
    if (own && own._hl) {
      var hl = own._hl;            // (kept: the box may be drawn anew, with a fresh one, before an undo)
      return { el: own, get: function () { return hl.text; }, set: function (md, again) {
        var was = hl.text;
        hl.text = md; hl.set(md);
        if (!again) undoPush({ undo: function () { hl.text = was; hl.set(was); }, redo: function () { hl.text = md; hl.set(md); } });
      } };
    }
    return null;
  }
  /* What the chosen words would change: { target, range, marks (indexes of the highlights it's in), within (all of it is
     highlighted already) } — or null when they aren't all in one part that can be highlighted */
  function hlChoice() {
    var sel = window.getSelection && window.getSelection();
    if (!sel || sel.isCollapsed || !sel.rangeCount) return null;
    var range = sel.getRangeAt(0), a = hlTarget(range.startContainer), z = hlTarget(range.endContainer);
    if (!a || !z || a.el !== z.el || !range.toString().trim()) return null;
    var all = a.el.querySelectorAll("mark"), marks = [], within = true, walker = d.createTreeWalker(a.el, NodeFilter.SHOW_TEXT), tn;
    Array.prototype.forEach.call(all, function (m, n) { if (range.intersectsNode(m)) marks.push(n); });
    while ((tn = walker.nextNode())) {
      if (!range.intersectsNode(tn) || !tn.data.trim()) continue;
      var from = tn === range.startContainer ? range.startOffset : 0, to = tn === range.endContainer ? range.endOffset : tn.data.length;
      if (tn.data.slice(from, to).trim() && !(tn.parentElement && tn.parentElement.closest("mark"))) { within = false; break; }
    }
    return { target: a, range: range, marks: marks, within: within && marks.length > 0 };
  }
  // color: one of HL_COLORS, or null to take it off. Returns false (and says so) when the words can't be found.
  function hlRead(color) {
    var ch = hlChoice();
    if (!ch) return false;
    var tg = ch.target, src = tg.get(), next = null, spans = hlSpans(src);
    if (ch.within && ch.marks.every(function (n) { return spans[n]; })) {
      next = src;
      ch.marks.slice().reverse().forEach(function (n) { var h = spans[n]; next = hlApply(next, h.inS, h.inE, color).text; });
    } else if (color) {
      var pre = d.createRange(); pre.selectNodeContents(tg.el); pre.setEnd(ch.range.startContainer, ch.range.startOffset);
      var words = ch.range.toString(), firstLine = words.trim().split(/\s+/).slice(0, 3).join(" ");
      var at = hlFind(src, words, hlCount(pre.toString().replace(/\s+/g, " "), firstLine));
      if (!at) { toast(t("hlNotFound", "Couldn't highlight that here — switch to Write and choose it there."), "warn"); return false; }
      next = hlApply(src, at[0], at[1], color).text;
    } else return false;
    if (next === src) return true;
    if (color) hlRemember(color);
    window.getSelection().removeAllRanges();
    tg.set(next);
    // (a highlight shows itself; taking one off is said, with Undo)
    if (!color) toast(t("hlOff", "Highlight taken off") + " · Ctrl+Z", "", { label: t("undo", "Undo"), run: function () { undoStep(true); } });
    return true;
  }

  // the small bar over words chosen while reading
  var hlBar = null, hlTimer = 0;
  function hlBarHide() { if (hlBar) hlBar.classList.remove("is-on"); }
  function hlBarMake() {
    hlBar = d.createElement("div"); hlBar.className = "hl-bar"; hlBar.setAttribute("role", "toolbar"); hlBar.setAttribute("aria-label", t("hlBar", "Highlight"));
    var names = { yellow: t("hlYellow", "Yellow"), green: t("hlGreen", "Green"), blue: t("hlBlue", "Blue"), pink: t("hlPink", "Pink"), purple: t("hlPurple", "Purple") };
    hlBar.innerHTML = '<span class="hl-bar-label" aria-hidden="true" title="Ctrl+Shift+H · Ctrl+Z">' + HL_PEN + "<kbd>Ctrl Shift H</kbd></span>" + HL_COLORS.map(function (c) {
      var name = escAttr(t("hlIn", "Highlight: %(colour)s").replace("%(colour)s", names[c]));
      return '<button type="button" class="hl-dot" data-hl-c="' + c + '" title="' + name + '" aria-label="' + name + '"></button>';
    }).join("") + '<button type="button" class="hl-dot hl-off" data-hl-c="" title="' + escAttr(t("hlRemove", "Take the highlight off")) + '" aria-label="' +
      escAttr(t("hlRemove", "Take the highlight off")) + '">' + HL_ERASE + "</button>";
    hlBar.addEventListener("mousedown", function (e) { e.preventDefault(); });          // the words stay chosen
    hlBar.addEventListener("click", function (e) {
      var b = e.target.closest("[data-hl-c]"); if (!b) return;
      e.preventDefault(); hlRead(b.getAttribute("data-hl-c") || null); hlBarHide();
    });
    d.body.appendChild(hlBar);
  }
  function hlBarShow() {
    var ch = hlChoice();
    if (!ch) return hlBarHide();
    if (!hlBar) hlBarMake();
    hlBar.classList.toggle("has-marks", ch.marks.length > 0);
    var last = hlLast();
    hlBar.querySelectorAll(".hl-dot[data-hl-c]").forEach(function (b) { b.classList.toggle("is-last", b.getAttribute("data-hl-c") === last); });
    hlBar.classList.add("is-on");
    var rs = ch.range.getClientRects(), first = rs[0] || ch.range.getBoundingClientRect(), end = rs[rs.length - 1] || first;
    var w = hlBar.offsetWidth, h = hlBar.offsetHeight, touch = window.matchMedia && matchMedia("(pointer: coarse)").matches;
    // on a phone the system's own menu (Copy…) is over the words: this one goes under them
    var top = touch ? end.bottom + 10 : first.top - h - 8;
    if (!touch && top < 8) top = end.bottom + 8;
    if (touch && top + h > innerHeight - 8) top = first.top - h - 10;
    var left = Math.max(8, Math.min((touch ? end.left + end.width / 2 : first.left + (rs.length === 1 ? first.width / 2 : 0)) - w / 2, innerWidth - w - 8));
    hlBar.style.top = Math.round(top) + "px"; hlBar.style.left = Math.round(left) + "px";
  }
  var HL_PEN = '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m9 11-6 6v3h9l3-3"/><path d="m22 12-4.6 4.6a2 2 0 0 1-2.8 0l-5.2-5.2a2 2 0 0 1 0-2.8L14 4"/></svg>';
  var HL_ERASE = '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M6 6l12 12M18 6 6 18"/></svg>';
  d.addEventListener("selectionchange", function () {
    clearTimeout(hlTimer);
    hlTimer = setTimeout(function () {
      var sel = window.getSelection();
      if (!sel || sel.isCollapsed) return hlBarHide();
      if (!d.querySelector(":active") || (window.matchMedia && matchMedia("(pointer: coarse)").matches)) hlBarShow();
    }, 180);
  });
  d.addEventListener("mouseup", function (e) { if (hlBar && hlBar.contains(e.target)) return; setTimeout(function () { var s = window.getSelection(); if (s && !s.isCollapsed) hlBarShow(); else hlBarHide(); }, 0); });
  d.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && hlBar && hlBar.classList.contains("is-on")) { hlBarHide(); return; }
    if ((e.ctrlKey || e.metaKey) && e.shiftKey && !e.altKey && (e.key === "h" || e.key === "H")) {
      var ch = hlChoice();
      if (!ch) return;
      e.preventDefault();
      hlRead(ch.within ? null : hlLast());           // pressed again on a highlight: it comes off
      hlBarHide();
    }
  });
  d.addEventListener("scroll", function () { if (hlBar && hlBar.classList.contains("is-on")) hlBarShow(); }, true);

  /* ── Find while reading (Obsidian's reading view; Chrome's Ctrl+F, but only in the text being read) ─────────
     Ctrl+F over a note or an answer being read ([data-find-read]) opens a small bar: every match is marked, the one
     you're on more strongly; Enter / Shift+Enter go to the next / previous; Aa matches case. Replacing changes the
     Markdown, so Ctrl+H (or "Replace…") hands the words to the box that writes it ([data-find-read] gets "ft:replace").
     Over a Markdown box that's showing ([data-find-write]) Ctrl+F and Ctrl+H open its own find and replace. ── */
  var rf = null;
  var RF_SKIP = ".md-handle, .md-add, .md-menu, .wn-code-bar, button, script, style, .katex-mathml";
  var HAS_HL = !!(window.CSS && CSS.highlights && window.Highlight);
  function rfNodes(el) {
    var out = [], w = d.createTreeWalker(el, NodeFilter.SHOW_TEXT, { acceptNode: function (n) {
      return n.parentElement && n.parentElement.closest(RF_SKIP) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT; } }), n;
    while ((n = w.nextNode())) out.push(n);
    return out;
  }
  function rfSearch() {
    if (!rf) return;
    var q = rf.input.value, nodes = rfNodes(rf.el), flat = "", map = [];
    rf.hits = [];
    nodes.forEach(function (n) { map.push([n, flat.length]); flat += n.data; });
    if (q) {
      var hay = rf.cs ? flat : flat.toLowerCase(), needle = rf.cs ? q : q.toLowerCase(), i = hay.indexOf(needle);
      var spot = function (p, end) {
        for (var k = map.length - 1; k >= 0; k--) if (end ? map[k][1] < p : map[k][1] <= p) return [map[k][0], p - map[k][1]];
        return [map[0][0], 0];
      };
      while (i >= 0 && rf.hits.length < 2000) {
        var a = spot(i, false), b = spot(i + needle.length, true), r = d.createRange();
        r.setStart(a[0], a[1]); r.setEnd(b[0], b[1]); rf.hits.push(r);
        i = hay.indexOf(needle, i + needle.length);
      }
    }
    if (rf.at >= rf.hits.length) rf.at = 0;
    rfDraw(false);
  }
  function rfDraw(go) {
    var n = rf.hits.length, q = rf.input.value;
    rf.bar.classList.toggle("is-none", !!q && !n);
    rf.count.textContent = !q ? "" : n ? t("findOf", "%(at)s of %(n)s").replace("%(at)s", rf.at + 1).replace("%(n)s", n) : t("findNone", "No matches");
    if (HAS_HL) {
      CSS.highlights.set("ft-find", new Highlight(...rf.hits));
      if (n) CSS.highlights.set("ft-find-now", new Highlight(rf.hits[rf.at])); else CSS.highlights.delete("ft-find-now");
    }
    if (go && n) {
      var r = rf.hits[rf.at], box = r.getBoundingClientRect(), top = rf.bar.getBoundingClientRect().bottom + 16;
      if (box.top < top || box.bottom > innerHeight - 24) window.scrollBy({ top: box.top - innerHeight / 2, behavior: "instant" });
      if (!HAS_HL) { var sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(r); }
    }
  }
  function rfStep(dir) { if (!rf || !rf.hits.length) return; rf.at = (rf.at + dir + rf.hits.length) % rf.hits.length; rfDraw(true); }
  function rfClose() {
    if (!rf) return;
    rf.bar.remove(); rf.watch.disconnect();
    if (HAS_HL) { CSS.highlights.delete("ft-find"); CSS.highlights.delete("ft-find-now"); }
    rf = null;
  }
  function rfReplace(el, q) {
    var host = el;
    rfClose();
    host.dispatchEvent(new CustomEvent("ft:replace", { bubbles: true, detail: { q: q || "" } }));
  }
  function rfOpen(el, q) {
    if (rf && rf.el === el) { if (q) rf.input.value = q; rf.input.focus(); rf.input.select(); rfSearch(); rfDraw(true); return; }
    rfClose();
    var bar = d.createElement("div"), x = function (v) { return escAttr(v); };
    bar.className = "md-find rf-find"; bar.setAttribute("role", "search");
    bar.innerHTML = '<div class="md-find-row"><input type="search" class="md-find-q" enterkeyhint="search" autocomplete="off" spellcheck="false" placeholder="' +
      x(t("findHere", "Find in this text")) + '" aria-label="' + x(t("findHere", "Find in this text")) + '"><span class="md-find-n num" aria-live="polite"></span>' +
      '<button type="button" class="md-find-btn" data-f="case" aria-pressed="false" title="Aa" aria-label="Aa"><span aria-hidden="true">Aa</span></button>' +
      '<button type="button" class="md-find-btn" data-f="prev" title="' + x(t("findPrev", "Previous (Shift+Enter)")) + '" aria-label="' + x(t("findPrev", "Previous (Shift+Enter)")) + '"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m6 15 6-6 6 6"/></svg></button>' +
      '<button type="button" class="md-find-btn" data-f="next" title="' + x(t("findNext", "Next (Enter)")) + '" aria-label="' + x(t("findNext", "Next (Enter)")) + '"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"/></svg></button>' +
      (el.hasAttribute("data-find-replace") ? '<button type="button" class="md-find-btn" data-f="rep" title="' + x(t("findReplace", "Replace… (opens Write)")) + ' — Ctrl+H" aria-label="' + x(t("findReplace", "Replace… (opens Write)")) + '"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 7h11M4 12h7M4 17h11M17 10l3 3-3 3"/></svg></button>' : "") +
      '<button type="button" class="md-find-btn" data-f="close" title="' + x(t("findClose", "Close (Esc)")) + '" aria-label="' + x(t("findClose", "Close (Esc)")) + '"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 6l12 12M18 6 6 18"/></svg></button></div>';
    d.body.appendChild(bar);
    rf = { el: el, bar: bar, input: bar.querySelector("input"), count: bar.querySelector(".md-find-n"), hits: [], at: 0, cs: false,
           watch: new MutationObserver(function () { clearTimeout(rf && rf.redo); if (rf) rf.redo = setTimeout(rfSearch, 60); }) };
    rf.watch.observe(el, { childList: true, subtree: true, characterData: true });
    if (q) rf.input.value = q;
    rf.input.addEventListener("input", function () { rf.at = 0; rfSearch(); rfDraw(true); });
    bar.addEventListener("keydown", function (e) {
      if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); rfClose(); }
      else if (e.key === "Enter") { e.preventDefault(); rfStep(e.shiftKey ? -1 : 1); }
      else if ((e.ctrlKey || e.metaKey) && !e.altKey && (e.key === "h" || e.key === "H") && el.hasAttribute("data-find-replace")) { e.preventDefault(); rfReplace(el, rf.input.value); }
      else if ((e.ctrlKey || e.metaKey) && !e.altKey && (e.key === "f" || e.key === "F")) { e.preventDefault(); rf.input.select(); }
    });
    bar.addEventListener("mousedown", function (e) { if (e.target.closest("button")) e.preventDefault(); });
    bar.addEventListener("click", function (e) {
      var b = e.target.closest("[data-f]"); if (!b || !rf) return;
      var k = b.getAttribute("data-f");
      if (k === "close") rfClose();
      else if (k === "prev" || k === "next") rfStep(k === "prev" ? -1 : 1);
      else if (k === "case") { rf.cs = !rf.cs; b.setAttribute("aria-pressed", String(rf.cs)); rfSearch(); rfDraw(true); }
      else if (k === "rep") rfReplace(el, rf.input.value);
    });
    rf.input.focus(); rf.input.select();
    rfSearch(); rfDraw(true);
  }
  function shown(el) { return !!(el && el.offsetParent !== null && el.getClientRects().length); }
  d.addEventListener("keydown", function (e) {
    if (e.defaultPrevented || e.altKey || e.shiftKey || !(e.ctrlKey || e.metaKey)) return;
    var k = (e.key || "").toLowerCase();
    if (k !== "f" && k !== "h") return;
    var tg = e.target;
    // (a Markdown box finds in itself: writing.js; another box to type in, or a list: the browser's own find)
    if (tg && tg.closest && (tg.closest("textarea, select, [contenteditable=''], [contenteditable='true'], .md-find") || (tg.closest("input") && !tg.closest("[data-keys-page]")))) return;
    // the part of the page being read or written: the one holding what's chosen, else the first showing
    var sel = window.getSelection(), at = sel && sel.anchorNode && (sel.anchorNode.nodeType === 1 ? sel.anchorNode : sel.anchorNode.parentElement);
    var all = Array.prototype.filter.call(d.querySelectorAll("[data-find-read], [data-find-write]"), shown);
    // an open question or pop-up before the page behind it; then what's being read before an empty box to write in
    var up = function (x) { return (x.closest("[role=dialog]") ? 2 : 0) + (x.matches("[data-find-read]") ? 1 : 0); };
    all.sort(function (a, b) { return up(b) - up(a); });
    var focused = d.activeElement && d.activeElement !== d.body ? d.activeElement : null;
    if (!at && focused) at = focused;
    var el = (at && all.filter(function (x) { return x.contains(at); })[0]) || all[0];
    if (!el) return;                                    // nothing of ours here: the browser's own find
    var words = sel && !sel.isCollapsed ? sel.toString().trim() : "";
    if (words.length > 80 || words.indexOf("\n") >= 0) words = "";
    e.preventDefault();
    if (el.matches("[data-find-write]")) { if (window.FTWriting && FTWriting.find) FTWriting.find(el, k === "h", words); return; }
    if (k === "h") { if (el.hasAttribute("data-find-replace")) rfReplace(el, words || (rf && rf.input.value) || ""); else rfOpen(el, words); }
    else rfOpen(el, words);
  });
  window.Work.findIn = rfOpen;
  /* The shortcuts sheet (?): the keys of the page you're on first, marked "On this page" — as Notion and Gmail
     show the keys of where you are. A page names its sections: data-keys-page="notes writing reading find". */
  window.Work.keysHere = function (list) {
    var grid = list && list.querySelector(".wk-grid"), page = d.querySelector("[data-keys-page]");
    if (!grid) return;
    grid.querySelectorAll(".wk-here").forEach(function (x) { x.remove(); });
    grid.querySelectorAll(".is-here").forEach(function (x) { x.classList.remove("is-here"); });
    var names = page ? page.getAttribute("data-keys-page").split(/\s+/) : [];
    names.slice().reverse().forEach(function (name) {
      Array.prototype.slice.call(grid.querySelectorAll('[data-keys="' + name + '"]')).reverse().forEach(function (sec) {
        sec.classList.add("is-here"); grid.insertBefore(sec, grid.firstChild);
        var tag = d.createElement("small"); tag.className = "wk-here"; tag.textContent = list.getAttribute("data-here") || "On this page";
        var h = sec.querySelector("h3"); if (h) h.appendChild(tag);
      });
    });
    var box = list.closest(".wk-keys"); if (box) box.scrollTop = 0;
  };
  // something small open over the page (the shortcuts, a find or highlight bar, a question): Esc is for it, not the page
  window.Work.overlayOpen = function () {
    return !!(d.querySelector("dialog[open]") || Array.prototype.some.call(d.querySelectorAll(".wk-keys, .hl-bar.is-on, .md-find, .md-bubble.is-on"), function (x) { return x.offsetParent !== null || getComputedStyle(x).position === "fixed" && getComputedStyle(x).display !== "none"; }));
  };
  d.addEventListener("keydown", function (e) { if (e.key === "Escape" && Work.overlayOpen()) e.ftOverlay = true; }, true);    // (seen before anything closes)
  // a ⌨ button anywhere ([data-keys-open]) opens the sheet
  d.addEventListener("click", function (e) { if (e.target.closest && e.target.closest("[data-keys-open]")) d.dispatchEvent(new CustomEvent("work:help")); });

  window.Work.hl = { colors: HL_COLORS, last: hlLast, remember: hlRemember, spans: hlSpans, apply: hlApply, find: hlFind };
  /* A box drawn from Markdown (Work.markdown) where words chosen while reading can be highlighted: set(md) saves it. */
  window.Work.highlightable = function (el, text, set) {
    if (!el) return;
    if (!set) { delete el._hl; el.removeAttribute("data-hl-box"); return; }
    el._hl = { text: String(text || ""), set: set }; el.setAttribute("data-hl-box", "");
  };

  // A code block gets its language and a Copy button (outside the box that scrolls sideways); diagrams don't.
  function codeBoxes(html) {
    return html.replace(/<pre><code(?: class="language-([\w+#.-]+)")?>([\s\S]*?)<\/code><\/pre>/g, function (all, lang, code) {
      if (lang === "mermaid" || lang === "tasks") return all;      // (drawn by Work.enrich)
      var label = t("copyCode", "Copy code");
      return '<div class="wn-code"' + (lang ? ' data-lang="' + lang + '"' : "") + ">" + all + '<span class="wn-code-bar">' +
        (lang ? '<span class="wn-code-lang">' + lang + "</span>" : "") +
        '<button type="button" class="wn-code-copy" data-copy-code aria-label="' + label + '" title="' + label + '">' + COPY_ICON + "</button></span></div>";
    });
  }
  var COPY_ICON = '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>';
  d.addEventListener("click", function (e) {
    var b = e.target.closest && e.target.closest("[data-copy-code]"); if (!b) return;
    var pre = b.closest(".wn-code").querySelector("pre"); if (!pre) return;
    e.preventDefault(); e.stopPropagation();
    var text = pre.textContent.replace(/\n$/, "");
    var done = function () { b.classList.add("is-done"); setTimeout(function () { b.classList.remove("is-done"); }, 1300); toast(t("copied", "Copied")); };
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(done, function () { FT.showText(text); });
    else FT.showText(text);
  });

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
  // An element with its Markdown in data-md-text (a comment): drawn, with diagrams and coloured code. A Git
  // event's icon (the element's first child, if it's .wtd-git) is kept in front.
  window.Work.paintMarkdown = function (el) {
    if (!window.marked || el._painted) return;
    el._painted = true;
    var icon = el.querySelector(":scope > .wtd-git");
    el.innerHTML = renderMarkdown(el.getAttribute("data-md-text") || "");
    if (icon) el.insertBefore(icon, el.firstChild);
    Work.enrich(el);
  };
  d.addEventListener("DOMContentLoaded", function () {
    d.querySelectorAll("[data-render-markdown]").forEach(function (el) {
      var draw = function () {
        el.innerHTML = renderMarkdown(el.getAttribute("data-render-markdown"));
        Work.enrich(el);
      };
      if (window.marked) draw(); else setTimeout(draw, 300);
    });
  });

  /* ── Cards that change place (pinned, unpinned…) glide there instead of jumping: each child of `box`
     is measured, mutate() moves things (it may return a promise, e.g. Alpine's next tick), and each
     is animated from where it was (FLIP). Without motion, they just move. ── */
  window.Work.flip = function (box, mutate) {
    var still = !box || !box.animate || matchMedia("(prefers-reduced-motion: reduce)").matches, was = [];
    if (!still) Array.prototype.forEach.call(box.children, function (el) { was.push([el, el.getBoundingClientRect()]); });
    return Promise.resolve(mutate()).then(function () {
      if (still) return;
      was.forEach(function (x) {
        var el = x[0], a = x[1]; if (!el.isConnected) return;
        var b = el.getBoundingClientRect(), dx = a.left - b.left, dy = a.top - b.top;
        if ((dx || dy) && b.width) el.animate([{ transform: "translate(" + dx + "px, " + dy + "px)" }, { transform: "none" }], { duration: 280, easing: "cubic-bezier(.2, .7, .2, 1)" });
      });
    });
  };

  /* ── What a drawn note pulls in (apps/productivity/linked.py) ──────────────
     Work.enrich(el, {note: id}) after Markdown is drawn into el: diagrams, coloured code, ```tasks lists
     (the tasks a filter finds, ticked off right there) and ![[embedded notes]] — one level deep
     (`note`: the note being drawn, which can't show itself). */
  var pulled = {};          // url → { at, p }: the preview is drawn again at every key, the lists aren't fetched again
  function pull(url, fresh) {
    var hit = pulled[url];
    if (!fresh && hit && Date.now() - hit.at < 60000) return hit.p;
    var p = fetch(url, { credentials: "same-origin", headers: { Accept: "application/json" } }).then(function (r) { return r.json(); });
    pulled[url] = { at: Date.now(), p: p };
    p.catch(function () { delete pulled[url]; });
    return p;
  }
  function esc(v) { return escAttr(v == null ? "" : v); }
  window.Work.enrich = function (el, opts) {
    if (!el) return;
    opts = opts || {};
    Work.mermaidIn(el);
    if (window.hljs) el.querySelectorAll("pre code:not(.language-mermaid):not(.language-tasks)").forEach(function (c) { if (!c.dataset.highlighted) hljs.highlightElement(c); });
    if (!CFG.urls || !CFG.urls.taskQuery) return;
    el.querySelectorAll("pre > code.language-tasks").forEach(function (code) {
      var box = d.createElement("div");
      box.className = "wn-tasks"; box.setAttribute("data-task-query", code.textContent);
      box.innerHTML = '<p class="wn-tasks-note">' + esc(t("loading", "Loading…")) + "</p>";
      code.parentNode.replaceWith(box);
      drawTasks(box);
    });
    if (opts.inside) return;           // a note shown inside another shows its own ![[…]] as links
    el.querySelectorAll(".wn-embed[data-embed]").forEach(function (box) {
      var ref = box.getAttribute("data-embed");
      pull(CFG.urls.noteEmbed + "?" + new URLSearchParams({ ref: ref, from: opts.note || "" })).then(function (res) {
        if (!box.isConnected) return;
        if (!res.ok) { box.classList.add("is-missing"); box.title = res.error || ""; return; }
        box.innerHTML = '<div class="wn-embed-head"><a href="' + esc(res.url) + '">' + NOTE_ICON + "<span>" + esc(res.title) + (res.heading ? " › " + esc(res.heading) : "") +
          '</span></a></div><div class="wn-embed-body"></div>';
        var inner = box.querySelector(".wn-embed-body");
        inner.innerHTML = res.body.trim() ? renderMarkdown(res.body) : '<p class="wn-tasks-note">' + esc(t("emptyNote", "Nothing written yet.")) + "</p>";
        Work.enrich(inner, { inside: true });
      }, function () { /* offline: the link stays */ });
    });
  };
  var NOTE_ICON = '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M9 13h6M9 17h4"/></svg>';
  function drawTasks(box, fresh) {
    var query = box.getAttribute("data-task-query");
    pull(CFG.urls.taskQuery + "?q=" + encodeURIComponent(query), fresh).then(function (res) {
      if (!box.isConnected) return;
      var h = '<div class="wn-tasks-head"><span class="wn-tasks-chips">' +
        (res.chips.length ? res.chips.map(function (c) { return '<span class="wn-tasks-chip">' + esc(c) + "</span>"; }).join("") : '<span class="wn-tasks-chip">' + esc(t("openTasksAll", "Open tasks")) + "</span>") +
        '<b class="wn-tasks-count">' + res.total + '</b></span><a class="wn-tasks-open" href="' + esc(res.link) + '">' + esc(t("openInTasks", "Open in Tasks")) + " →</a></div>";
      res.errors.forEach(function (e) { h += '<p class="wn-tasks-err">' + esc(e) + "</p>"; });
      if (!res.items.length) h += '<p class="wn-tasks-note">' + esc(t("noTasksMatch", "No tasks match — nothing to do here.")) + "</p>";
      else h += '<ul class="wn-tasks-list">' + res.items.map(function (x) {
        return '<li class="wn-task' + (x.done ? " is-done" : "") + '"><input type="checkbox" class="wn-task-tick" data-task-tick="' + x.id + '"' + (x.done ? " checked" : "") +
          ' aria-label="' + esc(t("markDone", "Done")) + '"><a class="wn-task-title" href="' + esc(x.url) + '">' + esc(x.title) + '</a><span class="wn-task-meta">' +
          (x.priority >= 3 ? '<span class="wn-task-prio" data-p="' + x.priority + '">!' + (x.priority === 4 ? "!" : "") + "</span>" : "") +
          (x.status === "doing" || x.status === "review" ? '<span class="wn-task-status" data-status="' + x.status + '">' + esc(x.statusLabel) + "</span>" : "") +
          (x.project ? '<span class="wn-task-proj"' + (x.color ? ' data-color="' + esc(x.color) + '"' : "") + ">" + esc(x.project) + "</span>" : "") +
          (x.due ? '<span class="wn-task-due' + (x.late ? " is-late" : "") + '">' + esc(x.due) + "</span>" : "") + "</span></li>";
      }).join("") + "</ul>";
      if (res.more) h += '<a class="wn-tasks-more" href="' + esc(res.link) + '">' + esc(t("andMore", "and %s more").replace("%s", res.more)) + "</a>";
      box.innerHTML = h;
    }, function () {
      if (box.isConnected) box.innerHTML = '<p class="wn-tasks-err">' + esc(t("listOffline", "This list needs a connection.")) + "</p>";
    });
  }
  d.addEventListener("change", function (e) {
    var tick = e.target.closest && e.target.closest("[data-task-tick]"); if (!tick) return;
    var id = tick.getAttribute("data-task-tick"), on = tick.checked, row = tick.closest(".wn-task");
    row.classList.toggle("is-done", on);
    if (on) play(CFG.sound ? "chime" : "");
    api(CFG.urls.taskBase + id + "/done/", { done: on ? "1" : "0" }).then(function (res) {
      if (!res.ok) { tick.checked = !on; row.classList.toggle("is-done", !on); return; }
      if (res.next) toast(t("repeatMade", "Next one added") + (res.next.due ? " · " + res.next.due : ""));
      if (res.unblocked && res.unblocked.length) toast(t("unblocked", "Ready to start now:") + " " + res.unblocked.join(", "));
      if (res.queued) return;
      pulled = {};
      // a moment to see it ticked, then every list on the page as it is now (the done one leaves)
      setTimeout(function () { d.querySelectorAll(".wn-tasks[data-task-query]").forEach(function (b) { drawTasks(b, true); }); }, 900);
    });
  });
  // "Link": where another note names this one in plain text, it becomes a [[link]] (apps/productivity/linked.py)
  d.addEventListener("click", function (e) {
    var b = e.target.closest && e.target.closest("[data-link-mention]"); if (!b) return;
    var links = b.closest("[data-note-links]"); if (!links) return;
    e.preventDefault(); b.disabled = true;
    var source = b.getAttribute("data-link-mention");
    api(CFG.urls.noteBase + links.getAttribute("data-note-links") + "/", { action: "link_mentions", source: source === "all" ? "" : source }).then(function (res) {
      if (!res.ok || res.queued) { b.disabled = false; return; }
      var open = !!links.querySelector("details[open]");
      links.outerHTML = res.links;
      var now = d.getElementById("note-links"), more = now && now.querySelector("details");
      if (more && open) more.open = true;
      toast(t("mentionsLinked", "Linked") + (res.count > 1 ? " · " + res.count : ""), "good");
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
             c: "calendar", o: "goals", l: "learning", v: "review", d: "plan", w: "week", m: "diagrams", k: "cards", q: "prep", e: "exam", u: "roadmaps", y: "paths" };
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
    // a page that uses some of these keys itself (the exam board: c = a new question) says so: data-page-keys="c a"
    var own = d.querySelector("[data-page-keys]");
    if (own && own.getAttribute("data-page-keys").split(" ").indexOf(k) >= 0) return;
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
