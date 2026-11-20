/* The floating clock: a small clock over the page when the computer's own clock can't be seen — full screen (F11, or
   the app's own full screen), an installed app's window, or the web view — with what's running under it (the focus
   session's time left, the next timer, the stopwatch). Drag it anywhere; it stays there. Alt+T shows or hides it,
   × hides it, ⚙ chooses when it shows (full screen · full screen and web view · always · never), seconds, 12/24 hours
   and the date. Kept on this device (each screen is different). After clock.js (Clock) and work.js (Work.focus). */
(function () {
  "use strict";
  var d = document, root = d.documentElement, W = window.Work;
  if (!W) return;
  var KEY = "ft-fclock", DEF = { show: "fsweb", seconds: false, h12: false, date: true, hidden: false, x: null, y: null };
  function T(k, f) { return ((W.cfg || {}).text || {})[k] || f; }
  function load() { return Object.assign({}, DEF, W.recall(KEY, {}) || {}); }
  var P = load();
  function keep() { W.store(KEY, P); }
  function pad(n) { return (n < 10 ? "0" : "") + n; }
  function fmt(sec) { sec = Math.max(0, Math.ceil(sec)); var h = Math.floor(sec / 3600), m = Math.floor(sec % 3600 / 60), s = sec % 60; return (h ? h + ":" + pad(m) : m) + ":" + pad(s); }

  function fullScreen() { return !!(d.fullscreenElement || root.getAttribute("data-zen") || matchMedia("(display-mode: fullscreen)").matches); }
  function appWindow() { return matchMedia("(display-mode: standalone)").matches || matchMedia("(display-mode: window-controls-overlay)").matches; }
  function wanted() {
    if (P.hidden || P.show === "off") return false;
    if (P.show === "always") return true;
    if (fullScreen() || appWindow()) return true;
    // (a phone shows its own clock: in its app view, or on a small screen, only in full screen)
    return P.show === "fsweb" && root.getAttribute("data-view") !== "app" && !matchMedia("(max-width: 639.98px)").matches;
  }

  var el = null, timeEl, secEl, ampmEl, dateEl, runEl, menu;
  function build() {
    el = d.createElement("div"); el.className = "fclock"; el.setAttribute("role", "timer"); el.setAttribute("aria-live", "off");
    el.innerHTML = '<div class="fclock-main"><b class="fclock-time num"></b><small class="fclock-sec num"></small><small class="fclock-ampm"></small></div>' +
      '<div class="fclock-date"></div><a class="fclock-run num" hidden></a>' +
      '<div class="fclock-tools"><button type="button" class="fclock-btn" data-act="menu" aria-label="' + T("clockSettings", "Clock settings") + '">⚙</button>' +
      '<button type="button" class="fclock-btn" data-act="hide" aria-label="' + T("clockHide", "Hide the clock (Alt+T)") + '">✕</button></div>' +
      '<div class="fclock-menu" hidden role="menu"></div>';
    timeEl = el.querySelector(".fclock-time"); secEl = el.querySelector(".fclock-sec"); ampmEl = el.querySelector(".fclock-ampm");
    dateEl = el.querySelector(".fclock-date"); runEl = el.querySelector(".fclock-run"); menu = el.querySelector(".fclock-menu");
    el.addEventListener("click", function (e) {
      var b = e.target.closest("[data-act]"); if (!b) return;
      var act = b.getAttribute("data-act");
      if (act === "hide") { hide(true); return; }
      if (act === "menu") { menu.hidden ? openMenu() : (menu.hidden = true); return; }
      if (act === "show") { P.show = b.getAttribute("data-v"); keep(); openMenu(); tick(); return; }
      if (act === "toggle") { var k = b.getAttribute("data-v"); P[k] = !P[k]; keep(); openMenu(); tick(); }
    });
    drag();
    d.body.appendChild(el);
    place();
  }
  function openMenu() {
    var opts = [["fs", T("clockFs", "In full screen")], ["fsweb", T("clockFsWeb", "Full screen and web view")], ["always", T("clockAlways", "Always")], ["off", T("clockOff", "Never")]];
    menu.innerHTML = '<p class="fclock-menu-h">' + T("clockShow", "Show the clock") + "</p>" +
      opts.map(function (o) { return '<button type="button" role="menuitemradio" aria-checked="' + (P.show === o[0]) + '" data-act="show" data-v="' + o[0] + '">' + (P.show === o[0] ? "● " : "○ ") + o[1] + "</button>"; }).join("") +
      '<hr>' + [["seconds", T("clockSeconds", "Seconds")], ["h12", T("clock12", "12-hour (AM/PM)")], ["date", T("clockDate", "Date")]].map(function (o) {
        return '<button type="button" role="menuitemcheckbox" aria-checked="' + !!P[o[0]] + '" data-act="toggle" data-v="' + o[0] + '">' + (P[o[0]] ? "☑ " : "☐ ") + o[1] + "</button>";
      }).join("") + '<p class="fclock-menu-k">Alt+T · ' + T("clockDrag", "drag to move") + "</p>";
    menu.hidden = false;
  }
  function hide(told) {
    P.hidden = true; keep(); tick();
    if (told) W.toast(T("clockHidden", "Clock hidden — Alt+T brings it back"), "", { label: T("undo", "Undo"), run: function () { P.hidden = false; keep(); tick(); } });
  }

  /* drag it anywhere (a short tap is a tap); the place is kept as a share of the screen, so it fits a new size */
  function drag() {
    var sx, sy, ox, oy, moved = false;
    el.addEventListener("pointerdown", function (e) {
      if (e.button !== 0 || e.target.closest("button, a, .fclock-menu")) return;
      var r = el.getBoundingClientRect(); sx = e.clientX; sy = e.clientY; ox = r.left; oy = r.top; moved = false;
      e.preventDefault();                       // (no text selection, no native drag — which would cancel this one)
      el.setPointerCapture(e.pointerId); el.classList.add("is-dragging");
    });
    el.addEventListener("dragstart", function (e) { e.preventDefault(); });
    el.addEventListener("pointermove", function (e) {
      if (!el.classList.contains("is-dragging")) return;
      var dx = e.clientX - sx, dy = e.clientY - sy;
      if (!moved && Math.abs(dx) + Math.abs(dy) < 4) return;
      moved = true; set(ox + dx, oy + dy);
    });
    function end() {
      if (!el.classList.contains("is-dragging")) return;
      el.classList.remove("is-dragging");
      if (!moved) return;
      var r = el.getBoundingClientRect();
      P.x = r.left / Math.max(1, innerWidth - r.width); P.y = r.top / Math.max(1, innerHeight - r.height); keep();
    }
    el.addEventListener("pointerup", end);
    el.addEventListener("pointercancel", end);
  }
  function set(x, y) {
    var r = el.getBoundingClientRect();
    el.style.left = Math.max(6, Math.min(innerWidth - r.width - 6, x)) + "px";
    el.style.top = Math.max(6, Math.min(innerHeight - r.height - 6, y)) + "px";
    el.style.right = el.style.bottom = "auto";
  }
  function place() {
    if (P.x == null) { el.style.left = el.style.top = ""; return; }         // (first time: the corner from the CSS)
    var r = el.getBoundingClientRect();
    set(P.x * (innerWidth - r.width), P.y * (innerHeight - r.height));
  }
  window.addEventListener("resize", function () { if (el && !el.hidden) place(); });

  /* what's running: the focus session, else the timer ending first, else the stopwatch */
  function running() {
    var F = W.focus && W.focus.state;
    if (F && F.running) return { icon: F.mode === "focus" ? "🍅" : "☕", text: fmt(W.focus.left()) };
    var C = window.Clock;
    if (!C) return null;
    var t = C.timers.list.filter(function (x) { return x.running; }).sort(function (a, b) { return a.endsAt - b.endsAt; })[0];
    if (t) return { icon: "⏲", text: fmt(C.timers.left(t)), label: t.label };
    if (C.stopwatch.running) return { icon: "⏱", text: fmt(C.stopwatch.elapsed()) };
    return null;
  }
  function tick() {
    var on = wanted();
    if (!on) { if (el) el.hidden = true; return; }
    if (!el) build();
    el.hidden = false;
    var now = new Date(), h = now.getHours();
    timeEl.textContent = (P.h12 ? ((h % 12) || 12) : pad(h)) + ":" + pad(now.getMinutes());
    secEl.textContent = P.seconds ? ":" + pad(now.getSeconds()) : "";
    ampmEl.textContent = P.h12 ? (h < 12 ? "AM" : "PM") : "";
    dateEl.textContent = P.date ? now.toLocaleDateString(root.lang || undefined, { weekday: "short", day: "numeric", month: "short" }) : "";
    dateEl.hidden = !P.date;
    var r = running();
    runEl.hidden = !r;
    if (r) { runEl.textContent = r.icon + " " + r.text + (r.label ? " · " + r.label : ""); runEl.href = (W.cfg.urls || {}).focus_page || "#"; }
    el.title = now.toLocaleString(root.lang || undefined);
    if (!placed) { placed = true; place(); }          // (once it has its size: the place kept is a share of the room left)
  }
  var placed = false;
  setInterval(tick, 500);
  ["fullscreenchange", "visibilitychange"].forEach(function (t) { d.addEventListener(t, function () { setTimeout(tick, 50); }); });
  new MutationObserver(function () { setTimeout(tick, 50); }).observe(root, { attributes: true, attributeFilter: ["data-zen", "data-view"] });
  d.addEventListener("keydown", function (e) {
    if (e.altKey && !e.ctrlKey && !e.metaKey && e.code === "KeyT") {
      e.preventDefault();
      if (P.hidden || !wanted()) { P.hidden = false; if (!wanted()) P.show = "always"; keep(); tick(); W.toast(T("clockShown", "Clock on — Alt+T hides it")); }
      else hide(false);
    }
    if (e.key === "Escape" && menu && !menu.hidden) menu.hidden = true;
  });
  d.addEventListener("pointerdown", function (e) { if (menu && !menu.hidden && !e.target.closest(".fclock")) menu.hidden = true; });
  window.FloatClock = { prefs: function () { return P; }, set: function (k, v) { P[k] = v; keep(); tick(); }, tick: tick };
  tick();
}());
