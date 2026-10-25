/* Exam notes (Productivity): a subject's questions and answers — added one by
   one or pasted as a list (with a preview first), edited, starred, moved and
   deleted in place, chapter by chapter — and flipping through them one at a
   time. Loaded after work.js on those pages.

   Answers are Markdown: lists, tables, code, ```mermaid diagrams, pictures,
   and formulas ($…$, $$…$$, \(…\), \[…\] — what ChatGPT and Claude write).
   Pasting a ChatGPT or Claude reply that was copied as formatted text turns
   it back into Markdown (textarea[data-md-paste]).

   On the subject's page questions are dragged into order (and into another
   chapter), picked to be changed together, and a question being written is
   kept in the browser as a draft until it's added.

   Review: the question first (optionally: write your answer first); think of
   the answer, turn the card over, then "I knew it" (marked as known) or "Not
   yet" (it comes back at the end of the round, is marked as not known, and
   counts as missed once more). Swipe right / left on a phone; Z undoes. */
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

  function store(k, v) { if (window.Work && Work.store) Work.store(k, v); }
  function recall(k, fallback) { return window.Work && Work.recall ? Work.recall(k, fallback) : fallback; }
  function typing(e) {
    var el = e.target;
    return el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName));
  }
  function readFile(file) {
    return new Promise(function (resolve, reject) {
      if (!file || file.size > 2 * 1024 * 1024) return reject();
      var r = new FileReader(); r.onload = function () { resolve(String(r.result || "")); }; r.onerror = reject; r.readAsText(file);
    });
  }
  /* Where a bar of ours can stick: under the app's top bar and the work timer card, which stick too. */
  function stickyTop() {
    var top = 0;
    d.querySelectorAll(".topbar, .wt-bar").forEach(function (el) {
      var st = getComputedStyle(el);
      if (st.position === "sticky" && el.offsetParent) top = Math.max(top, (parseFloat(st.top) || 0) + el.offsetHeight);
    });
    d.documentElement.style.setProperty("--work-sticky-top", (top + 8) + "px");
    return top + 8;
  }
  window.addEventListener("resize", stickyTop);
  d.addEventListener("DOMContentLoaded", stickyTop);

  function copy(text) {
    if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text);
    var ta = d.createElement("textarea"); ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0";
    d.body.appendChild(ta); ta.select(); d.execCommand("copy"); ta.remove();
    return Promise.resolve();
  }

  document.addEventListener("alpine:init", function () {
    /* ── a subject's page ── */
    Alpine.data("examSubject", function () {
      var D = data("exam-data"), DRAFT = "exam-draft-" + D.subject;
      return {
        notes: D.notes || [], subjects: D.subjects || [], draft: { question: "", answer: "", chapter: "" },
        many: false, paste: "", pasteChapter: "", preview: null, checking: false, previewTimer: null,
        find: "", show: "all", openAll: false, open: {}, folded: {}, editing: null, edit: {}, editFrom: null,
        writeView: { add: false, edit: false }, selecting: false, picked: {}, moveTo: "", adding: !(D.notes || []).length,
        t: t,
        init: function () {
          var self = this, hash = /^#q(\d+)$/.exec(location.hash);     // from a search result: open that one
          if (hash) {
            this.open[+hash[1]] = true;
            this.$nextTick(function () { var el = d.getElementById("q" + hash[1]); if (el) el.scrollIntoView({ block: "center" }); });
          }
          var saved = recall(DRAFT, null);                               // a question that wasn't added last time
          if (saved && (saved.question || saved.answer || saved.paste)) {
            this.draft = { question: saved.question || "", answer: saved.answer || "", chapter: saved.chapter || "" };
            this.paste = saved.paste || ""; this.many = !!saved.paste && !saved.question;
            this.adding = true;
            toast(t("draftBack"), "good");
          }
          this.$watch("draft", function () { self.keepDraft(); }, { deep: true });
          this.$watch("paste", function () { self.keepDraft(); self.schedulePreview(); });
          this.$watch("pasteChapter", function () { if (self.paste.trim()) self.schedulePreview(); });
          window.addEventListener("beforeprint", function () { self.openAll = true; self.folded = {}; });
          window.addEventListener("beforeunload", function (e) {           // an edit in place isn't kept as a draft
            if (self.editing !== null && JSON.stringify(self.edit) !== self.editFrom) { e.preventDefault(); e.returnValue = t("leave"); }
          });
          this.$nextTick(function () { self.sortable(); });
        },
        keepDraft: function () {
          var x = this.draft, v = x.question.trim() || x.answer.trim() || this.paste.trim() ? { question: x.question, answer: x.answer, chapter: x.chapter, paste: this.paste } : null;
          store(DRAFT, v);
        },
        key: function (e) {             // a: add a question · r: review · (/ finds: the search box has data-work-search)
          if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey || typing(e)) return;
          if (e.key === "a") { e.preventDefault(); this.openAdd(false); }
          else if (e.key === "r" && this.notes.length) { e.preventDefault(); location.href = D.review; }
          else if (e.key === "Escape" && this.selecting) this.endSelect();
        },
        paint: function (el, text) { if (el._md !== text) { el._md = text; paint(el, text); } },
        openAdd: function (many) {
          var self = this;
          this.adding = true; this.many = many;
          this.$nextTick(function () {
            var box = many ? self.$root.querySelector(".wex-paste") : self.$refs.question;
            if (box) { box.focus(); box.scrollIntoView({ block: "center", behavior: "smooth" }); }
          });
        },
        count: function () { var n = this.notes.length; return t(n === 1 ? "countOne" : "count").replace("%(counter)s", n); },
        known: function () { return this.notes.filter(function (q) { return q.known; }).length; },
        pct: function () { return this.notes.length ? Math.round(100 * this.known() / this.notes.length) : 0; },
        pace: function () {             // "about 4 a day to learn them all before the exam"
          var left = this.notes.length - this.known();
          if (!this.notes.length) return "";
          if (!left) return t("allKnown");
          if (D.daysLeft === null || D.daysLeft === undefined || D.daysLeft < 1) return "";
          return t("perDay").replace("%(n)s", Math.ceil(left / D.daysLeft));
        },
        chapters: function () {
          var out = [];
          this.notes.forEach(function (q) { if (q.chapter && out.indexOf(q.chapter) < 0) out.push(q.chapter); });
          return out;
        },
        groups: function () {           // each chapter's questions together, chapters in the order their first question comes
          var by = {}, keys = [];
          this.notes.forEach(function (q) { if (!by[q.chapter]) { by[q.chapter] = []; keys.push(q.chapter); } by[q.chapter].push(q); });
          return keys.map(function (k) { return { chapter: k, notes: by[k] }; });
        },
        flatten: function (groups) {
          var n = 0, order = [];
          groups.forEach(function (g) { g.notes.forEach(function (q) { q.chapter = g.chapter; q.number = ++n; order.push(q); }); });
          Array.prototype.splice.apply(this.notes, [0, this.notes.length].concat(order));
          var self = this; this.$nextTick(function () { self.sortable(); });
        },
        renumber: function () { this.flatten(this.groups()); },
        saveOrder: function () {
          api(D.api, { action: "order", rows: JSON.stringify(this.notes.map(function (q) { return [q.id, q.chapter]; })) });
        },
        canDrag: function () { return this.show === "all" && !this.find.trim() && !this.selecting && this.editing === null; },
        sortable: function () {
          if (!window.Sortable) { var self0 = this; setTimeout(function () { self0.sortable(); }, 150); return; }
          var self = this;
          // Sortable drags a copy of the row: Alpine is told to leave it alone (and forgets that afterwards)
          function start(evt) { evt.item.setAttribute("x-ignore", ""); }
          function done(evt) { evt.item.removeAttribute("x-ignore"); delete evt.item._x_ignore; }
          this.$root.querySelectorAll(".wex-list").forEach(function (list) {
            if (list._sortable) return;
            list._sortable = Sortable.create(list, {
              group: "wex-questions", handle: ".wex-grip", draggable: ".wex-q", animation: 150, forceFallback: true, fallbackOnBody: true,
              emptyInsertThreshold: 28, onChoose: start, onUnchoose: done,
              onEnd: function (evt) {
                if (evt.from === evt.to && evt.oldDraggableIndex === evt.newDraggableIndex) { done(evt); return; }
                done(evt);
                evt.item.remove();      // put the row back: Alpine draws the new order from the data
                evt.from.insertBefore(evt.item, evt.from.querySelectorAll(":scope > .wex-q")[evt.oldDraggableIndex] || null);
                var groups = self.groups(), find = function (el) { var c = el.getAttribute("data-chapter"); return groups.filter(function (g) { return g.chapter === c; })[0]; };
                var from = find(evt.from), to = find(evt.to);
                if (!from || !to) return;
                to.notes.splice(evt.newDraggableIndex, 0, from.notes.splice(evt.oldDraggableIndex, 1)[0]);
                self.flatten(groups.filter(function (g) { return g.notes.length; })); self.saveOrder();
              },
            });
          });
        },
        moveChapter: function (g, step) {
          var groups = this.groups(), i = groups.map(function (x) { return x.chapter; }).indexOf(g.chapter), j = i + step;
          if (i < 0 || j < 0 || j >= groups.length) return;
          groups.splice(j, 0, groups.splice(i, 1)[0]);
          this.flatten(groups); this.saveOrder();
        },
        firstGroup: function (g) { var gs = this.groups(); return gs.length && gs[0].chapter === g.chapter; },
        lastGroup: function (g) { var gs = this.groups(); return gs.length && gs[gs.length - 1].chapter === g.chapter; },
        foldAll: function (on) { var self = this; this.groups().forEach(function (g) { self.folded[g.chapter] = on; }); },
        anyFolded: function () { var self = this; return this.groups().some(function (g) { return self.folded[g.chapter]; }); },
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
        toggle: function (q) {
          if (this.selecting) { this.pick(q); return; }
          this.open[q.id] = !this.isOpen(q); if (this.openAll && !this.open[q.id]) this.openAll = false;
        },
        /* adding */
        add: function () {
          var self = this, q = this.draft.question.trim();
          if (!q) { toast(t("writeFirst"), "warn"); return; }
          api(D.api, { action: "add", question: q, answer: this.draft.answer, chapter: this.draft.chapter }).then(function (r) {
            if (!r.ok || !r.note) return;
            self.notes.push(r.note); self.renumber();
            self.draft = { question: "", answer: "", chapter: self.draft.chapter };        // the chapter stays for the next one
            self.writeView.add = false;
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
            if (r && r.ok) r.found.forEach(function (p) { p.on = !p.dupe; });           // ones already there start unticked
            self.preview = r && r.ok ? r : { found: [], error: r && r.error };
          });
        },
        ticked: function () { return this.preview ? this.preview.found.filter(function (p) { return p.on; }).length : 0; },
        tickAll: function (on) { this.preview.found.forEach(function (p) { p.on = on; }); },
        addMany: function () {
          var self = this, pick = [];
          if (!this.paste.trim()) { toast(t("pasteFirst"), "warn"); return; }
          if (this.preview) this.preview.found.forEach(function (p, i) { if (p.on) pick.push(i); });
          if (!pick.length) return;
          api(D.api, { action: "add_many", text: this.paste, chapter: this.pasteChapter, pick: pick.join(",") }).then(function (r) {
            if (!r.ok || !r.notes) return;
            r.notes.forEach(function (n) { self.notes.push(n); });
            self.renumber(); self.paste = ""; self.preview = null; self.many = false;
            toast(r.message, "good");
          });
        },
        openFile: function (file) {
          var self = this;
          readFile(file).then(function (text) { self.many = true; self.paste = text; }, function () { toast(t("notSaved"), "warn"); });
        },
        dropFile: function (e) {
          var f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
          if (f && (/^text\//.test(f.type) || /\.(md|markdown|txt|csv|tsv)$/i.test(f.name))) { e.preventDefault(); this.openFile(f); }
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
          this.editFrom = JSON.stringify(this.edit); this.writeView.edit = false;
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
            q.question = e.question.trim(); q.answer = e.answer; self.open[q.id] = true;
            var chapter = (e.chapter || "").trim();
            if (chapter !== q.chapter) {                         // into another chapter: at its end
              var groups = self.groups(), from = groups.filter(function (g) { return g.chapter === q.chapter; })[0];
              from.notes.splice(from.notes.indexOf(q), 1);
              var to = groups.filter(function (g) { return g.chapter === chapter; })[0];
              if (to) to.notes.push(q); else groups.push({ chapter: chapter, notes: [q] });
              self.flatten(groups.filter(function (g) { return g.notes.length; })); self.saveOrder();
            }
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
        /* picking several */
        startSelect: function () { this.selecting = true; this.picked = {}; this.editing = null; },
        endSelect: function () { this.selecting = false; this.picked = {}; },
        pick: function (q) { this.picked[q.id] = !this.picked[q.id]; },
        pickedIds: function () { var self = this; return this.notes.filter(function (q) { return self.picked[q.id]; }).map(function (q) { return q.id; }); },
        pickedText: function () { return t("picked").replace("%(n)s", this.pickedIds().length); },
        pickAll: function () {
          var self = this, all = this.notes.filter(function (q) { return self.visible(q); }), on = !all.every(function (q) { return self.picked[q.id]; });
          all.forEach(function (q) { self.picked[q.id] = on; });
        },
        bulk: function (op) {
          var self = this, ids = this.pickedIds(), fields = { action: "bulk", op: op, ids: ids.join(",") };
          if (!ids.length) return;
          if (op === "delete" && !confirm(t("bulkDeleteAsk"))) return;
          if (op === "chapter") { var name = prompt(t("chapterAsk"), ""); if (name === null) return; fields.chapter = name.trim(); }
          if (op === "move") { if (!this.moveTo) return; fields.subject = this.moveTo; }
          api(D.api, fields).then(function (r) {
            if (!r.ok) return;
            var picked = self.notes.filter(function (q) { return ids.indexOf(q.id) >= 0; });
            if (op === "delete" || op === "move") {
              picked.forEach(function (q) { self.notes.splice(self.notes.indexOf(q), 1); });
              self.renumber(); self.endSelect();
              if (op === "move") { toast(r.message, "good"); self.moveTo = ""; return; }
              Work.toast(t("deletedMany").replace("%(n)s", ids.length), "good", { label: t("undo", "Undo"), run: function () {
                Promise.all((r.undo || []).map(function (u) { return Work.api(u, {}); })).then(function () { location.reload(); });
              } });
              return;
            }
            if (op === "known" || op === "unknown") picked.forEach(function (q) { q.known = op === "known"; });
            if (op === "chapter") {
              var groups = self.groups().map(function (g) { return { chapter: g.chapter, notes: g.notes.filter(function (q) { return picked.indexOf(q) < 0; }) }; });
              var to = groups.filter(function (g) { return g.chapter === fields.chapter; })[0];
              if (to) to.notes = to.notes.concat(picked); else groups.push({ chapter: fields.chapter, notes: picked });
              self.flatten(groups.filter(function (g) { return g.notes.length; })); self.saveOrder();
            }
            self.endSelect();
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
        printAll: function (questionsOnly) {
          var self = this;
          d.body.classList.toggle("wex-print-quiz", !!questionsOnly);
          this.openAll = !questionsOnly; this.folded = {};
          this.$nextTick(function () { setTimeout(function () { window.print(); d.body.classList.remove("wex-print-quiz"); }, 300); });
        },
      };
    });

    /* ── one page to read everything through before the exam ── */
    Alpine.data("examOverview", function () {
      var D = data("exam-data"), KEEP = "exam-overview-" + D.subject, kept = recall(KEEP, {}) || {};
      return {
        notes: D.notes || [], show: kept.show || "all", answers: kept.answers !== false, size: kept.size || 1,
        find: "", searching: false, open: {}, full: {}, long: {}, current: 0, scrolled: false,
        t: t,
        init: function () {
          var self = this, timer = null;
          ["show", "answers", "size"].forEach(function (k) { self.$watch(k, function () { self.keep(); }); });
          window.addEventListener("scroll", function () {
            self.scrolled = window.scrollY > 600;
            clearTimeout(timer);
            timer = setTimeout(function () { self.keep(); self.whereAmI(); }, 150);
          }, { passive: true });
          if (kept.y) this.$nextTick(function () { setTimeout(function () { window.scrollTo(0, kept.y); }, 120); });   // back where you were reading
        },
        keep: function () { store(KEEP, { show: this.show, answers: this.answers, size: this.size, y: Math.round(window.scrollY) }); },
        paint: function (el, text, q) {
          if (el._md !== text) { el._md = text; paint(el, text); }
          if (q && !this.full[q.id]) {
            var self = this;
            requestAnimationFrame(function () { if (el.clientHeight) self.long[q.id] = el.scrollHeight > el.clientHeight + 4; });      // trimmed: offer "Show all"
          }
        },
        known: function () { return this.notes.filter(function (q) { return q.known; }).length; },
        pct: function () { return this.notes.length ? Math.round(100 * this.known() / this.notes.length) : 0; },
        groups: function () {
          var by = {}, keys = [];
          this.notes.forEach(function (q) { if (!by[q.chapter]) { by[q.chapter] = []; keys.push(q.chapter); } by[q.chapter].push(q); });
          return keys.map(function (k) { return { chapter: k, notes: by[k] }; });
        },
        matches: function (q, show) {
          if (show === "unknown" && q.known) return false;
          if (show === "starred" && !q.starred) return false;
          if (show === "missed" && !q.misses) return false;
          return true;
        },
        visible: function (q) {
          if (!this.matches(q, this.show)) return false;
          var f = this.find.trim().toLowerCase();
          return !f || (q.question + "\n" + q.answer).toLowerCase().indexOf(f) >= 0;
        },
        count: function (show) { var self = this; return this.notes.filter(function (q) { return self.matches(q, show); }).length; },
        shown: function (g) { var self = this; return g.notes.some(function (q) { return self.visible(q); }); },
        knownIn: function (g) { return g.notes.filter(function (q) { return q.known; }).length; },
        setShow: function (show) { this.show = show; window.scrollTo({ top: 0 }); },
        reveal: function (q) { if (!this.answers) this.open[q.id] = !this.open[q.id]; },
        zoom: function (step) { this.size = Math.round(Math.min(1.4, Math.max(0.85, this.size + step * 0.1)) * 100) / 100; },
        toggleSearch: function () {
          var self = this;
          this.searching = !this.searching;
          if (!this.searching) { this.find = ""; return; }
          this.$nextTick(function () { self.$refs.find && self.$refs.find.focus(); });
        },
        barHeight: function () { var bar = this.$root.querySelector(".wexo-nav"); return bar ? bar.getBoundingClientRect().height : 0; },
        jump: function (gi) {
          var el = d.getElementById("chapter-" + gi);
          if (!el) return;
          window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - stickyTop() - this.barHeight() - 8, behavior: "smooth" });
        },
        whereAmI: function () {           // the chapter being read, lit up in the chapter row
          var line = stickyTop() + this.barHeight() + 24, at = 0;
          this.$root.querySelectorAll(".wexo-group").forEach(function (el) { if (el.offsetParent && el.getBoundingClientRect().top < line) at = +el.dataset.index; });
          this.current = at;
          var chip = this.$root.querySelectorAll(".wexo-chap")[at];
          if (chip && chip.scrollIntoView) chip.scrollIntoView({ inline: "nearest", block: "nearest" });
        },
        flag: function (q, what) {
          var key = what === "star" ? "starred" : "known";
          q[key] = !q[key];
          api(D.noteBase + q.id + "/", { action: what, value: q[key] ? "1" : "0" }).then(function (r) { if (!r.ok && !r.queued) q[key] = !q[key]; });
        },
        reviewUrl: function () { return D.review + "?which=" + (this.show === "unknown" ? "unknown" : this.show); },
        printIt: function () {
          var self = this;
          this.answers = true;
          this.notes.forEach(function (q) { self.full[q.id] = true; });
          this.$nextTick(function () { setTimeout(function () { window.print(); }, 300); });
        },
        key: function (e) {
          if (e.ctrlKey || e.metaKey || e.altKey || typing(e)) return;
          if (e.key === "/") { e.preventDefault(); if (!this.searching) this.toggleSearch(); else this.$refs.find.focus(); }
          else if (e.defaultPrevented) return;
          else if (e.key === "a") { e.preventDefault(); this.answers = !this.answers; }
        },
      };
    });

    /* ── flip through them ── */
    Alpine.data("examReview", function () {
      var D = data("exam-data");
      return {
        all: D.notes || [], chapters: D.chapters || [], chapter: D.chapter || "", which: D.which || "unknown", back: D.back,
        shuffle: D.shuffle || !!recall("exam-shuffle", false), writeFirst: !!recall("exam-write-first", false), mine: "",
        queue: [], pos: 0, card: null, flipped: false, stage: "card", editing: false, draft: {}, history: [],
        seen: 0, firstTry: 0, missed: [], started: 0, took: "", swipe: null, swiped: 0,
        init: function () {
          var self = this;
          this.$watch("shuffle", function (v) { store("exam-shuffle", v || null); });
          this.$watch("writeFirst", function (v) { store("exam-write-first", v || null); });
          this.start(this.which);
        },
        start: function (which, only) {
          var chapter = this.chapter;
          this.which = which;
          var list = only ? only.slice() : this.all.filter(function (q) {
            if (chapter && q.chapter !== chapter) return false;
            return which === "all" || (which === "starred" ? q.starred : which === "missed" ? q.misses > 0 : !q.known);
          });
          if (this.shuffle) {
            for (var i = list.length - 1; i > 0; i--) { var j = Math.floor(Math.random() * (i + 1)), x = list[i]; list[i] = list[j]; list[j] = x; }
          } else if (which === "missed") {
            list.sort(function (a, b) { return b.misses - a.misses || a.number - b.number; });       // the most missed first
          }
          this.queue = list.slice(); this.pos = 0; this.seen = list.length; this.firstTry = 0; this.missed = []; this.history = [];
          this.started = Date.now();
          if (!list.length) { this.stage = "empty"; return; }
          this.stage = "card"; this.showCard();
        },
        againMissed: function () { this.start(this.which, this.missed); },
        showCard: function () {
          var self = this;
          this.card = this.queue[this.pos]; this.flipped = false; this.mine = "";
          this.$nextTick(function () {
            paint(self.$refs.front, self.card.question); paint(self.$refs.q, self.card.question); paint(self.$refs.back, self.card.answer || t("noAnswer"));
            if (self.writeFirst && self.$refs.mine) self.$refs.mine.focus();
          });
        },
        leftText: function () {
          var n = this.queue.length - this.pos;
          return n === 1 ? t("leftOne", "1 question left") : t("left", "%(n)s questions left").replace("%(n)s", n);
        },
        flip: function () { if (this.stage === "card") this.flipped = !this.flipped; },
        mark: function (knew) {
          var q = this.card;
          if (!q || !this.flipped) return;
          this.history.push({ q: q, knew: knew, known: q.known, misses: q.misses, firstTry: this.firstTry, missed: this.missed.slice() });
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
        undo: function () {
          var h = this.history.pop();
          if (!h) return;
          if (!h.knew) this.queue.pop();
          h.q.known = h.known; h.q.misses = h.misses; this.firstTry = h.firstTry; this.missed = h.missed;
          api(D.noteBase + h.q.id + "/", { action: "unreview", known: h.known ? "1" : "0", misses: String(h.misses) });
          this.pos--; this.stage = "card"; this.showCard(); this.flipped = true;
        },
        /* swipe the turned card: right — knew it, left — not yet */
        down: function (e) { if (this.flipped && e.pointerType !== "mouse") this.swipe = { x: e.clientX, y: e.clientY, dx: 0 }; },
        move: function (e) {
          if (!this.swipe) return;
          this.swipe.dx = e.clientX - this.swipe.x;
          if (Math.abs(e.clientY - this.swipe.y) > Math.abs(this.swipe.dx) + 10) { this.swipe = null; return; }   // scrolling, not swiping
        },
        up: function () {
          var s = this.swipe; this.swipe = null;
          if (s && Math.abs(s.dx) > 90) { this.swiped = Date.now(); this.mark(s.dx > 0); }      // the tap that ends a swipe doesn't turn the next card
        },
        swipeStyle: function () { return this.swipe ? "transform: translateX(" + this.swipe.dx + "px) rotate(" + this.swipe.dx / 25 + "deg); --swipe:" + Math.max(-1, Math.min(1, this.swipe.dx / 120)) : ""; },
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
          if (this.editing || e.ctrlKey || e.metaKey || e.altKey) return;
          if (typing(e)) {                // writing your own answer first: Shift+Enter turns the card over
            if (e.key === "Enter" && e.shiftKey && e.target === this.$refs.mine) { e.preventDefault(); this.flipped = true; }
            return;
          }
          if (e.key === "Escape") { location.href = this.back; return; }
          if ((e.key === "z" || e.key === "Z") && this.history.length) { e.preventDefault(); this.undo(); return; }
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
