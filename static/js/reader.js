/* The Reader (work/read.html): notes or exam notes read as a book, one chapter at a time — made for people who'd
   rather not read, after Kindle, Apple Books, Medium, Blinkist and Duolingo:

   - small, finishable steps: a chapter, its minutes ("≈ 4 min"), the minutes left, a bar that fills;
   - no searching for your place: where you stopped is kept to the line (on the server, so on every device);
   - easy on the eyes: size, font (book, clean, easy), line spacing, width, Paper / Sepia / Dark / Night (this device);
   - help to stay on the line: Focus line (only the part you're on is bright), Bold word starts;
   - listening instead: the chapter read aloud part by part, the part marked, on into the next chapter;
   - a reward: a chapter's end is a small celebration, a daily goal (10 min) and its streak;
   - remembering: one line of your own at the end of each chapter, and (exam notes) a test of just that chapter.

   Time read is counted only while the page is in sight and you're reading (scrolling, keys, a tap in the last
   minute — or listening), and sent every 30 s (and on leaving). Keys: ← → chapters, T contents, A text, L listen,
   F focus line (↑ ↓ move it), + − size, Esc closes. */
(function () {
  "use strict";
  var d = document, W = window.Work;
  function json(id) { try { return JSON.parse(d.getElementById(id).textContent); } catch (e) { return {}; } }
  var TX = json("read-text");
  function T(k) { return TX[k] || k; }
  var PREFS = "ft-reader", DEFAULT = { size: 19, font: "serif", lh: 1.75, width: 68, theme: "paper", focus: false, bionic: false, rate: 1 };
  function loadPrefs() { var p = W.recall(PREFS, {}) || {}; return Object.assign({}, DEFAULT, p); }
  function typing(e) { var el = e.target; return !!(el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName))); }
  function csrf() { var m = d.cookie.match(/csrftoken=([^;]+)/); return m ? decodeURIComponent(m[1]) : ((d.querySelector("[name=csrfmiddlewaretoken]") || {}).value || ""); }
  var BLOCKS = "p, li, h1, h2, h3, h4, h5, h6, blockquote, pre, table, .wn-code";

  document.addEventListener("alpine:init", function () {
    Alpine.data("reader", function (data) {
      var start = Math.max(0, data.chapters.findIndex(function (c) { return c.key === data.start; }));
      return {
        data: data, chapters: data.chapters, progress: data.progress || {}, stats: data.stats || {}, prefs: loadPrefs(),
        idx: start, pos: 0, resumeAt: 0, toc: false, aa: false, snd: false, goalOpen: false, barHidden: false, justDone: false,
        takeaway: "", kept: false, speaking: false, listenPaused: false, at: -1, voices: [],
        pending: 0, lastActive: Date.now(), T: T,

        init: function () {
          var self = this;
          d.documentElement.setAttribute("data-reader", "");          // the app's menus step aside (as focus writing)
          this.open(this.idx, true);
          this.watchScroll();
          this.countTime();
          this.keys();
          this.sortable();
          this.$watch("speaking", function (on) { if (window.Ambient) Ambient.duck(on); });     // the background sound steps back while it's read aloud
          if ("speechSynthesis" in window) {
            var load = function () { self.voices = speechSynthesis.getVoices(); };
            load(); speechSynthesis.onvoiceschanged = load;
          }
        },

        /* ── the chapter on the page ── */
        cur: function () { return this.chapters[this.idx] || { key: "", title: "", md: "", minutes: 1 }; },
        next: function () { return this.chapters[this.idx + 1]; },
        prog: function (key) { return this.progress[key] || {}; },
        doneCount: function () { var self = this; return this.chapters.filter(function (c) { return self.prog(c.key).done; }).length; },
        allRead: function () { return this.doneCount() === this.chapters.length; },
        chapterOf: function () { return T("chapterOf").replace("%(n)s", this.idx + 1).replace("%(total)s", this.chapters.length); },
        minLeftText: function () { return T("minLeft").replace("%(n)s", Math.max(1, Math.ceil(this.cur().minutes * (1 - this.pos)))); },
        bookMinutesLeft: function () {
          var self = this;
          return this.chapters.reduce(function (s, c) { var p = self.prog(c.key); return s + (p.done ? 0 : Math.ceil(c.minutes * (1 - (p.position || 0)))); }, 0);
        },
        go: function (i) {
          if (i < 0 || i >= this.chapters.length || i === this.idx) return;
          this.flush(); this.stopSpeaking(); var wasListening = this.listenPaused === "next";
          this.open(i, false);
          if (wasListening) this.listen();
        },
        open: function (i, first) {
          var self = this, c = this.chapters[i], el = this.$refs.text;
          this.idx = i; this.justDone = false; this.kept = false; this.openedAt = Date.now(); clearTimeout(this.doneTimer);
          this.takeaway = this.prog(c.key).takeaway || "";
          el.innerHTML = W.markdown(c.md || "");
          if (W.enrich) try { W.enrich(el, {}); } catch (e) { /* diagrams etc. */ }
          if (window.hljs) el.querySelectorAll("pre code:not(.language-mermaid):not([data-highlighted])").forEach(function (x) { try { hljs.highlightElement(x); } catch (e) { /* ok */ } });
          if (this.prefs.bionic) this.bionic(true);
          var u = new URL(location.href); u.searchParams.set("ch", c.key); history.replaceState(null, "", u);
          var p = this.prog(c.key);
          this.resumeAt = p.done ? 0 : (p.position || 0);
          window.scrollTo({ top: 0, behavior: "instant" });
          this.$nextTick(function () {
            if (first && self.resumeAt > 0.03) self.jump(self.resumeAt);      // opened again: straight back to the line
            self.measure(); self.markFocus();
          });
        },
        jump: function (frac) {
          var r = this.$refs.text.getBoundingClientRect(), top = window.scrollY + r.top;
          window.scrollTo({ top: Math.max(0, top + frac * r.height - innerHeight * 0.35), behavior: "smooth" });
          this.resumeAt = 0;
        },

        /* ── how far: the bar, where you stopped, done at the end ── */
        measure: function () {
          var r = this.$refs.text.getBoundingClientRect(), h = Math.max(1, r.height);
          var seen = innerHeight * 0.6 - r.top;
          this.pos = Math.max(0, Math.min(1, seen / h));
        },
        watchScroll: function () {
          var self = this, lastY = window.scrollY, timer = 0;
          window.addEventListener("scroll", function () {
            var y = window.scrollY;
            self.barHidden = y > lastY + 4 && y > 120 && !self.toc && !self.aa && !self.snd;       // reading down: the bar steps aside; up: it's back
            if (y < lastY - 4) self.barHidden = false;
            lastY = y;
            self.measure(); self.markFocus(); self.active();
            clearTimeout(timer); timer = setTimeout(function () { self.save({ position: self.pos }); }, 1200);
          }, { passive: true });
          // the end in sight = read — but not before a quick skim's worth of time (600 words a minute), so a chapter
          // opened and jumped through isn't ticked off
          var check = function () {
            var r = self.$refs.end.getBoundingClientRect();
            if (r.top > innerHeight - 40 || r.bottom < 0) return;
            var wait = Math.min(20000, Math.max(3000, self.cur().words * 100)) - (Date.now() - self.openedAt);
            if (wait > 0) { clearTimeout(self.doneTimer); self.doneTimer = setTimeout(check, wait); return; }
            self.finished();
          };
          new IntersectionObserver(function (es) { es.forEach(function (e) { if (e.isIntersecting) check(); }); }, { threshold: 0.35 }).observe(this.$refs.end);
        },
        finished: function () {
          var c = this.cur(), p = this.prog(c.key);
          if (p.done) return;
          this.progress[c.key] = Object.assign({}, p, { done: true, position: 1 });
          this.justDone = true;
          if (W.cfg.sound) W.play("marimba");          // a small reward (sounds on in the timer's settings)
          this.save({ done: "1", position: 1 });
          if (this.allRead()) W.toast("🎉 " + T("allDone"), "good");
        },
        keepTakeaway: function () {
          var c = this.cur(), was = this.prog(c.key).takeaway || "";
          if (this.takeaway.trim() === was.trim()) return;
          this.progress[c.key] = Object.assign({}, this.prog(c.key), { takeaway: this.takeaway.trim() });
          this.save({ takeaway: this.takeaway.trim() }); this.kept = true;
        },

        /* ── time read: only while reading ── */
        active: function () { this.lastActive = Date.now(); },
        countTime: function () {
          var self = this, wasMet = !!this.stats.reached;
          ["keydown", "pointerdown", "wheel", "touchstart"].forEach(function (t) { d.addEventListener(t, function () { self.active(); }, { passive: true }); });
          setInterval(function () {
            if (!d.hidden && (self.speaking || Date.now() - self.lastActive < 60000)) self.pending++;
            if (!wasMet && self.stats.goal && self.todayMin() >= self.stats.goal) { wasMet = true; self.stats.reached = true; W.toast("🎯 " + T("goalMet"), "good"); }
          }, 1000);
          setInterval(function () { if (self.pending >= 30) self.flush(); }, 5000);
          d.addEventListener("visibilitychange", function () { if (d.hidden) self.flush(true); });
          window.addEventListener("pagehide", function () { self.flush(true); });
        },
        todayMin: function () { return (this.stats.today || 0) + this.pending / 60; },
        goalPct: function () { return this.stats.goal ? Math.min(100, Math.round(100 * this.todayMin() / this.stats.goal)) : (this.todayMin() ? 100 : 0); },
        todayText: function () {
          var n = Math.floor(this.todayMin());
          return this.stats.goal ? T("today").replace("%(n)s", n).replace("%(goal)s", this.stats.goal) : T("todayNoGoal").replace("%(n)s", n);
        },
        setGoal: function (n) {
          var self = this, goal = Math.max(0, Math.min(240, n));
          this.stats.goal = goal;
          this.post({ action: "goal", goal: goal }).then(function (r) { if (r && r.stats) self.stats = Object.assign(r.stats, { today: self.stats.today }); });
        },

        /* ── saving ── */
        fields: function (extra) {
          var c = this.cur(), f = { kind: this.data.kind, book: this.data.book || "", chapter: c.key };
          return Object.assign(f, extra || {});
        },
        post: function (fields, leaving) {
          var body = new FormData();
          body.append("csrfmiddlewaretoken", csrf());
          Object.keys(fields).forEach(function (k) { body.append(k, fields[k]); });
          if (leaving && navigator.sendBeacon) { navigator.sendBeacon(this.data.api, body); return Promise.resolve(null); }
          return fetch(this.data.api, { method: "POST", body: body, credentials: "same-origin", headers: { "X-CSRFToken": csrf() } })
            .then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; });
        },
        save: function (extra) {
          var self = this, c = this.cur(), add = Math.floor(this.pending);
          if (extra && extra.position != null) this.progress[c.key] = Object.assign({}, this.prog(c.key), { position: Math.max(this.prog(c.key).position || 0, extra.position) });
          this.pending -= add;
          return this.post(this.fields(Object.assign({ seconds: add }, extra || {}))).then(function (r) {
            if (r && r.stats) { self.stats = r.stats; } else self.pending += add;       // not sent: counted with the next one
          });
        },
        flush: function (leaving) {
          var add = Math.floor(this.pending); if (!add && !leaving) return;
          this.pending -= add;
          var f = this.fields({ seconds: add, position: this.pos });
          if (leaving) { this.post(f, true); this.stats.today = (this.stats.today || 0) + add / 60; return; }
          var self = this;
          this.post(f).then(function (r) { if (r && r.stats) self.stats = r.stats; else self.pending += add; });
        },

        /* ── text and colours ── */
        vars: function () {
          var p = this.prefs;
          return "--rd-size:" + p.size + "px;--rd-lh:" + p.lh + ";--rd-width:" + p.width + "ch";
        },
        set: function (k, v) {
          this.prefs[k] = v; W.store(PREFS, this.prefs);
          if (k === "theme") d.documentElement.setAttribute("data-rtheme", v);          // (the page around it too)
          if (k === "bionic") this.bionic(v);
          if (k === "focus") { this.markFocus(); if (v) W.toast(T("focusOn")); }
          var self = this; this.$nextTick(function () { self.measure(); });
        },
        size: function (by) { this.set("size", Math.max(14, Math.min(32, this.prefs.size + by))); },

        /* Bold word starts: the first half of each word in bold — the eye jumps from one to the next */
        bionic: function (on) {
          var el = this.$refs.text;
          if (!on) { el.querySelectorAll("b.rd-bw").forEach(function (b) { b.replaceWith(d.createTextNode(b.textContent)); }); el.normalize(); return; }
          if (el.querySelector("b.rd-bw")) return;
          var w = d.createTreeWalker(el, NodeFilter.SHOW_TEXT, { acceptNode: function (n) {
            return n.parentElement && n.parentElement.closest("pre, code, .katex, a, mark, b.rd-bw, svg") ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT; } }), list = [], n;
          while ((n = w.nextNode())) if (n.data.trim()) list.push(n);
          list.forEach(function (node) {
            var frag = d.createDocumentFragment();
            node.data.split(/(\s+)/).forEach(function (part) {
              if (!part.trim() || part.length < 2) { frag.appendChild(d.createTextNode(part)); return; }
              var cut = Math.ceil(part.length / 2), b = d.createElement("b"); b.className = "rd-bw"; b.textContent = part.slice(0, cut);
              frag.appendChild(b); frag.appendChild(d.createTextNode(part.slice(cut)));
            });
            node.replaceWith(frag);
          });
        },
        /* Focus line: only the part nearest the middle of the screen is bright */
        blocks: function () { return Array.prototype.filter.call(this.$refs.text.querySelectorAll(BLOCKS), function (b) { return !b.parentElement.closest("li, blockquote, table, .wn-code"); }); },
        markFocus: function () {
          var list = this.blocks(), mid = innerHeight * 0.42, best = null, gap = 1e9;
          list.forEach(function (b) { b.classList.remove("rd-here", "rd-near"); });
          if (!this.prefs.focus && !this.speaking) return;
          if (this.speaking && this.at >= 0) { var s = this.speakList[this.at]; if (s) s.classList.add("rd-here"); return; }
          list.forEach(function (b) { var r = b.getBoundingClientRect(), g = Math.abs((r.top + r.bottom) / 2 - mid); if (g < gap) { gap = g; best = b; } });
          if (best) {
            best.classList.add("rd-here");
            // a heading (an exam question): what's under it, up to the next heading, stays bright with it
            var hd = /^H[1-6]$/.test(best.tagName) ? best : null;
            if (!hd) for (var p = best.previousElementSibling; p; p = p.previousElementSibling) { if (/^H[1-6]$/.test(p.tagName)) { if (+p.tagName[1] >= 3) hd = p; break; } }
            if (hd) for (var n = hd; n; n = n.nextElementSibling) { if (n !== hd && /^H[1-6]$/.test(n.tagName)) break; n.classList.add("rd-near"); }
          }
        },
        stepFocus: function (dir) {
          var list = this.blocks(), at = list.findIndex(function (b) { return b.classList.contains("rd-here"); }), to = list[Math.max(0, Math.min(list.length - 1, at + dir))];
          if (to) { var r = to.getBoundingClientRect(); window.scrollBy({ top: (r.top + r.bottom) / 2 - innerHeight * 0.42, behavior: "smooth" }); }
        },

        /* ── listening (the browser reads aloud, part by part; Bangla with a Bangla voice where there is one) ── */
        listen: function () {
          if (!("speechSynthesis" in window)) { W.toast(T("noVoice"), "warn"); return; }
          if (this.speaking) { this.stopSpeaking(); this.listenPaused = true; return; }
          this.speakList = this.blocks().filter(function (b) { return b.textContent.trim() && b.tagName !== "PRE" && !b.classList.contains("wn-code"); });
          var from = this.at >= 0 && this.listenPaused ? this.at : Math.max(0, this.speakList.findIndex(function (b) { return b.getBoundingClientRect().bottom > innerHeight * 0.2; }));
          this.say(from);
        },
        say: function (i) {
          var self = this;
          if (!this.speakList) return;
          speechSynthesis.cancel();
          if (i >= this.speakList.length) {                         // the end of the chapter: on into the next
            this.speaking = false; this.at = -1;
            if (this.idx < this.chapters.length - 1) { this.listenPaused = "next"; this.finished(); this.go(this.idx + 1); } else { this.listenPaused = false; this.finished(); }
            return;
          }
          i = Math.max(0, i); this.at = i; this.speaking = true; this.listenPaused = false;
          var block = this.speakList[i], text = block.textContent.replace(/\s+/g, " ").trim();
          var bn = /[ঀ-৿]/.test(text), voice = this.voices.filter(function (v) { return bn ? /^bn/i.test(v.lang) : /^en/i.test(v.lang); })[0];
          var parts = text.match(/[^.!?।]+[.!?।]*\s*/g) || [text], k = 0;           // a sentence at a time (long ones get cut off otherwise)
          this.markFocus();
          var r = block.getBoundingClientRect();
          if (r.top < 80 || r.bottom > innerHeight - 80) window.scrollBy({ top: r.top - innerHeight * 0.35, behavior: "smooth" });
          var speakNext = function () {
            if (!self.speaking || self.at !== i) return;
            if (k >= parts.length) { self.say(i + 1); return; }
            var u = new SpeechSynthesisUtterance(parts[k++]);
            u.rate = self.prefs.rate; if (voice) { u.voice = voice; u.lang = voice.lang; } else if (bn) u.lang = "bn-BD";
            u.onend = speakNext; u.onerror = function () { if (self.speaking && self.at === i) speakNext(); };
            speechSynthesis.speak(u);
          };
          speakNext();
          this.active();
        },
        stopSpeaking: function () {
          if ("speechSynthesis" in window) speechSynthesis.cancel();
          this.speaking = false;
          this.blocks().forEach(function (b) { b.classList.remove("rd-here"); });
          this.markFocus();
        },

        /* ── contents in your own order (a note book) ── */
        sortable: function () {
          var self = this;
          if (!this.data.canOrder || !window.Sortable) return;
          Sortable.create(this.$refs.tocList, {
            handle: ".rd-toc-grip", animation: 150,
            onEnd: function (e) {
              if (e.oldIndex === e.newIndex) return;
              var key = self.cur().key, moved = self.chapters.splice(e.oldIndex, 1)[0];
              self.chapters.splice(e.newIndex, 0, moved);
              self.idx = self.chapters.findIndex(function (c) { return c.key === key; });
              self.post({ action: "order", ids: self.chapters.map(function (c) { return c.key; }).join(",") }).then(function (r) { if (r && r.ok) W.toast(T("orderSaved")); });
            },
          });
        },

        /* ── background sound (static/js/ambient.js): M pauses it for now, and plays it again ── */
        hushed: false,
        mute: function () {
          if (Ambient.why !== "reading") { this.snd = true; return; }        // nothing chosen to read with yet: the mixer
          Ambient.toggleMute(); this.hushed = Ambient.muted();
        },

        /* ── keys ── */
        keys: function () {
          var self = this;
          d.addEventListener("keydown", function (e) {
            if (typing(e) || e.ctrlKey || e.metaKey || e.altKey || d.querySelector("dialog[open]")) return;
            var k = e.key;
            if (k === "Escape") { if (self.toc || self.aa || self.snd || self.goalOpen) { self.toc = self.aa = self.snd = self.goalOpen = false; e.preventDefault(); } else if (self.speaking) self.stopSpeaking(); return; }
            if (k === "ArrowRight" || k === "n") { e.preventDefault(); self.go(self.idx + 1); }
            else if (k === "ArrowLeft" || k === "p") { e.preventDefault(); self.go(self.idx - 1); }
            else if (k === "t" || k === "T") { e.preventDefault(); self.toc = !self.toc; }
            else if (k === "a" || k === "A") { e.preventDefault(); self.aa = !self.aa; }
            else if (k === "l" || k === "L") { e.preventDefault(); self.listen(); }
            else if (k === "s" || k === "S") { e.preventDefault(); self.snd = !self.snd; }
            else if ((k === "m" || k === "M") && window.Ambient) { e.preventDefault(); self.mute(); }
            else if (k === "f" || k === "F") { e.preventDefault(); self.set("focus", !self.prefs.focus); }
            else if (k === "+" || k === "=") { e.preventDefault(); self.size(1); }
            else if (k === "-") { e.preventDefault(); self.size(-1); }
            else if (self.prefs.focus && (k === "ArrowDown" || k === "ArrowUp")) { e.preventDefault(); self.stepFocus(k === "ArrowDown" ? 1 : -1); }
          });
        },
      };
    });
  });
}());
