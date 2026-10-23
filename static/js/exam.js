/* Exam notes (Productivity): a subject's questions and answers — added,
   edited, starred and deleted in place — and flipping through them one at a
   time. Loaded after work.js on those pages.

   Review: the question first; think of the answer, turn the card over, then
   "I knew it" (marked as known) or "Not yet" (it comes back at the end of the
   round, and is marked as not known). */
(function () {
  "use strict";
  var d = document;
  function data(id) { try { return JSON.parse(d.getElementById(id).textContent); } catch (e) { return {}; } }
  var T = data("exam-text");
  function t(key, fallback) { return T[key] || fallback || key; }
  function md(text) { return window.Work && Work.markdown ? Work.markdown(text || "") : String(text || ""); }
  function toast(msg, tone) { if (window.Work && Work.toast) Work.toast(msg, tone); }
  function show(el, text) {
    if (!el) return;
    el.innerHTML = md(text);
    if (window.hljs) el.querySelectorAll("pre code").forEach(function (c) { hljs.highlightElement(c); });
  }
  function api(url, fields) {
    return Work.api(url, fields).then(function (r) {
      if (!r || (!r.ok && !r.queued)) toast((r && r.error) || t("notSaved", "Not saved — check your connection."), "warn");
      return r || {};
    });
  }

  document.addEventListener("alpine:init", function () {
    /* ── a subject's page ── */
    Alpine.data("examSubject", function () {
      var D = data("exam-data");
      return {
        notes: D.notes || [], draft: { question: "", answer: "" }, many: false, paste: "",
        find: "", show: "all", openAll: false, open: {}, editing: null, edit: {},
        t: t, md: md,
        init: function () {
          var self = this, hash = /^#q(\d+)$/.exec(location.hash);     // from a search result: open that one
          if (hash) {
            this.open[+hash[1]] = true;
            this.$nextTick(function () { var el = d.getElementById("q" + hash[1]); if (el) el.scrollIntoView({ block: "center" }); });
          }
          window.addEventListener("beforeprint", function () { self.openAll = true; });
        },
        count: function () { var n = this.notes.length; return t(n === 1 ? "countOne" : "count").replace("%(counter)s", n); },
        known: function () { return this.notes.filter(function (q) { return q.known; }).length; },
        renumber: function () { this.notes.forEach(function (q, i) { q.number = i + 1; }); },
        visible: function (q) {
          if (this.show === "unknown" && q.known) return false;
          if (this.show === "starred" && !q.starred) return false;
          var f = this.find.trim().toLowerCase();
          return !f || (q.question + "\n" + q.answer).toLowerCase().indexOf(f) >= 0 || String(q.number) === f;
        },
        isOpen: function (q) { return this.openAll || !!this.open[q.id]; },
        toggle: function (q) { this.open[q.id] = !this.isOpen(q); if (this.openAll && !this.open[q.id]) this.openAll = false; },
        add: function () {
          var self = this, q = this.draft.question.trim();
          if (!q) { toast(t("writeFirst"), "warn"); return; }
          api(D.api, { action: "add", question: q, answer: this.draft.answer }).then(function (r) {
            if (!r.ok || !r.note) return;
            self.notes.push(r.note); self.renumber();
            self.draft = { question: "", answer: "" };
            toast(t("added", "Added") + " · " + r.note.number, "good");
            self.$nextTick(function () { self.$refs.question && self.$refs.question.focus(); });
          });
        },
        addMany: function () {
          var self = this;
          if (!this.paste.trim()) { toast(t("pasteFirst"), "warn"); return; }
          api(D.api, { action: "add_many", text: this.paste }).then(function (r) {
            if (!r.ok || !r.notes) return;
            r.notes.forEach(function (n) { self.notes.push(n); });
            self.renumber(); self.paste = ""; self.many = false;
            toast(r.message, "good");
          });
        },
        flag: function (q, what) {
          var key = what === "star" ? "starred" : "known";
          q[key] = !q[key];
          api(D.noteBase + q.id + "/", { action: what, value: q[key] ? "1" : "0" }).then(function (r) { if (!r.ok && !r.queued) q[key] = !q[key]; });
        },
        startEdit: function (q) {
          this.edit = { question: q.question, answer: q.answer }; this.editing = q.id;
          var self = this;
          this.$nextTick(function () { var box = d.querySelector("#q" + q.id + " .wpc-edit textarea"); if (box) box.focus(); });
        },
        saveEdit: function (q) {
          var self = this, e = this.edit;
          if (!e.question.trim()) { toast(t("writeFirst"), "warn"); return; }
          api(D.noteBase + q.id + "/", { action: "update", question: e.question, answer: e.answer }).then(function (r) {
            if (!r.ok && !r.queued) return;
            q.question = e.question.trim(); q.answer = e.answer; self.editing = null; self.open[q.id] = true;
          });
        },
        remove: function (q) {
          var self = this;
          api(D.noteBase + q.id + "/", { action: "delete" }).then(function (r) {
            if (!r.ok) return;
            self.notes.splice(self.notes.indexOf(q), 1); self.renumber();
            Work.undoable(t("deleted", "Question deleted"), r.undo, function () { location.reload(); });
          });
        },
        reset: function () {
          var self = this;
          if (!confirm(t("resetAsk"))) return;
          api(D.api, { action: "reset" }).then(function (r) { if (r.ok) self.notes.forEach(function (q) { q.known = false; }); });
        },
        printAll: function () { var self = this; this.openAll = true; this.$nextTick(function () { window.print(); }); },
      };
    });

    /* ── flip through them ── */
    Alpine.data("examReview", function () {
      var D = data("exam-data");
      return {
        all: D.notes || [], which: D.which || "unknown", shuffle: !!D.shuffle, back: D.back,
        queue: [], pos: 0, card: null, flipped: false, stage: "card",
        seen: 0, firstTry: 0, missed: [], started: 0, took: "",
        init: function () { this.start(this.which); },
        start: function (which) {
          this.which = which;
          var list = this.all.filter(function (q) { return which === "all" || (which === "starred" ? q.starred : !q.known); });
          if (this.shuffle) {
            for (var i = list.length - 1; i > 0; i--) { var j = Math.floor(Math.random() * (i + 1)), x = list[i]; list[i] = list[j]; list[j] = x; }
          }
          this.queue = list.slice(); this.pos = 0; this.seen = list.length; this.firstTry = 0; this.missed = [];
          this.started = Date.now();
          if (!list.length) { this.stage = "empty"; return; }
          this.stage = "card"; this.showCard();
        },
        showCard: function () {
          var self = this;
          this.card = this.queue[this.pos]; this.flipped = false;
          this.$nextTick(function () { show(self.$refs.front, self.card.question); show(self.$refs.q, self.card.question); show(self.$refs.back, self.card.answer || t("noAnswer")); });
        },
        leftText: function () {
          var n = this.queue.length - this.pos;
          return n === 1 ? t("leftOne", "1 question left") : t("left", "%(n)s questions left").replace("%(n)s", n);
        },
        flip: function () { if (this.stage === "card") this.flipped = !this.flipped; },
        mark: function (knew) {
          var q = this.card;
          if (!q || !this.flipped) return;
          if (knew && this.missed.indexOf(q) < 0) this.firstTry++;
          if (!knew) { if (this.missed.indexOf(q) < 0) this.missed.push(q); this.queue.push(q); }
          if (q.known !== knew) {
            q.known = knew;
            api(D.noteBase + q.id + "/", { action: "known", value: knew ? "1" : "0" });
          }
          this.pos++;
          if (this.pos >= this.queue.length) {
            var secs = Math.round((Date.now() - this.started) / 1000);
            this.took = window.Work && Work.clock ? Work.clock(secs) : secs + "s";
            this.stage = "done"; return;
          }
          this.showCard();
        },
        key: function (e) {
          if (e.ctrlKey || e.metaKey || e.altKey || /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)) return;
          if (e.key === "Escape") { location.href = this.back; return; }
          if (this.stage !== "card") return;
          if (e.key === " " || e.key === "Enter") { if (e.target.closest && e.target.closest("button, a")) return; e.preventDefault(); this.flip(); }
          else if (this.flipped && (e.key === "1" || e.key === "ArrowLeft")) { e.preventDefault(); this.mark(false); }
          else if (this.flipped && (e.key === "2" || e.key === "ArrowRight")) { e.preventDefault(); this.mark(true); }
        },
      };
    });
  });
})();
