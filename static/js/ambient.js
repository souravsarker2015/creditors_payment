/* Background sound — rain, thunder, sea waves, a stream, wind, a fireplace, birds, night crickets, brown / pink / white
   noise, binaural beats — mixed together, each at its own level, as Noisli and myNoise have it. Every sound is made
   here, in the browser (Web Audio): nothing to download, it works offline, and it never repeats exactly.

   What plays (Work.cfg.mixes — set with the mixer, saved at /work/api/sound/; the sounds and ready-made mixes: ambient.py):
   - in the Reader: the reading mix;
   - while a focus session runs: the focus mix; on a break: the break mix (none: quiet — silence rests best);
   - while a timer or the stopwatch runs, if chosen (withTimers): the focus mix;
   - on the focus page, or on every page if chosen (tickEverywhere);
   - while a mixer is open: what it's set to, so you hear what you choose.
   One tab plays: the last one you looked at that has something to play. It fades in and out, and goes quieter while the
   Reader reads aloud. A small pill (bottom right) pauses it for now — or plays it, when the browser waits for a tap. */
(function () {
  "use strict";
  var d = document, W = window.Work;
  if (!W) return;
  var CFG = W.cfg, ME = d.documentElement.getAttribute("data-user") || "0";
  CFG.mixes = CFG.mixes || { focus: "", "break": "", reading: "" };
  function T(k, f) { return (CFG.text || {})[k] || f; }
  function rnd(a, b) { return a + Math.random() * (b - a); }

  /* ── The raw stuff: noise, made once (a few seconds, looped from a random place) ─────────────────────────────── */
  var BUF = {};
  function buffer(c, kind) {
    var key = kind + ":" + c.sampleRate;
    if (BUF[key]) return BUF[key];
    var sr = c.sampleRate, n = Math.floor(sr * (kind === "drops" ? 6 : 9)), buf = c.createBuffer(1, n, sr), x = buf.getChannelData(0), i, peak = 0, sum = 0, mean = 0;
    if (kind === "drops") {            // rain on leaves and roofs: thousands of tiny drops, most of them faint, a few close by
      for (var k = 0; k < 6 * 520; k++) {
        var at = Math.floor(Math.random() * n), len = Math.floor(sr * rnd(0.0015, 0.009)), a = Math.pow(Math.random(), 2.6);
        for (var j = 0; j < len; j++) x[(at + j) % n] += (Math.random() * 2 - 1) * a * Math.pow(1 - j / len, 3);
      }
      for (i = 0; i < n; i++) peak = Math.max(peak, Math.abs(x[i]));
      for (i = 0; i < n; i++) x[i] *= 0.9 / (peak || 1);
    } else {
      var b0 = 0, b1 = 0, b2 = 0, b3 = 0, b4 = 0, b5 = 0, b6 = 0, last = 0;
      for (i = 0; i < n; i++) {
        var w = Math.random() * 2 - 1;
        if (kind === "white") x[i] = w;
        else if (kind === "pink") {            // Paul Kellet's filter
          b0 = 0.99886 * b0 + w * 0.0555179; b1 = 0.99332 * b1 + w * 0.0750759; b2 = 0.969 * b2 + w * 0.153852;
          b3 = 0.8665 * b3 + w * 0.3104856; b4 = 0.55 * b4 + w * 0.5329522; b5 = -0.7616 * b5 - w * 0.016898;
          x[i] = b0 + b1 + b2 + b3 + b4 + b5 + b6 + w * 0.5362; b6 = w * 0.115926;
        } else { last = (last + 0.02 * w) / 1.02; x[i] = last; }      // brown: a slow random walk
      }
      var gap = x[n - 1] - x[0];               // the end meets the start, so the loop has no click
      for (i = 0; i < n; i++) { x[i] -= gap * i / (n - 1); mean += x[i]; }
      mean /= n;
      for (i = 0; i < n; i++) { x[i] -= mean; sum += x[i] * x[i]; }
      var g = 0.25 / Math.sqrt(sum / n || 1);  // all of them equally loud to start with
      for (i = 0; i < n; i++) x[i] *= g;
    }
    BUF[key] = buf;
    return buf;
  }

  var NODES = null;                            // what a sound being made starts (stopped with it)
  function src(c, kind, rate) {
    var s = c.createBufferSource(); s.buffer = buffer(c, kind); s.loop = true;
    if (rate) s.playbackRate.value = rate;
    s.start(c.currentTime, Math.random() * s.buffer.duration);
    if (NODES) NODES.push(s);
    return s;
  }
  function osc(c, type, f) { var o = c.createOscillator(); o.type = type; o.frequency.value = f; o.start(c.currentTime); if (NODES) NODES.push(o); return o; }
  function flt(c, type, f, q) { var x = c.createBiquadFilter(); x.type = type; x.frequency.value = f; if (q != null) x.Q.value = q; return x; }
  function amp(c, v) { var g = c.createGain(); g.gain.value = v; return g; }
  function pan(c, where, into) {
    if (!c.createStereoPanner) return into;
    var p = c.createStereoPanner(); p.pan.value = where; p.connect(into); return p;
  }
  function chain() { for (var i = 1; i < arguments.length; i++) arguments[i - 1].connect(arguments[i]); return arguments[arguments.length - 1]; }
  // something that happens again and again: fn(t) does it at t and says how long until the next time
  function every(first, fn) {
    var next = first;
    return function (from, to) { while (next < to) { var t = Math.max(next, from); next = t + Math.max(0.01, fn(t)); } };
  }
  function both() { var plans = [].slice.call(arguments); return function (from, to) { plans.forEach(function (p) { p(from, to); }); }; }
  function burst(c, out, t, kind, type, f, q, peak, len) {        // a short one-off: a crackle, a roll of thunder
    var s = c.createBufferSource(), x = flt(c, type, f, q), g = amp(c, 0);
    s.buffer = buffer(c, kind); s.loop = true;
    g.gain.setValueAtTime(Math.max(0.001, peak), t); g.gain.exponentialRampToValueAtTime(0.0001, t + len);
    chain(s, x, g, out); s.start(t, Math.random() * 5); s.stop(t + len + 0.05);
    return { filter: x, gain: g };
  }

  /* ── The sounds. Each is made into `out` (its own volume); what moves (waves, birds, crackles) is planned a few
        seconds ahead by the function it gives back — plan(from, to). ─────────────────────────────────────────── */
  var MAKE = {
    rain: function (c, out) {
      chain(src(c, "pink"), flt(c, "highpass", 700, 0.5), flt(c, "lowpass", 8000), amp(c, 0.5), out);       // the hiss of it
      chain(src(c, "drops"), flt(c, "highpass", 1200, 0.7), amp(c, 0.6), out);                            // drops close by
      chain(src(c, "drops", 0.6), flt(c, "bandpass", 900, 0.8), amp(c, 0.45), out);                        // further off, lower
      chain(src(c, "brown"), flt(c, "lowpass", 300), amp(c, 0.35), out);                                    // the weight of it
    },
    thunder: function (c, out) {
      chain(src(c, "brown"), flt(c, "lowpass", 140), amp(c, 0.3), out);                                     // far away, rumbling on
      return every(c.currentTime + rnd(3, 9), function (t) {
        var len = rnd(6, 11), b = burst(c, out, t, "brown", "lowpass", rnd(380, 700), 0.7, 0.0001, len);
        b.gain.gain.cancelScheduledValues(t);
        b.gain.gain.setValueAtTime(0.0001, t); b.gain.gain.exponentialRampToValueAtTime(rnd(1.8, 3), t + rnd(0.1, 0.5));
        b.gain.gain.exponentialRampToValueAtTime(rnd(0.5, 1), t + rnd(1.2, 2)); b.gain.gain.exponentialRampToValueAtTime(0.0001, t + len);
        b.filter.frequency.setValueAtTime(b.filter.frequency.value, t); b.filter.frequency.exponentialRampToValueAtTime(110, t + len);
        return rnd(16, 45);
      });
    },
    waves: function (c, out) {
      var lp = flt(c, "lowpass", 400, 0.4), g = amp(c, 0.15), foam = amp(c, 0);
      chain(src(c, "brown"), lp); chain(src(c, "pink"), amp(c, 0.5), lp); chain(lp, g, out);
      chain(src(c, "white"), flt(c, "highpass", 2500, 0.3), foam, out);                                     // the hiss as a wave breaks
      return every(c.currentTime, function (t) {
        var len = rnd(7, 12), up = len * rnd(0.3, 0.45), peak = rnd(0.8, 1.2);
        g.gain.setTargetAtTime(peak, t, up / 2.5); g.gain.setTargetAtTime(0.1, t + up, (len - up) / 3);
        lp.frequency.setTargetAtTime(rnd(1000, 1700), t, up / 2.5); lp.frequency.setTargetAtTime(320, t + up, (len - up) / 3);
        foam.gain.setTargetAtTime(peak * 0.1, t + up * 0.8, 0.4); foam.gain.setTargetAtTime(0, t + up + 0.6, 1.2);
        return len;
      });
    },
    stream: function (c, out) {
      chain(src(c, "pink"), flt(c, "bandpass", 700, 0.6), amp(c, 0.5), out);
      var white = src(c, "white"), bands = [];
      for (var i = 0; i < 5; i++) { var f = flt(c, "bandpass", rnd(500, 2500), rnd(6, 14)), g = amp(c, 0); chain(white, f, g, out); bands.push([f, g]); }
      return every(c.currentTime, function (t) {          // water over stones: little bubbles, everywhere, all the time
        bands.forEach(function (b) {
          if (Math.random() < 0.45) { b[0].frequency.setTargetAtTime(rnd(350, 3000), t, 0.02); b[1].gain.setTargetAtTime(Math.random() < 0.3 ? 0 : rnd(0.8, 2.6), t, 0.03); }
        });
        return rnd(0.05, 0.14);
      });
    },
    wind: function (c, out) {
      var bp = flt(c, "bandpass", 500, 1), g = amp(c, 0.6);
      chain(src(c, "pink"), bp, g, out);
      chain(src(c, "brown"), flt(c, "lowpass", 200), amp(c, 0.25), out);
      return every(c.currentTime, function (t) {          // gusts
        var len = rnd(2.5, 7);
        bp.frequency.setTargetAtTime(rnd(250, 1200), t, len / 3); bp.Q.setTargetAtTime(rnd(0.7, 3.5), t, len / 3); g.gain.setTargetAtTime(rnd(0.35, 1.4), t, len / 3);
        return len;
      });
    },
    fire: function (c, out) {
      var roar = amp(c, 0.7);
      chain(src(c, "brown"), flt(c, "lowpass", 380), roar, out);
      chain(src(c, "pink"), flt(c, "bandpass", 1800, 0.7), amp(c, 0.04), out);
      return both(
        every(c.currentTime, function (t) {               // crackles: about six a second, at random, now and then a little run of them
          var n = Math.random() < 0.15 ? Math.floor(rnd(3, 8)) : 1;
          for (var i = 0; i < n; i++) {
            var big = Math.random() < 0.12;
            burst(c, out, t + i * rnd(0.01, 0.05), "white", big ? "bandpass" : "highpass", big ? rnd(500, 1200) : rnd(1800, 5000), big ? 1.5 : 0.8,
                  Math.pow(Math.random(), 1.5) * (big ? 2.2 : 1.6), big ? rnd(0.02, 0.05) : rnd(0.002, 0.012));
          }
          return -Math.log(1 - Math.random()) / 6;
        }),
        every(c.currentTime, function (t) { roar.gain.setTargetAtTime(rnd(0.45, 0.95), t, 0.3); return rnd(0.4, 1.2); })      // the flames
      );
    },
    birds: function (c, out) {
      return every(c.currentTime + rnd(0.5, 2), function (t) {
        var g = amp(c, rnd(0.12, 0.35)), kind = Math.floor(Math.random() * 3), base = rnd(2200, 3800), i, n;
        g.connect(pan(c, rnd(-0.8, 0.8), out));
        var note = function (f0, f1, len, at) {
          var o = c.createOscillator(), e = amp(c, 0);
          o.type = "sine"; o.frequency.setValueAtTime(f0, at); o.frequency.exponentialRampToValueAtTime(f1, at + len);
          e.gain.setValueAtTime(0.0001, at); e.gain.exponentialRampToValueAtTime(1, at + len * 0.2); e.gain.exponentialRampToValueAtTime(0.0001, at + len);
          chain(o, e, g); o.start(at); o.stop(at + len + 0.02);
        };
        if (kind === 0) for (i = 0, n = Math.floor(rnd(2, 6)); i < n; i++) note(base, base * rnd(1.3, 1.6), 0.08, t + i * rnd(0.11, 0.16));     // chirps
        else if (kind === 1) { note(base * 0.6, base * 0.75, 0.28, t); note(base * 0.8, base * 0.55, 0.32, t + 0.36); }                         // a whistle
        else for (i = 0, n = Math.floor(rnd(8, 16)); i < n; i++) note(base * 1.2, base * 1.05, 0.035, t + i * 0.05);                         // a trill
        return rnd(1.2, 6);
      });
    },
    night: function (c, out) {
      chain(src(c, "pink"), flt(c, "lowpass", 280), amp(c, 0.15), out);         // the still air
      return both.apply(null, [-0.6, 0.5].map(function (where, k) {               // two crickets, one each side
        var e = amp(c, 0), pulses = k ? 3 : 4, period = rnd(0.55, 0.85);
        chain(osc(c, "sine", rnd(4200, 4700)), e, amp(c, k ? 0.16 : 0.22)).connect(pan(c, where, out));
        return every(c.currentTime + rnd(0, 0.5), function (t) {
          if (Math.random() < 0.06) return rnd(1.5, 4);                             // a rest now and then
          for (var i = 0; i < pulses; i++) {
            var s = t + i * 0.045;
            e.gain.setValueAtTime(0, s); e.gain.linearRampToValueAtTime(1, s + 0.008); e.gain.linearRampToValueAtTime(0, s + 0.03);
          }
          return period * rnd(0.95, 1.05);
        });
      }));
    },
    brown: function (c, out) { chain(src(c, "brown"), amp(c, 1), out); },
    pink: function (c, out) { chain(src(c, "pink"), amp(c, 0.55), out); },
    white: function (c, out) { chain(src(c, "white"), flt(c, "lowpass", 9000), amp(c, 0.32), out); },
    binaural: function (c, out) {         // 200 Hz in one ear, 214 in the other: a 14 Hz "beat" (beta) — headphones
      var m = c.createChannelMerger(2), l = amp(c, 0.3), r = amp(c, 0.3);
      chain(osc(c, "sine", 200), l); chain(osc(c, "sine", 214), r);
      l.connect(m, 0, 0); r.connect(m, 0, 1); m.connect(out);
    },
  };
  // how loud each one is at 100, so they sit together (measured: Ambient.measure)
  // (RMS at 100: ≈ 0.13 each; the deep ones a little more, as the ear hears low sounds as quieter; the bright and the
  // far-off ones — birds, crickets — less, as they carry)
  var LOUD = { rain: 1, thunder: 1, waves: 0.95, stream: 1.25, wind: 1.45, fire: 0.75, birds: 3, night: 1.5, brown: 0.75, pink: 1, white: 1.4, binaural: 0.5 };

  /* ── Mixes: "rain:60,fire:30" ─────────────────────────────────────────────────────────────────────────────── */
  function parse(s) {
    var o = {};
    (s || "").split(",").forEach(function (part) {
      var m = /^([a-z]+):(\d{1,3})$/.exec(part.trim());
      if (m && MAKE[m[1]] && +m[2] > 0) o[m[1]] = Math.min(100, +m[2]);
    });
    return o;
  }
  function format(o) { return Object.keys(o).filter(function (k) { return o[k] > 0; }).map(function (k) { return k + ":" + Math.round(o[k]); }).join(","); }
  function same(a, b) { var x = parse(a), y = parse(b); return format(x).split(",").sort().join() === format(y).split(",").sort().join(); }
  function store() { return window.Alpine && Alpine.store("ambient"); }
  function mixes() { var s = store(); return s ? s.mixes : CFG.mixes; }
  function volume() { var s = store(), v = s ? s.volume : CFG.mixVolume; return v == null ? 40 : +v; }
  function layer(id) { return ((CFG.ambient || {}).layers || []).filter(function (l) { return l.id === id; })[0] || { id: id, icon: "♪", name: id }; }
  function label(mix) {
    var preset = ((CFG.ambient || {}).presets || []).filter(function (p) { return same(p.mix, mix); })[0], ids = Object.keys(parse(mix));
    return { icons: ids.map(function (id) { return layer(id).icon; }).join(""), name: preset ? preset.name : ids.map(function (id) { return layer(id).name; }).join(" · ") };
  }

  /* ── Playing ──────────────────────────────────────────────────────────────────────────────────────────────── */
  var A = { c: null, master: null, live: {}, mix: "", level: 0, why: "", want: "", duck: 1, preview: null, yielded: false, muted: {} };
  try { A.muted = JSON.parse(sessionStorage.getItem("work-ambient-muted:" + ME) || "{}") || {}; } catch (e) { A.muted = {}; }
  function keepMuted() { try { sessionStorage.setItem("work-ambient-muted:" + ME, JSON.stringify(A.muted)); } catch (e) { /* private mode */ } }

  function start(c, id) {
    var out = c.createGain(), plan = null;
    out.gain.value = 0; out.connect(A.master);
    NODES = [];
    try { plan = MAKE[id](c, out) || null; } catch (e) { plan = null; }
    var L = A.live[id] = { out: out, nodes: NODES, plan: plan };
    NODES = null;
    return L;
  }
  function stop(id) {
    var L = A.live[id]; delete A.live[id];
    L.out.gain.setTargetAtTime(0, A.c.currentTime, 0.5);
    setTimeout(function () { L.nodes.forEach(function (n) { try { n.stop(); } catch (e) { /* stopped */ } }); try { L.out.disconnect(); } catch (e) { /* gone */ } }, 4000);
  }
  function plan() {
    var c = A.c; if (!c) return;
    var now = c.currentTime;
    Object.keys(A.live).forEach(function (id) { var L = A.live[id]; if (L.plan) L.plan(now, now + 3); });
  }
  function play(mix) {
    var level = mix ? Math.pow(volume() / 100, 2) * A.duck : 0;
    if (mix === A.mix && level === A.level) { plan(); return; }
    var c = W.audio && W.audio(); if (!c) return;
    if (!A.master || A.c !== c) {
      A.c = c; A.master = c.createGain(); A.master.gain.value = 0;
      var squeeze = c.createDynamicsCompressor(); squeeze.threshold.value = -10; squeeze.ratio.value = 4;          // many at once never clips
      A.master.connect(squeeze); squeeze.connect(c.destination);
    }
    var want = parse(mix), now = c.currentTime;
    Object.keys(A.live).forEach(function (id) { if (!want[id]) stop(id); });
    Object.keys(want).forEach(function (id) {
      var L = A.live[id] || start(c, id);
      L.out.gain.setTargetAtTime(Math.pow(want[id] / 100, 1.6) * (LOUD[id] || 1), now, 0.35);
    });
    A.master.gain.setTargetAtTime(level, now, mix && !A.mix ? 0.9 : 0.4);        // in gently from quiet
    A.mix = mix; A.level = level;
    plan();
  }

  /* ── What to play, here and now ───────────────────────────────────────────────────────────────────────────── */
  var NONE = { mix: "", why: "" };
  function wanted() {
    var P = A.preview, s = store();
    if (P && P.el.isConnected && P.el.getClientRects().length) return { mix: mixes()[P.which] || "", why: "preview" };
    if (P) { A.preview = null; if (s) s.previewing = ""; }
    var M = mixes(), reader = d.documentElement.hasAttribute("data-reader");
    if (reader && M.reading) return { mix: M.reading, why: "reading" };
    var F = W.focus && W.focus.state && W.focus.state.running ? W.focus.state : null,
        timing = !!(window.Clock && (Clock.timers.list.some(function (t) { return t.running; }) || Clock.stopwatch.running));
    if (!F && !timing && (A.muted.focus || A.muted["break"] || A.muted.timer)) { delete A.muted.focus; delete A.muted["break"]; delete A.muted.timer; keepMuted(); }      // paused "for now": until it's all over
    if (!(CFG.tickEverywhere || d.querySelector("[data-focus-page]"))) return NONE;
    if (F) return F.mode === "focus" ? { mix: M.focus, why: "focus" } : { mix: M["break"], why: "break" };
    if (timing && CFG.withTimers) return { mix: M.focus, why: "timer" };
    return NONE;
  }
  var chan = ("BroadcastChannel" in window) ? new BroadcastChannel("work-ambient:" + ME) : null, TAB = Math.random().toString(36).slice(2);
  if (chan) chan.onmessage = function (e) { if (e.data && e.data.take && e.data.take !== TAB && !A.yielded) { A.yielded = true; update(); } };

  function update() {
    var w = wanted(), preview = w.why === "preview",
        mix = w.mix && (preview || (!A.muted[w.why] && !A.yielded)) ? w.mix : "";
    if (preview) A.yielded = false;
    if (mix && !A.mix && chan) chan.postMessage({ take: TAB });          // one tab plays: this one, now
    A.why = w.why; A.want = w.mix;
    if (mix || A.mix) play(mix);
    pill();
  }
  setInterval(update, 700);
  d.addEventListener("visibilitychange", function () { if (!d.hidden && A.yielded) { A.yielded = false; update(); } });
  ["pointerdown", "keydown"].forEach(function (type) {
    d.addEventListener(type, function () { if (A.c && A.c.state === "suspended" && A.mix) A.c.resume().then(update); }, { passive: true });
  });
  window.addEventListener("work:focus-settings", function () { setTimeout(update, 0); });

  /* ── The pill: what's playing, pause / play (and "tap to play" when the browser waits for one) ──────────── */
  var pillEl = null;
  function pill() {
    var show = A.want && A.why !== "preview" && !A.yielded && !d.documentElement.hasAttribute("data-reader");
    if (!show) { if (pillEl) pillEl.hidden = true; return; }
    if (!pillEl) {
      pillEl = d.createElement("button"); pillEl.type = "button"; pillEl.className = "amb-pill";
      pillEl.innerHTML = '<span class="amb-pill-do" aria-hidden="true"></span><span class="amb-pill-ic" aria-hidden="true"></span><span class="amb-pill-name"></span>';
      pillEl.addEventListener("click", function () {
        if (A.c && A.c.state !== "running" && !A.muted[A.why]) { A.c.resume().then(update); return; }
        if (A.muted[A.why]) delete A.muted[A.why]; else A.muted[A.why] = 1;
        keepMuted(); update();
      });
      d.body.appendChild(pillEl);
    }
    var muted = !!A.muted[A.why], waiting = !muted && A.c && A.c.state !== "running", what = label(A.want);
    pillEl.hidden = false;
    pillEl.classList.toggle("is-off", muted || !!waiting);
    pillEl.querySelector(".amb-pill-do").textContent = muted || waiting ? "▶" : "❚❚";
    pillEl.querySelector(".amb-pill-ic").textContent = what.icons;
    pillEl.querySelector(".amb-pill-name").textContent = waiting ? T("soundTap", "Tap to play") : what.name;
    pillEl.setAttribute("aria-label", (muted || waiting ? T("soundPlay", "Play the sound") : T("soundPause", "Pause the sound")) + ": " + what.name);
    pillEl.title = pillEl.getAttribute("aria-label");
  }

  window.Ambient = {
    parse: parse, format: format, same: same, label: label, update: update,
    get playing() { return A.mix; }, get why() { return A.why; },
    get running() { return !!(A.c && A.c.state === "running" && A.mix); },
    preview: function (el, which) { A.preview = { el: el, which: which }; var s = store(); if (s) s.previewing = which; update(); },
    stopPreview: function () { A.preview = null; var s = store(); if (s) s.previewing = ""; update(); },
    duck: function (on) { A.duck = on ? 0.3 : 1; update(); },          // quieter while something is read aloud
    muted: function () { return !!A.muted[A.why]; },
    toggleMute: function () { if (!A.why) return; if (A.muted[A.why]) delete A.muted[A.why]; else A.muted[A.why] = 1; keepMuted(); update(); },
    // how loud a sound is (its RMS over a few seconds, made offline) — to set LOUD so they sit together
    measure: function (id, seconds) {
      seconds = seconds || 12;
      var c = new (window.OfflineAudioContext || window.webkitOfflineAudioContext)(2, 44100 * seconds, 44100), out = c.createGain();
      out.connect(c.destination); NODES = []; var p = MAKE[id](c, out); NODES = null; if (p) p(0, seconds);
      return c.startRendering().then(function (buf) {
        var sum = 0, n = 0;
        for (var ch = 0; ch < buf.numberOfChannels; ch++) { var x = buf.getChannelData(ch); for (var i = 0; i < x.length; i++) { sum += x[i] * x[i]; n++; } }
        return Math.sqrt(sum / n);
      });
    },
  };

  /* ── The mixer (Focus page ⚙, Settings, the Reader): ready-made mixes, every sound with its own slider, one volume ── */
  d.addEventListener("alpine:init", function () {
    Alpine.store("ambient", { mixes: Object.assign({ focus: "", "break": "", reading: "" }, CFG.mixes), volume: CFG.mixVolume == null ? 40 : CFG.mixVolume, previewing: "" });
    Alpine.data("mixer", function (which, fixed) {
      return {
        which: which || "focus", fixed: !!fixed, state: "", timer: null, pending: {},
        layers: (CFG.ambient || {}).layers || [], all: (CFG.ambient || {}).presets || [],
        init: function () { this.root = this.$el; },
        get box() { return Alpine.store("ambient"); },
        get mix() { return this.box.mixes[this.which] || ""; },
        get presets() { var w = this.which; return this.all.filter(function (p) { return p.for.indexOf(w) >= 0; }); },
        get hearing() { return this.box.previewing === this.which; },
        level: function (id) { return parse(this.mix)[id] || 0; },
        isPreset: function (p) { return same(p.mix, this.mix); },
        toggle: function (id) { var p = parse(this.mix); if (p[id]) delete p[id]; else p[id] = 50; this.set(format(p)); },
        slide: function (id, v) { var p = parse(this.mix); p[id] = Math.max(1, Math.min(100, +v)); this.set(format(p)); },
        pick: function (p) { this.set(this.isPreset(p) ? "" : p.mix); },        // tapped again: off
        off: function () { this.set(""); },
        set: function (mix) {
          this.box.mixes[this.which] = mix; CFG.mixes[this.which] = mix;
          this.listen();
          var o = {}; o[this.which + "_mix"] = mix; this.save(o);
        },
        setVolume: function (v) { this.box.volume = +v; CFG.mixVolume = +v; this.listen(); this.save({ mix_volume: +v }); },
        listen: function () { Ambient.preview(this.root, this.which); },
        hear: function () { if (this.hearing) Ambient.stopPreview(); else this.listen(); },
        save: function (fields) {
          var self = this;
          Object.assign(this.pending, fields); this.state = "saving"; clearTimeout(this.timer);
          this.timer = setTimeout(function () {
            var send = self.pending; self.pending = {};
            send._ft_same = "ambient:" + Object.keys(send).sort().join();
            W.api(CFG.urls.sound, send).then(function (res) {
              self.state = res && res.ok ? "saved" : "error";
              if (!(res && res.ok)) W.toast(T("notSaved", "Not saved."), "warn");
            });
          }, 450);
        },
      };
    });
  });
}());
