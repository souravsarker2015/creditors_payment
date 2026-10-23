/* Exam notes (Productivity): a subject's questions and answers — added one by
   one or pasted as a list (with a preview first), edited, starred, moved and
   deleted in place, chapter by chapter — and flipping through them one at a
   time. Loaded after work.js on those pages.

   Answers are Markdown: lists, tables, code, ```mermaid diagrams, pictures,
   and formulas ($…$, $$…$$, \(…\), \[…\] — what ChatGPT and Claude write).
   Pasting a ChatGPT or Claude reply that was copied as formatted text turns
   it back into Markdown (textarea[data-md-paste]).

   Review: the question first; think of the answer, turn the card over, then
   "I knew it" (marked as known) or "Not yet" (it comes back at the end of the
   round, is marked as not known, and counts as missed once more). */
(function () {
  "use strict";
  var d = document;
  function data(id) { try { return JSON.parse(d.getElementById(id).textContent); } catch (e) { return {}; } }
  var T = data("exam-text");
  function t(key, fallback) { return T[key] || fallback || key; }
  function toast(msg, tone) { if (window.Work && Work.toast) Work.toast(msg, tone); }
  function api(url, fields) {
    return Work.api(url, fields).then(function (r) {
      if (!r || (!r.ok && !r.queued)) toast((r && r.error) || t("notSaved", "Not saved — check your connection."), "warn");
      return r || {};
    });
  }

  /* ── Markdown with formulas ── */
  function markdown(text) {
    var md = window.Work && Work.markdown ? Work.markdown : function (s) { return s; };
    if (!window.katex) return md(text || "");
    var maths = [];
    function keep(display) {
      return function (m, tex) { maths.push({ tex: tex, display: display }); return "@@KM" + (maths.length - 1) + "@@"; };
    }
    // code (``` blocks and `inline`) is left as it is: only the text between gets formulas
    var parts = String(text || "").split(/(```[\s\S]*?(?:```|$)|~~~[\s\S]*?(?:~~~|$)|`[^`\n]+`)/);
    for (var i = 0; i < parts.length; i += 2) {
      parts[i] = parts[i]
        .replace(/\$\$([\s\S]+?)\$\$/g, keep(true))
        .replace(/\\\[([\s\S]+?)\\\]/g, keep(true))
        .replace(/\\\(([\s\S]+?)\\\)/g, keep(false))
        .replace(/(^|[^\\$\w])\$(?!\s)([^\n$]+?)(?<!\s)\$(?!\d)/g, function (m, pre, tex) { return pre + keep(false)(m, tex); });
    }
    return md(parts.join("")).replace(/@@KM(\d+)@@/g, function (m, n) {
      var x = maths[+n];
      try { return katex.renderToString(x.tex, { displayMode: x.display, throwOnError: false, output: "htmlAndMathml" }); }
      catch (e) { return m; }
    });
  }
  function paint(el, text) {
    if (!el) return;
    el.innerHTML = markdown(text);
    if (window.Work && Work.mermaidIn) Work.mermaidIn(el);
    if (window.hljs) el.querySelectorAll("pre code:not(.language-mermaid)").forEach(function (c) { hljs.highlightElement(c); });
  }

  /* ── A ChatGPT / Claude reply copied as formatted text → Markdown again ── */
  var turndown = null;
  function toMarkdown(html) {
    if (!turndown) {
      turndown = new TurndownService({ headingStyle: "atx", codeBlockStyle: "fenced", bulletListMarker: "-", emDelimiter: "*", hr: "---" });
      if (window.turndownPluginGfm) turndown.use(turndownPluginGfm.gfm);
      turndown.remove(["button", "style", "script", "svg"]);           // "Copy code" buttons and icons
      turndown.addRule("math", {                                        // KaTeX keeps the formula it drew
        filter: function (n) { return n.classList && (n.classList.contains("katex-display") || n.classList.contains("katex")); },
        replacement: function (content, n) {
          var a = n.querySelector('annotation[encoding="application/x-tex"]');
          if (!a) return content;
          var tex = a.textContent.trim();
          return n.classList.contains("katex-display") ? "\n\n$$" + tex + "$$\n\n" : "$" + tex + "$";
        },
      });
      turndown.addRule("code", {                                        // a code box: its language and its code, not its toolbar
        filter: function (n) { return n.nodeName === "PRE"; },
        replacement: function (content, n) {
          var c = n.querySelector("code") || n, lang = ((c.className || "").match(/language-([\w+#.-]+)/) || [])[1] || "";
          return "\n\n```" + lang + "\n" + c.textContent.replace(/\n+$/, "") + "\n```\n\n";
        },
      });
    }
    return turndown.turndown(html).replace(/\n{3,}/g, "\n\n").trim();
  }
  function looksLikeMarkdown(text) {
    return /(^|\n)\s{0,3}(#{1,6}\s|```|[-*+]\s|\d+[.)]\s|>\s|\|.*\|)|\*\*[^*\n]+\*\*|`[^`\n]+`|\$[^$\n]+\$/.test(text || "");
  }
  d.addEventListener("paste", function (e) {
    var ta = e.target && e.target.closest && e.target.closest("textarea[data-md-paste]");
    if (!ta || e.defaultPrevented || !e.clipboardData || !window.TurndownService) return;
    var html = e.clipboardData.getData("text/html"), text = e.clipboardData.getData("text/plain");
    if (!html || !/<(h[1-6]|li|pre|strong|b|em|table|code|blockquote|span class="katex)[\s>"]/i.test(html) || looksLikeMarkdown(text)) return;
    var md = "";
    try { md = toMarkdown(html); } catch (err) { return; }
    if (!md) return;
    e.preventDefault();
    ta.setRangeText(md, ta.selectionStart, ta.selectionEnd, "end");
    ta.dispatchEvent(new Event("input", { bubbles: true }));
  });

  function copy(text) {
    if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text);
    var ta = d.createElement("textarea"); ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0";
    d.body.appendChild(ta); ta.select(); d.execCommand("copy"); ta.remove();
    return Promise.resolve();
  }

  document.addEventListener("alpine:init", function () {
    /* ── a subject's page ── */
    Alpine.data("examSubject", function () {
      var D = data("exam-data");
      return {
        notes: D.notes || [], subjects: D.subjects || [], draft: { question: "", answer: "", chapter: "" },
        many: false, paste: "", pasteChapter: "", preview: null, checking: false, previewTimer: null,
        find: "", show: "all", openAll: false, open: {}, folded: {}, editing: null, edit: {},
        t: t,
        init: function () {
          var self = this, hash = /^#q(\d+)$/.exec(location.hash);     // from a search result: open that one
          if (hash) {
            this.open[+hash[1]] = true;
            this.$nextTick(function () { var el = d.getElementById("q" + hash[1]); if (el) el.scrollIntoView({ block: "center" }); });
          }
          window.addEventListener("beforeprint", function () { self.openAll = true; self.folded = {}; });
          this.$watch("paste", function () { self.schedulePreview(); });
          this.$watch("pasteChapter", function () { if (self.paste.trim()) self.schedulePreview(); });
        },
        paint: function (el, text) { if (el._md !== text) { el._md = text; paint(el, text); } },
        count: function () { var n = this.notes.length; return t(n === 1 ? "countOne" : "count").replace("%(counter)s", n); },
        known: function () { return this.notes.filter(function (q) { return q.known; }).length; },
        chapters: function () {
          var out = [];
          this.notes.forEach(function (q) { if (q.chapter && out.indexOf(q.chapter) < 0) out.push(q.chapter); });
          return out;
        },
        groups: function () {           // no chapter first, then the chapters in the order they were first used
          var by = {}, keys = [];
          this.notes.forEach(function (q) { if (!by[q.chapter]) { by[q.chapter] = []; keys.push(q.chapter); } by[q.chapter].push(q); });
          keys.sort(function (a, b) { return (a ? 1 : 0) - (b ? 1 : 0); });
          return keys.map(function (k) { return { chapter: k, notes: by[k] }; });
        },
        renumber: function () {
          var n = 0, order = [];
          this.groups().forEach(function (g) { g.notes.forEach(function (q) { q.number = ++n; order.push(q); }); });
          Array.prototype.splice.apply(this.notes, [0, this.notes.length].concat(order));
        },
        visible: function (q) {
          if (this.show === "unknown" && q.known) return false;
          if (this.show === "starred" && !q.starred) return false;
          if (this.show === "missed" && !q.misses) return false;
          var f = this.find.trim().toLowerCase();
          return !f || (q.question + "\n" + q.answer + "\n" + q.chapter).toLowerCase().indexOf(f) >= 0 || String(q.number) === f;
        },
        shown: function (g) { var self = this; return g.notes.some(function (q) { return self.visible(q); }); },
        knownIn: function (g) { return g.notes.filter(function (q) { return q.known; }).length; },
        reviewUrl: function (g) { return D.review + "?which=all&chapter=" + encodeURIComponent(g.chapter); },
        isOpen: function (q) { return this.openAll || !!this.open[q.id]; },
        toggle: function (q) { this.open[q.id] = !this.isOpen(q); if (this.openAll && !this.open[q.id]) this.openAll = false; },
        /* adding */
        add: function () {
          var self = this, q = this.draft.question.trim();
          if (!q) { toast(t("writeFirst"), "warn"); return; }
          api(D.api, { action: "add", question: q, answer: this.draft.answer, chapter: this.draft.chapter }).then(function (r) {
            if (!r.ok || !r.note) return;
            self.notes.push(r.note); self.renumber();
            self.draft = { question: "", answer: "", chapter: self.draft.chapter };        // the chapter stays for the next one
            toast(t("added", "Added") + " · " + r.note.number, "good");
            self.$nextTick(function () { self.$refs.question && self.$refs.question.focus(); });
          });
        },
        schedulePreview: function () {
          var self = this;
          clearTimeout(this.previewTimer);
          if (!this.paste.trim()) { this.preview = null; return; }
          this.previewTimer = setTimeout(function () { self.check(); }, 450);
        },
        check: function () {
          var self = this, text = this.paste;
          if (!text.trim()) { this.preview = null; return; }
          this.checking = true;
          Work.api(D.api, { action: "add_many", text: text, chapter: this.pasteChapter, preview: "1" }).then(function (r) {
            self.checking = false;
            if (text !== self.paste) return;                 // changed meanwhile: a newer check is on its way
            self.preview = r && r.ok ? r : { found: [], new: 0, error: r && r.error };
          });
        },
        addMany: function () {
          var self = this;
          if (!this.paste.trim()) { toast(t("pasteFirst"), "warn"); return; }
          api(D.api, { action: "add_many", text: this.paste, chapter: this.pasteChapter }).then(function (r) {
            if (!r.ok || !r.notes) return;
            r.notes.forEach(function (n) { self.notes.push(n); });
            self.renumber(); self.paste = ""; self.preview = null; self.many = false;
            toast(r.message, "good");
          });
        },
        copyPrompt: function () { copy(this.$refs.prompt.value).then(function () { toast(t("copied"), "good"); }); },
        /* one question */
        flag: function (q, what) {
          var key = what === "star" ? "starred" : "known";
          q[key] = !q[key];
          api(D.noteBase + q.id + "/", { action: what, value: q[key] ? "1" : "0" }).then(function (r) { if (!r.ok && !r.queued) q[key] = !q[key]; });
        },
        startEdit: function (q) {
          this.edit = { question: q.question, answer: q.answer, chapter: q.chapter, subject: D.subject }; this.editing = q.id;
          this.$nextTick(function () { var box = d.querySelector("#q" + q.id + " .wpc-edit textarea"); if (box) box.focus(); });
        },
        saveEdit: function (q) {
          var self = this, e = this.edit;
          if (!e.question.trim()) { toast(t("writeFirst"), "warn"); return; }
          api(D.noteBase + q.id + "/", { action: "update", question: e.question, answer: e.answer, chapter: e.chapter, subject: e.subject }).then(function (r) {
            if (!r.ok && !r.queued) return;
            self.editing = null;
            if (String(e.subject) !== String(D.subject)) {       // moved to another subject
              self.notes.splice(self.notes.indexOf(q), 1); self.renumber();
              var to = self.subjects.find(function (s) { return String(s.id) === String(e.subject); });
              toast(t("moved").replace("%(name)s", to ? to.name : ""), "good");
              return;
            }
            q.question = e.question.trim(); q.answer = e.answer; q.chapter = (e.chapter || "").trim(); self.open[q.id] = true;
            self.renumber();
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
        /* chapters and the whole subject */
        renameChapter: function (g) {
          var self = this, name = prompt(t("renameAsk"), g.chapter);
          if (name === null || name.trim() === g.chapter) return;
          name = name.trim();
          api(D.api, { action: "rename_chapter", old: g.chapter, chapter: name }).then(function (r) {
            if (!r.ok) return;
            self.notes.forEach(function (q) { if (q.chapter === g.chapter) q.chapter = name; });
            self.renumber();
          });
        },
        reset: function () {
          var self = this;
          if (!confirm(t("resetAsk"))) return;
          api(D.api, { action: "reset" }).then(function (r) { if (r.ok) self.notes.forEach(function (q) { q.known = false; }); });
        },
        printAll: function () { this.openAll = true; this.folded = {}; this.$nextTick(function () { setTimeout(function () { window.print(); }, 300); }); },
      };
    });

    /* ── flip through them ── */
    Alpine.data("examReview", function () {
      var D = data("exam-data");
      return {
        all: D.notes || [], chapters: D.chapters || [], chapter: D.chapter || "", which: D.which || "unknown", shuffle: !!D.shuffle, back: D.back,
        queue: [], pos: 0, card: null, flipped: false, stage: "card", editing: false, draft: {},
        seen: 0, firstTry: 0, missed: [], started: 0, took: "",
        init: function () { this.start(this.which); },
        start: function (which) {
          var chapter = this.chapter;
          this.which = which;
          var list = this.all.filter(function (q) {
            if (chapter && q.chapter !== chapter) return false;
            return which === "all" || (which === "starred" ? q.starred : which === "missed" ? q.misses > 0 : !q.known);
          });
          if (this.shuffle) {
            for (var i = list.length - 1; i > 0; i--) { var j = Math.floor(Math.random() * (i + 1)), x = list[i]; list[i] = list[j]; list[j] = x; }
          } else if (which === "missed") {
            list.sort(function (a, b) { return b.misses - a.misses || a.number - b.number; });       // the most missed first
          }
          this.queue = list.slice(); this.pos = 0; this.seen = list.length; this.firstTry = 0; this.missed = [];
          this.started = Date.now();
          if (!list.length) { this.stage = "empty"; return; }
          this.stage = "card"; this.showCard();
        },
        showCard: function () {
          var self = this;
          this.card = this.queue[this.pos]; this.flipped = false;
          this.$nextTick(function () { paint(self.$refs.front, self.card.question); paint(self.$refs.q, self.card.question); paint(self.$refs.back, self.card.answer || t("noAnswer")); });
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
          if (!knew) { if (this.missed.indexOf(q) < 0) this.missed.push(q); this.queue.push(q); q.misses++; }
          q.known = knew;
          api(D.noteBase + q.id + "/", { action: "review", knew: knew ? "1" : "0" });
          this.pos++;
          if (this.pos >= this.queue.length) {
            var secs = Math.round((Date.now() - this.started) / 1000);
            this.took = window.Work && Work.clock ? Work.clock(secs) : secs + "s";
            this.stage = "done"; return;
          }
          this.showCard();
        },
        /* fix a typo without leaving the review */
        startEdit: function () {
          if (!this.card) return;
          this.draft = { question: this.card.question, answer: this.card.answer }; this.editing = true;
          var self = this; this.$nextTick(function () { self.$refs.editQuestion && self.$refs.editQuestion.focus(); });
        },
        saveEdit: function () {
          var self = this, q = this.card, e = this.draft;
          if (!e.question.trim()) { toast(t("writeFirst"), "warn"); return; }
          api(D.noteBase + q.id + "/", { action: "update", question: e.question, answer: e.answer }).then(function (r) {
            if (!r.ok && !r.queued) return;
            q.question = e.question.trim(); q.answer = e.answer; self.editing = false;
            paint(self.$refs.front, q.question); paint(self.$refs.q, q.question); paint(self.$refs.back, q.answer || t("noAnswer"));
            toast(t("saved", "Saved"), "good");
          });
        },
        key: function (e) {
          if (this.editing || e.ctrlKey || e.metaKey || e.altKey || /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)) return;
          if (e.key === "Escape") { location.href = this.back; return; }
          if (this.stage !== "card") return;
          if (e.key === " " || e.key === "Enter") { if (e.target.closest && e.target.closest("button, a, select")) return; e.preventDefault(); this.flip(); }
          else if (e.key === "e" || e.key === "E") { e.preventDefault(); this.startEdit(); }
          else if (this.flipped && (e.key === "1" || e.key === "ArrowLeft")) { e.preventDefault(); this.mark(false); }
          else if (this.flipped && (e.key === "2" || e.key === "ArrowRight")) { e.preventDefault(); this.mark(true); }
        },
      };
    });
  });
})();
