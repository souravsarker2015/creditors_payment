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
  function tabKey(e) {        // in a code box: Tab puts in four spaces, Enter keeps the line's indent (one more after ":" or "{")
    var ta = e.target, s = ta.selectionStart;
    if (e.key === "Tab" && !e.shiftKey) {
      e.preventDefault(); ta.setRangeText("    ", s, ta.selectionEnd, "end");
    } else if (e.key === "Enter" && !e.ctrlKey && !e.metaKey && !e.shiftKey && !e.altKey) {
      var line = ta.value.slice(ta.value.lastIndexOf("\n", s - 1) + 1, s), indent = (/^[ \t]*/.exec(line) || [""])[0];
      if (/[:{[(]\s*$/.test(line)) indent += "    ";
      e.preventDefault(); ta.setRangeText("\n" + indent, s, ta.selectionEnd, "end");
    } else return;
    ta.dispatchEvent(new Event("input", { bubbles: true }));
  }
  function clock(secs) {
    secs = Math.max(0, Math.round(secs));
    var h = Math.floor(secs / 3600), m = Math.floor(secs % 3600 / 60), s = secs % 60;
    return (h ? h + ":" + (m < 10 ? "0" : "") : "") + m + ":" + (s < 10 ? "0" : "") + s;
  }

  /* Running a coding answer (practice and exams): the code with its checks, in runner.js's sandbox. */
  var runMixin = {
    ran: { busy: false, loading: false, res: null },
    warm: function () { if (this.canRun()) Work.warmRunner(this.q.language); },
    canRun: function () { return !!(this.q && this.q.kind === "code" && window.Work && Work.runLanguage && Work.runLanguage(this.q.language)); },
    isSQL: function () { return this.canRun() && Work.runLanguage(this.q.language) === "sql"; },
    run: function () {
      if (!this.canRun() || this.ran.busy) return;
      var self = this, q = this.q, lang = Work.runLanguage(q.language);
      this.ran = { busy: true, loading: false, res: null };
      Work.runCode(lang, this.codeNow(), {
        tests: q.tests, expected: lang === "sql" && q.answer ? Work.firstCode(q.answer) : "",
        onLoading: function () { self.ran.loading = true; },
      }).then(function (res) {
        if (self.q !== q) return;
        self.ran = { busy: false, loading: false, res: res };
        if (res.verdict === "pass" || res.verdict === "match") self.ranOk = true;
      });
    },
    runText: function () {
      var r = this.ran;
      if (r.busy) return r.loading ? t("runLoading", "Getting ready — the first run takes a few seconds…") : t("running", "Running…");
      if (!r.res) return "";
      var res = r.res;
      if (res.timeout) return t("runTimeout", "Stopped: it ran too long. Is there an endless loop?");
      if (res.verdict === "pass") return t("runPass", "All checks passed");
      if (res.verdict === "match") return t("runMatch", "Same result as the model answer");
      if (res.verdict === "differ") return t("runDiffer", "A different result from the model answer's");
      if (res.verdict === "fail") return t("runFail", "A check failed");
      if (!res.ok) return t("runError", "There's an error");
      return t("runDone", "Ran in %(ms)s ms").replace("%(ms)s", res.ms || 0);
    },
    runTone: function () { var r = this.ran.res; return !r ? "" : r.verdict === "pass" || r.verdict === "match" ? "good" : r.ok && !r.verdict ? "" : "bad"; },
    runKey: function (e) { if ((e.ctrlKey || e.metaKey) && (e.key === "'" || e.key === "\\")) { e.preventDefault(); this.run(); return true; } return false; },
  };

  document.addEventListener("alpine:init", function () {
    /* ── A practice session (also one question on its own page) ─────────── */
    Alpine.data("prepSession", function (source) {
      var S = data(source || "prep-session"), list = S.questions || [];
      return Object.assign({}, runMixin, {
        list: list, i: 0, q: null, stage: list.length ? "ask" : "empty", chosen: [], text: "", ticked: [], right: null, busy: false,
        started: 0, total: list.length, back: S.back || "", single: !!S.single, shown: 0, ranOk: false, now: Date.now(), skipped: {},
        tally: { n: 0, right: 0, partly: 0, wrong: 0, seconds: 0 }, missed: [], byTopic: {},
        init: function () {
          var self = this;
          if (list.length) this.load(0);
          setInterval(function () { self.now = Date.now(); }, 1000);
        },
        load: function (i) {
          this.i = i; this.q = this.list[i]; this.stage = "ask"; this.chosen = []; this.ticked = []; this.right = null;
          this.shown = 0; this.ranOk = false; this.ran = { busy: false, loading: false, res: null };
          this.warm();
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
          var sent = { choice: this.chosen.join(","), seconds: this.seconds() };
          if (right && this.shown) sent.rating = 2;          // right, with a hint: it comes back sooner
          Work.api(Work.cfg.urls.prepBase + q.id + "/answer/", sent);
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
          if (this.ranOk && !this.ticked.length) c = null;                              // the checks passed: that's the mark until points are ticked
          var r = c === null ? (this.ranOk ? 3 : 0) : c >= 0.999 ? 3 : c >= 0.6 ? 2 : 1;
          if (this.ran.res && this.ran.res.verdict && !this.ranOk && r > 2) r = 2;      // the checks didn't pass
          return this.shown && r > 2 ? 2 : r;                                          // a hint was needed: Hard at best
        },
        /* hints, one at a time */
        hint: function () { if (this.q && this.shown < this.q.hints.length) this.shown++; },
        /* not now: to the end of the session (once) */
        skip: function () {
          if (this.single || this.stage !== "ask" || this.i + 1 >= this.list.length) return;
          var q = this.list.splice(this.i, 1)[0];
          if (!this.skipped[q.id]) { this.skipped[q.id] = true; this.list.push(q); } else this.total--;
          this.load(this.i);
        },
        canSkip: function () { return !this.single && this.stage === "ask" && this.i + 1 < this.list.length; },
        timeOn: function () { return clock(Math.max(0, (this.now - this.started) / 1000)); },
        codeNow: function () { return this.text; },
        resetCode: function () { if (this.q) this.text = this.q.starter || ""; this.ran = { busy: false, loading: false, res: null }; },
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
        after: function (r) { return (this.q && this.q.after && this.q.after[r]) || ""; },
        tab: tabKey,
        key: function (e) {
          if (this.stage === "empty" || this.stage === "done" || this.stage === "rated") return;
          if (this.runKey(e)) return;
          var inBox = typing(e.target);
          if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); this.go(); return; }
          if (inBox) return;
          if (e.key === "Enter" || e.key === " ") { e.preventDefault(); this.go(); return; }
          if (e.key === "h" && this.stage === "ask") { e.preventDefault(); this.hint(); return; }
          if (e.key === "s" && this.canSkip()) { e.preventDefault(); this.skip(); return; }
          var n = parseInt(e.key, 10);
          if (!n) return;
          if (this.stage === "ask" && this.isChoice() && n <= this.q.options.length) { e.preventDefault(); this.toggle(n - 1); }
          else if (this.stage === "answered" && !this.isChoice() && n <= 4) { e.preventDefault(); this.rate(n); }
        },
        go: function () {             // Enter: check, show the answer, or carry on
          if (this.stage === "ask") { if (this.isChoice()) this.check(); else this.reveal(); }
          else if (this.stage === "answered") { if (this.isChoice()) this.next(); else this.rate(this.suggested() || 3); }
        },
      });
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
      return Object.assign({}, runMixin, {
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
          this.ran = { busy: false, loading: false, res: null };
          this.warm();
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
          if (!forced) {
            var self = this;
            FT.ask(n ? t("unanswered", "%(n)s questions have no answer yet. Hand in anyway?").replace("%(n)s", n) : t("submit", "Hand in the exam now?")).then(function (sure) { if (sure) self.handIn(true); });
            return;
          }
          this.handedIn = true; clearInterval(this.timer); clearTimeout(this.saver); this.dirty = false;
          try { localStorage.removeItem(store); } catch (e) { /* fine */ }
          this.$refs.answers.value = JSON.stringify(this.payload());
          this.$refs.form.submit();
        },
        codeNow: function () { return this.a.text; },
        resetCode: function () { this.a.text = this.q.starter || ""; this.ran = { busy: false, loading: false, res: null }; },
        tab: tabKey,
        key: function (e) {
          if (this.runKey(e)) return;
          if (typing(e.target)) return;
          if (e.key === "ArrowRight" || e.key === "n") { e.preventDefault(); this.load(this.i + 1); }
          else if (e.key === "ArrowLeft" || e.key === "p") { e.preventDefault(); this.load(this.i - 1); }
          else if (e.key === "f") { e.preventDefault(); this.a.flag = !this.a.flag; }
          else if (this.q.kind === "choice") {
            var n = parseInt(e.key, 10);
            if (n && n <= this.q.options.length) { e.preventDefault(); this.toggle(n - 1); }
          }
        },
      });
    });

    /* ── A topic's contents: sections and numbered questions, edited in place ── */
    Alpine.data("prepContents", function () {
      var C = data("prep-contents"), sorters = [];
      function blank() { return { prompt: "", answer: "", kind: "short", difficulty: 2, level: "", open: false }; }
      return {
        sections: C.sections, find: "", expandAll: false, open: null, editing: null, draft: {}, adding: {}, newSection: "",
        renaming: null, renameText: "", saving: false,
        init: function () {
          var self = this;
          this.sections.forEach(function (s) { self.adding[s.id] = blank(); });
          this.$nextTick(function () { self.sortable(); });
        },
        api: function (url, fields) {
          var self = this; this.saving = true;
          return Work.api(url, fields).then(function (r) {
            self.saving = false;
            if (!r || (!r.ok && !r.queued)) toast((r && r.error) || t("notSaved", "Not saved — check your connection."), "warn");
            return r || {};
          });
        },
        md: md,
        points: function (q) { return (q.key_points || "").split("\n").map(function (l) { return l.replace(/^[\s*•-]+/, "").trim(); }).filter(Boolean); },
        sectionNo: function (s) { return this.sections.filter(function (x) { return x.id; }).indexOf(s) + 1; },
        renumber: function () {
          var self = this;
          this.sections.forEach(function (s) {
            var no = self.sectionNo(s);
            s.questions.forEach(function (q, i) { q.number = C.code + "-" + (s.id ? no + "." : "") + (i + 1); q.section = s.id; });
          });
        },
        mastered: function (s) { return s.questions.filter(function (q) { return q.status === "mastered"; }).length; },
        matches: function (q) {
          var f = this.find.trim().toLowerCase();
          if (!f) return true;
          if (/^[a-z0-9\u0980-\u09ff]*[-\s]?\d+(\.\d+)?$/i.test(f)) {
            var n = q.number.toLowerCase();
            if (n === f || n.endsWith("-" + f.replace(/^[^\d]*[-\s]?/, ""))) return true;
          }
          return (q.title + " " + q.prompt + " " + q.answer).toLowerCase().indexOf(f) >= 0;
        },
        toggle: function (q) { this.open = this.open === q.id ? null : q.id; },
        /* drag to reorder: Sortable moves the row, then the data is changed and Alpine draws it again */
        sortable: function () {
          if (!window.Sortable) { var self0 = this; setTimeout(function () { self0.sortable(); }, 100); return; }
          var self = this, root = this.$refs.sections;
          // the floating copy Sortable drags is a clone of the row: Alpine is told to leave it alone
          // (set on press, before Sortable clones it; Alpine's own flag is cleared again afterwards)
          function start(evt) { evt.item.setAttribute("x-ignore", ""); }
          function done(evt) { evt.item.removeAttribute("x-ignore"); delete evt.item._x_ignore; }
          function undoMove(evt, selector) {
            done(evt);
            evt.item.remove();
            evt.from.insertBefore(evt.item, evt.from.querySelectorAll(":scope > " + selector)[evt.oldDraggableIndex] || null);
          }
          if (!root._sortable) root._sortable = Sortable.create(root, {
            handle: ".wpc-head .wpc-grip", draggable: ".wpc-section", animation: 150, forceFallback: true, fallbackOnBody: true, onChoose: start, onUnchoose: done,
            onEnd: function (evt) {
              if (evt.oldDraggableIndex === evt.newDraggableIndex) { done(evt); return; }
              undoMove(evt, ".wpc-section");
              var moved = self.sections.splice(evt.oldDraggableIndex, 1)[0];
              self.sections.splice(Math.max(1, evt.newDraggableIndex), 0, moved);     // "not in a section" stays first
              self.renumber(); self.saveOrder();
            },
          });
          root.querySelectorAll(".wpc-list").forEach(function (list) {
            if (list._sortable) return;
            list._sortable = Sortable.create(list, {
              group: "wpc-questions", handle: ".wpc-grip", draggable: ".wpc-q", animation: 150, forceFallback: true, fallbackOnBody: true, emptyInsertThreshold: 28, onChoose: start, onUnchoose: done,
              onEnd: function (evt) {
                if (evt.from === evt.to && evt.oldDraggableIndex === evt.newDraggableIndex) { done(evt); return; }
                undoMove(evt, ".wpc-q");
                var from = self.byId(+evt.from.getAttribute("data-section")), to = self.byId(+evt.to.getAttribute("data-section"));
                var q = from.questions.splice(evt.oldDraggableIndex, 1)[0];
                to.questions.splice(evt.newDraggableIndex, 0, q);
                self.renumber(); self.saveOrder();
              },
            });
          });
        },
        byId: function (id) { return this.sections.filter(function (s) { return s.id === id; })[0]; },
        saveOrder: function () {
          var order = { sections: [], questions: {} };
          this.sections.forEach(function (s) { if (s.id) order.sections.push(s.id); order.questions[s.id] = s.questions.map(function (q) { return q.id; }); });
          this.api(C.api, { action: "order", order: JSON.stringify(order) });
        },
        /* questions */
        startEdit: function (q) {
          this.editing = q.id; this.open = q.id;
          this.draft = { prompt: q.prompt, answer: q.answer, key_points: q.key_points, kind: q.kind, difficulty: q.difficulty, level: q.level, section: q.section };
          var self = this;
          this.$nextTick(function () { var box = self.$root.querySelector('.wpc-q[data-id="' + q.id + '"] .wpc-edit textarea'); if (box) box.focus(); });
        },
        saveEdit: function (q) {
          var self = this, d = this.draft, was = q.section, moved = d.section !== was;
          if (!d.prompt.trim()) { toast(t("writeFirst", "Write the question first."), "warn"); return; }
          this.api(Work.cfg.urls.prepBase + q.id + "/", Object.assign({ action: "update" }, d)).then(function (r) {
            if (!r.ok && !r.queued) return;
            Object.assign(q, r.question || { prompt: d.prompt, answer: d.answer, key_points: d.key_points, level: d.level });
            if (moved) {
              var from = self.byId(was), to = self.byId(d.section);
              if (from && to) { from.questions.splice(from.questions.indexOf(q), 1); to.questions.push(q); }
            }
            self.renumber(); self.editing = null;
            toast(t("saved", "Saved"), "good");
          });
        },
        remove: function (q, s) {
          var self = this;
          this.api(Work.cfg.urls.prepBase + q.id + "/", { action: "delete" }).then(function (r) {
            if (!r.ok) return;
            s.questions.splice(s.questions.indexOf(q), 1); self.renumber();
            Work.undoable(t("deleted", "Question deleted"), r.undo, function () { location.reload(); });
          });
        },
        add: function (s) {
          var self = this, a = this.adding[s.id];
          if (!a.prompt.trim()) { toast(t("writeFirst", "Write the question first."), "warn"); return; }
          this.api(C.api, { action: "question_add", section: s.id, prompt: a.prompt, answer: a.answer, kind: a.kind, difficulty: a.difficulty, level: a.level }).then(function (r) {
            if (!r.ok || !r.question) return;
            s.questions.push(r.question); self.renumber();
            self.adding[s.id] = Object.assign(blank(), { open: true, kind: a.kind, difficulty: a.difficulty, level: a.level });    // ready for the next one
            toast(t("added", "Question added") + " · " + r.question.number, "good");
            self.$nextTick(function () { var box = self.$root.querySelector('.wpc-section[data-section="' + s.id + '"] .wpc-add textarea'); if (box) box.focus(); });
          });
        },
        /* sections */
        addSection: function () {
          var self = this, name = this.newSection.trim();
          if (!name) return;
          this.api(C.api, { action: "section_add", name: name }).then(function (r) {
            if (!r.ok || !r.section) return;
            self.adding[r.section.id] = blank(); self.sections.push(r.section); self.newSection = "";
            self.$nextTick(function () { self.sortable(); });
          });
        },
        startRename: function (s) {
          this.renaming = s.id; this.renameText = s.name;
          var self = this; this.$nextTick(function () { if (self.$refs.renameBox) { self.$refs.renameBox.focus(); self.$refs.renameBox.select(); } });
        },
        rename: function (s) {
          if (this.renaming !== s.id) return;
          var name = this.renameText.trim(); this.renaming = null;
          if (!name || name === s.name) return;
          s.name = name; this.api(C.api, { action: "section_rename", section: s.id, name: name });
        },
        dropSection: function (s) {
          var self = this;
          FT.ask({ message: t("dropSection", "Delete this section? Its questions stay, outside any section."), danger: true, after: "gone" }).then(function (sure) {
            if (!sure) return;
            self.api(C.api, { action: "section_delete", section: s.id }).then(function (r) {
              if (!r.ok) return;
              self.byId(0).questions = self.byId(0).questions.concat(s.questions);
              self.sections.splice(self.sections.indexOf(s), 1); self.renumber();
            });
          });
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
