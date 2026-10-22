/* Interview prep (Productivity): a practice session, a timed mock exam and
   the question form's choice editor. Loaded after work.js on those pages.

   Practice: one question at a time. Multiple choice is checked at once;
   the others show the model answer, you tick the key points you covered
   and rate yourself (1–4), which sets when the question comes back.
   An exam: every question on a countdown, answers saved as you go; when
   the time is up it's handed in by itself. */
(function () {
  "use strict";
  var d = document;
  function md(text) { return window.Work && Work.markdown ? Work.markdown(text || "") : String(text || ""); }
  function show(el, text) {
    if (!el) return;
    el.innerHTML = md(text);
    if (window.Work && Work.mermaidIn) Work.mermaidIn(el);
    if (window.hljs) el.querySelectorAll("pre code:not(.language-mermaid)").forEach(function (c) { hljs.highlightElement(c); });
  }
  function data(id) { try { return JSON.parse(d.getElementById(id).textContent); } catch (e) { return {}; } }
  var T = data("prep-text");
  function t(key, fallback) { return T[key] || fallback; }
  function toast(msg, tone) { if (window.Work && Work.toast) Work.toast(msg, tone); }
  function typing(el) {       // a text box has the keys; a checkbox or radio doesn't
    return el && (el.isContentEditable || /^(TEXTAREA|SELECT)$/.test(el.tagName) || el.tagName === "INPUT" && !/^(checkbox|radio|button)$/.test(el.type));
  }
  function tabKey(e) {        // Tab in a code box puts in four spaces
    if (e.key !== "Tab" || e.shiftKey) return;
    var ta = e.target; e.preventDefault();
    var s = ta.selectionStart; ta.setRangeText("    ", s, ta.selectionEnd, "end");
    ta.dispatchEvent(new Event("input", { bubbles: true }));
  }
  function clock(secs) {
    secs = Math.max(0, Math.round(secs));
    var h = Math.floor(secs / 3600), m = Math.floor(secs % 3600 / 60), s = secs % 60;
    return (h ? h + ":" + (m < 10 ? "0" : "") : "") + m + ":" + (s < 10 ? "0" : "") + s;
  }

  document.addEventListener("alpine:init", function () {
    /* ── A practice session (also one question on its own page) ─────────── */
    Alpine.data("prepSession", function (source) {
      var S = data(source || "prep-session"), list = S.questions || [];
      return {
        list: list, i: 0, q: null, stage: list.length ? "ask" : "empty", chosen: [], text: "", ticked: [], right: null, busy: false,
        started: 0, total: list.length, back: S.back || "", single: !!S.single,
        tally: { n: 0, right: 0, partly: 0, wrong: 0, seconds: 0 }, missed: [], byTopic: {},
        init: function () { if (list.length) this.load(0); },
        load: function (i) {
          this.i = i; this.q = this.list[i]; this.stage = "ask"; this.chosen = []; this.ticked = []; this.right = null;
          this.text = this.q.kind === "code" ? (this.q.starter || "") : ""; this.started = Date.now();
          var self = this;
          this.$nextTick(function () {
            show(self.$refs.prompt, self.q.prompt);
            if (self.$refs.input) self.$refs.input.focus({ preventScroll: true });
          });
        },
        isChoice: function () { return this.q && this.q.kind === "choice"; },
        toggle: function (n) {
          if (this.stage !== "ask") return;
          var at = this.chosen.indexOf(n);
          if (this.q.multi) { if (at >= 0) this.chosen.splice(at, 1); else this.chosen.push(n); }
          else this.chosen = [n];
        },
        optionState: function (n) {
          if (this.stage === "ask") return this.chosen.indexOf(n) >= 0 ? "picked" : "";
          var good = this.q.correct.indexOf(n) >= 0, picked = this.chosen.indexOf(n) >= 0;
          return good ? (picked ? "right" : "missed") : (picked ? "wrong" : "");
        },
        seconds: function () { return Math.round((Date.now() - this.started) / 1000); },
        check: function () {          // multiple choice: marked here, saved in the background
          if (!this.chosen.length) { toast(t("pick", "Pick an answer first."), "warn"); return; }
          var q = this.q, right = this.chosen.length === q.correct.length && this.chosen.every(function (c) { return q.correct.indexOf(c) >= 0; });
          this.right = right; this.stage = "answered";
          this.count(right ? 1 : 0, q);
          Work.api(Work.cfg.urls.prepBase + q.id + "/answer/", { choice: this.chosen.join(","), seconds: this.seconds() });
          this.reveal();
        },
        reveal: function () {
          if (this.stage === "ask") this.stage = "answered";
          var self = this;
          this.$nextTick(function () { show(self.$refs.answer, self.q.answer); show(self.$refs.why, self.q.explanation); });
        },
        coveredText: function () {
          return t("covered", "You covered %(n)s of %(total)s key points").replace("%(n)s", this.ticked.length).replace("%(total)s", this.q.points.length);
        },
        covered: function () { return this.q && this.q.points.length ? this.ticked.length / this.q.points.length : null; },
        suggested: function () {
          var c = this.covered();
          if (c === null) return 0;
          return c >= 0.999 ? 3 : c >= 0.6 ? 2 : 1;
        },
        rate: function (r) {          // written answers: you say how it went
          if (this.stage !== "answered" || this.isChoice() || this.busy) return;
          var c = this.covered(), score = c === null ? { 1: 0, 2: 0.5, 3: 1, 4: 1 }[r] : c;
          if (r === 1) score = Math.min(score, 0.4);
          this.count(score, this.q);
          Work.api(Work.cfg.urls.prepBase + this.q.id + "/answer/", { rating: r, score: score.toFixed(2), seconds: this.seconds(), text: this.text.slice(0, 4000) });
          this.next();
        },
        count: function (score, q) {
          this.tally.n++; this.tally.seconds += this.seconds();
          if (score >= 0.999) this.tally.right++; else if (score > 0) this.tally.partly++; else this.tally.wrong++;
          if (score < 0.999 && this.missed.indexOf(q.id) < 0) this.missed.push(q.id);
          var b = this.byTopic[q.topic] || (this.byTopic[q.topic] = { n: 0, got: 0, color: q.color });
          b.n++; b.got += score;
        },
        next: function () {
          if (this.single) { this.stage = "rated"; return; }
          if (this.i + 1 < this.list.length) this.load(this.i + 1); else this.stage = "done";
        },
        topics: function () {
          var self = this;
          return Object.keys(this.byTopic).map(function (k) { var b = self.byTopic[k]; return { name: k, n: b.n, pct: Math.round(100 * b.got / b.n), color: b.color }; });
        },
        pct: function () { return this.tally.n ? Math.round(100 * (this.tally.right + 0.5 * this.tally.partly) / this.tally.n) : 0; },
        retryUrl: function () { return S.practice + "?ids=" + this.missed.join(","); },
        avg: function () { return this.tally.n ? clock(this.tally.seconds / this.tally.n) : "0:00"; },
        hint: function (r) { return (this.q && this.q.hints && this.q.hints[r]) || ""; },
        tab: tabKey,
        key: function (e) {
          if (this.stage === "empty" || this.stage === "done" || this.stage === "rated") return;
          var inBox = typing(e.target);
          if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); this.go(); return; }
          if (inBox) return;
          if (e.key === "Enter" || e.key === " ") { e.preventDefault(); this.go(); return; }
          var n = parseInt(e.key, 10);
          if (!n) return;
          if (this.stage === "ask" && this.isChoice() && n <= this.q.options.length) { e.preventDefault(); this.toggle(n - 1); }
          else if (this.stage === "answered" && !this.isChoice() && n <= 4) { e.preventDefault(); this.rate(n); }
        },
        go: function () {             // Enter: check, show the answer, or carry on
          if (this.stage === "ask") { if (this.isChoice()) this.check(); else this.reveal(); }
          else if (this.stage === "answered") { if (this.isChoice()) this.next(); else this.rate(this.suggested() || 3); }
        },
      };
    });

    /* ── A timed mock exam ────────────────────────────────────────────── */
    Alpine.data("prepExam", function () {
      var S = data("prep-exam"), store = "work-exam:" + S.id;
      var saved = {}; try { saved = JSON.parse(localStorage.getItem(store) || "{}"); } catch (e) { saved = {}; }
      var answers = {}, secs = {};      // time on each question is kept apart, so the clock doesn't count as a change
      (S.questions || []).forEach(function (q) {
        var a = (S.answers || {})[q.id] || saved[q.id] || {};
        answers[q.id] = { choice: a.choice || [], text: a.text != null ? a.text : (q.kind === "code" ? q.starter || "" : ""), flag: !!a.flag };
        secs[q.id] = a.seconds || 0;
      });
      return {
        list: S.questions || [], i: 0, answers: answers, left: 0, ends: new Date(S.ends).getTime(), dirty: false, state: "", handedIn: false,
        lastTick: Date.now(), timer: null, saver: null,
        get q() { return this.list[this.i]; },
        get a() { return this.answers[this.q.id]; },
        init: function () {
          var self = this;
          this.tick();
          this.timer = setInterval(function () { self.tick(); }, 1000);
          this.load(0);
          this.$watch("answers", function () { self.changed(); });
          window.addEventListener("beforeunload", function () { if (self.dirty) self.save(true); });
        },
        load: function (i) {
          this.i = Math.max(0, Math.min(i, this.list.length - 1));
          var self = this;
          this.$nextTick(function () { show(self.$refs.prompt, self.q.prompt); });
        },
        tick: function () {
          var now = Date.now();
          if (this.q) secs[this.q.id] += Math.round((now - this.lastTick) / 1000);
          this.lastTick = now;
          this.left = Math.max(0, Math.round((this.ends - now) / 1000));
          if (!this.left && !this.handedIn) { toast(t("timeUp", "Time's up — your answers have been handed in."), "warn"); this.handIn(true); }
        },
        clock: function () { return clock(this.left); },
        low: function () { return this.left <= 300; },
        changed: function () {
          this.dirty = true; this.state = "";
          try { localStorage.setItem(store, JSON.stringify(this.payload())); } catch (e) { /* private mode */ }
          var self = this;
          clearTimeout(this.saver);
          this.saver = setTimeout(function () { self.save(); }, 1500);
        },
        save: function (quiet) {
          var self = this, body = new FormData();
          body.append("answers", JSON.stringify(this.payload()));
          var req = fetch(S.save, { method: "POST", body: body, credentials: "same-origin", keepalive: !!quiet,
                                    headers: { "X-CSRFToken": (d.cookie.match(/csrftoken=([^;]+)/) || [])[1] || "", "X-Requested-With": "fetch" } });
          if (quiet) return;
          req.then(function (r) {
            if (r.status === 409) { location.reload(); return; }
            self.dirty = !r.ok; self.state = r.ok ? "saved" : "offline";
          }).catch(function () { self.state = "offline"; });
        },
        payload: function () {        // the answers with the time spent on each
          var out = {}, self = this;
          Object.keys(this.answers).forEach(function (id) { out[id] = Object.assign({}, self.answers[id], { seconds: secs[id] || 0 }); });
          return out;
        },
        toggle: function (n) {
          var c = this.a.choice, at = c.indexOf(n);
          if (this.q.multi) { if (at >= 0) c.splice(at, 1); else c.push(n); }
          else this.a.choice = at >= 0 ? [] : [n];
        },
        picked: function (n) { return this.a.choice.indexOf(n) >= 0; },
        done: function (q) { var a = this.answers[q.id]; return a.choice.length > 0 || (a.text || "").trim() !== "" && a.text !== (q.starter || ""); },
        unanswered: function () { var self = this; return this.list.filter(function (q) { return !self.done(q); }).length; },
        flagged: function () { var self = this; return this.list.filter(function (q) { return self.answers[q.id].flag; }).length; },
        handIn: function (forced) {
          if (this.handedIn) return;
          var n = this.unanswered();
          if (!forced && !confirm(n ? t("unanswered", "%(n)s questions have no answer yet. Hand in anyway?").replace("%(n)s", n) : t("submit", "Hand in the exam now?"))) return;
          this.handedIn = true; clearInterval(this.timer); clearTimeout(this.saver); this.dirty = false;
          try { localStorage.removeItem(store); } catch (e) { /* fine */ }
          this.$refs.answers.value = JSON.stringify(this.payload());
          this.$refs.form.submit();
        },
        tab: tabKey,
        key: function (e) {
          if (typing(e.target)) return;
          if (e.key === "ArrowRight" || e.key === "n") { e.preventDefault(); this.load(this.i + 1); }
          else if (e.key === "ArrowLeft" || e.key === "p") { e.preventDefault(); this.load(this.i - 1); }
          else if (e.key === "f") { e.preventDefault(); this.a.flag = !this.a.flag; }
          else if (this.q.kind === "choice") {
            var n = parseInt(e.key, 10);
            if (n && n <= this.q.options.length) { e.preventDefault(); this.toggle(n - 1); }
          }
        },
      };
    });

    /* ── The question form: its choices (multiple choice) ───────────────── */
    Alpine.data("prepChoices", function () {
      return {
        items: [],
        init: function () {
          var raw = []; try { raw = JSON.parse(this.$refs.store.value || "[]"); } catch (e) { raw = []; }
          this.items = raw.length ? raw.map(function (o) { return { text: o.text || "", correct: !!o.correct }; })
                                  : [{ text: "", correct: true }, { text: "", correct: false }, { text: "", correct: false }, { text: "", correct: false }];
          var self = this;
          this.$watch("items", function () { self.sync(); });
          this.sync();
        },
        sync: function () { this.$refs.store.value = JSON.stringify(this.items.filter(function (o) { return o.text.trim(); })); },
        add: function () {
          this.items.push({ text: "", correct: false });
          var self = this;
          this.$nextTick(function () { var all = self.$el.querySelectorAll("[data-choice-text]"); if (all.length) all[all.length - 1].focus(); });
        },
        drop: function (n) { this.items.splice(n, 1); },
      };
    });

    /* ── A question's own notes: saved as you type ─────────────────────── */
    Alpine.data("prepNotes", function (id) {
      var timer = null;
      return {
        state: "",
        changed: function (value) {
          var self = this;
          this.state = "…";
          clearTimeout(timer);
          timer = setTimeout(function () {
            Work.api(Work.cfg.urls.prepBase + id + "/", { action: "notes", notes: value }).then(function (r) { self.state = r && r.ok ? t("noteSaved", "Note saved") : ""; });
          }, 800);
        },
      };
    });
  });

  /* The star on a question (bank and question page). */
  d.addEventListener("click", function (e) {
    var b = e.target.closest("[data-prep-star]"); if (!b) return;
    e.preventDefault();
    Work.api(Work.cfg.urls.prepBase + b.getAttribute("data-prep-star") + "/", { action: "star" }).then(function (r) {
      if (!r || !r.ok) return;
      var on = r.queued ? !b.classList.contains("is-on") : r.starred;       // offline: it's sent later
      b.classList.toggle("is-on", on); b.setAttribute("aria-pressed", on ? "true" : "false");
      toast(on ? t("starred", "Starred") : t("unstarred", "Star removed"));
    });
  });
})();
