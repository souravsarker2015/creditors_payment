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
    /* ── pages of questions from the server: shared by the board and the overview ── */
    function pager(D) {
      return {
        notes: [], next: 1, loading: false, query: "", show: "all", chapter: null, sort: "order",
        shows: D.shows || { all: 0, unknown: 0, missed: 0, starred: 0 }, chapters: D.chapters || [],
        params: function (page) {
          var p = new URLSearchParams({ show: this.show, sort: this.sort, page: page });
          if (this.chapter !== null) p.set("chapter", this.chapter);
          if (this.query.trim()) p.set("q", this.query.trim());
          if (this.pinnedFirst && this.pinnedFirst()) p.set("pinned", "1");
          return p.toString();
        },
        load: function () {
          var self = this, page = this.next;
          if (this.loading || !page) return Promise.resolve();
          this.loading = true;
          var asked = this.params(page);
          return fetch(D.notes + "?" + asked, { credentials: "same-origin", headers: { "X-Requested-With": "fetch" } })
            .then(function (r) { return r.json(); })
            .then(function (r) {
              if (self.params(page) !== asked) return;            // the filters changed meanwhile: a newer load follows
              if (page === 1) { self.notes = []; if (r.shows) { self.shows = r.shows; self.chapters = r.chapters; } }
              r.notes.forEach(function (n) { self.notes.push(n); });
              self.next = r.next;
              self.$nextTick(function () { if (self.loaded) self.loaded(); self.more(); });
            })
            .catch(function () { toast(t("notSaved"), "warn"); })
            .then(function () { self.loading = false; });
        },
        reload: function () { this.next = 1; this.loading = false; return this.load(); },
        more: function () {            // the end of the list is in view: the next page (the observer only fires on changes)
          var el = this.$refs.more;
          if (el && this.next && !this.loading && el.getBoundingClientRect().top < window.innerHeight + 700) this.load();
        },
        watchEnd: function () {
          var self = this;
          if ("IntersectionObserver" in window && this.$refs.more) {
            new IntersectionObserver(function (es) { if (es.some(function (e) { return e.isIntersecting; })) self.load(); }, { rootMargin: "0px 0px 700px 0px" }).observe(this.$refs.more);
          }
        },
        updateCounts: function (r) { if (r && r.shows) { this.shows = r.shows; this.chapters = r.chapters; } },
        setShow: function (show) { this.show = show; this.reload(); },
        setChapter: function (name) { this.chapter = name; this.reload(); },
        pct: function () { return this.shows.all ? Math.round(100 * (this.shows.all - this.shows.unknown) / this.shows.all) : 0; },
        flag: function (q, what) {
          var self = this, key = what === "star" ? "starred" : "known";
          q[key] = !q[key];
          api(D.noteBase + q.id + "/", { action: what, value: q[key] ? "1" : "0" }).then(function (r) {
            if (!r.ok && !r.queued) { q[key] = !q[key]; return; }
            self.shows[key === "starred" ? "starred" : "unknown"] += (key === "starred") === q[key] ? 1 : -1;
          });
        },
      };
    }

    /* ── a subject's board: cards like Google Keep, a page at a time ── */
    Alpine.data("examBoard", function () {
      var D = data("exam-data"), DRAFT = "exam-draft-" + D.subject, PREFS = "exam-board", prefs = recall(PREFS, {}) || {};
      function blank(keep) { return { question: "", answer: "", chapter: keep ? keep.chapter : "", color: "", starred: false }; }      // the label stays for the next one
      return Object.assign(pager(D), {
        D: D, t: t, answers: prefs.answers !== false, composing: false, many: false, draft: blank(), writeView: { add: false, edit: false },
        paste: "", pasteChapter: "", preview: null, checking: false, previewTimer: null,
        selecting: false, picked: {}, moveTo: "", editing: null, edit: {}, editFrom: "", labelsOpen: false,
        init: function () {
          var self = this;
          if (prefs.sort === "new") this.sort = "new";
          var saved = recall(DRAFT, null);                       // a question that wasn't added last time
          if (saved && (saved.question || saved.answer || saved.paste)) {
            this.draft = Object.assign(blank(), saved); this.paste = saved.paste || "";
            this.composing = true; this.many = !!saved.paste && !saved.question;
            toast(t("draftBack"), "good");
          }
          this.$watch("draft", function () { self.keepDraft(); }, { deep: true });
          this.$watch("paste", function () { self.keepDraft(); self.schedulePreview(); });
          this.$watch("pasteChapter", function () { if (self.paste.trim()) self.schedulePreview(); });
          this.$watch("answers", function () { self.keepPrefs(); });
          this.$watch("sort", function () { self.keepPrefs(); });
          window.addEventListener("beforeunload", function (e) {
            if (self.editing && JSON.stringify(self.edit) !== self.editFrom) { e.preventDefault(); e.returnValue = t("leave"); }
          });
          if (!this.shows.all) this.composing = true;
          this.watchEnd();
          this.load();
        },
        keepPrefs: function () { store(PREFS, { answers: this.answers, sort: this.sort }); },
        keepDraft: function () {
          var x = this.draft, has = x.question.trim() || x.answer.trim() || this.paste.trim();
          store(DRAFT, has ? Object.assign({}, x, { paste: this.paste }) : null);
        },
        paint: function (el, text) { if (el._md !== text) { el._md = text; paint(el, text); } },
        countText: function () { var n = this.shows.all; return t(n === 1 ? "countOne" : "count").replace("%(counter)s", n); },
        pace: function () {
          var left = this.shows.unknown;
          if (!this.shows.all) return "";
          if (!left) return t("allKnown");
          if (D.daysLeft === null || D.daysLeft === undefined || D.daysLeft < 1) return "";
          return t("perDay").replace("%(n)s", Math.ceil(left / D.daysLeft));
        },
        pinnedFirst: function () { return this.sort === "order" && this.show === "all" && this.chapter === null && !this.query.trim(); },
        firstOther: function (i) { return this.pinnedFirst() && i > 0 && this.notes[i - 1].starred && !this.notes[i].starred; },
        firstPinned: function (i) { return this.pinnedFirst() && i === 0 && this.notes[0].starred; },
        canDrag: function () { return this.pinnedFirst() && !this.selecting; },
        loaded: function () { this.sortable(); },
        sortable: function () {
          if (!window.Sortable) { var self0 = this; setTimeout(function () { self0.sortable(); }, 150); return; }
          var self = this, grid = this.$refs.grid;
          if (!grid || grid._sortable) return;
          function start(evt) { evt.item.setAttribute("x-ignore", ""); }
          function done(evt) { evt.item.removeAttribute("x-ignore"); delete evt.item._x_ignore; }
          grid._sortable = Sortable.create(grid, {
            handle: ".wkc-grip", draggable: ".wkc", animation: 150, forceFallback: true, fallbackOnBody: true, onChoose: start, onUnchoose: done,
            onEnd: function (evt) {
              done(evt);
              if (evt.oldDraggableIndex === evt.newDraggableIndex) return;
              var moved = self.notes[evt.oldDraggableIndex];
              evt.item.remove();      // put the card back: Alpine draws the new order from the data
              grid.insertBefore(evt.item, grid.querySelectorAll(":scope > .wkc")[evt.oldDraggableIndex] || null);
              self.notes.splice(evt.oldDraggableIndex, 1);
              self.notes.splice(evt.newDraggableIndex, 0, moved);
              var before = self.notes[evt.newDraggableIndex + 1];
              api(D.api, { action: "move", id: moved.id, before: before ? before.id : "" }).then(function (r) {
                if (!r.ok) return;
                moved.chapter = r.chapter; self.updateCounts(r);
              });
            },
          });
        },
        /* taking a note */
        openComposer: function (many) {
          var self = this;
          this.composing = true; this.many = many;
          this.$nextTick(function () { var box = many ? self.$root.querySelector(".wex-paste") : self.$refs.question; if (box) box.focus(); });
        },
        closeComposer: function () {
          if (!this.many && this.draft.question.trim()) { this.add(false); return; }     // like Keep: closing keeps what was written
          this.composing = !this.shows.all; this.many = false; this.writeView.add = false;
        },
        add: function (keepOpen) {
          var self = this, x = this.draft;
          if (!x.question.trim()) { toast(t("writeFirst"), "warn"); return; }
          api(D.api, { action: "add", question: x.question.trim(), answer: x.answer, chapter: x.chapter, color: x.color, starred: x.starred ? "1" : "0" }).then(function (r) {
            if (!r.ok || !r.note) return;
            r.note._new = true;
            self.notes.splice(r.note.starred || !self.pinnedFirst() ? 0 : self.notes.filter(function (n) { return n.starred; }).length, 0, r.note);
            self.updateCounts(r);
            self.draft = blank(x); self.writeView.add = false;
            toast(t("added", "Added") + (r.note.number ? " · #" + r.note.number : ""), "good");
            if (keepOpen) self.$nextTick(function () { self.$refs.question && self.$refs.question.focus(); });
            else self.composing = false;
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
            if (text !== self.paste) return;
            if (r && r.ok) r.found.forEach(function (p) { p.on = !p.dupe; });
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
            self.paste = ""; self.preview = null; self.many = false; self.composing = false;
            toast(r.message, "good");
            self.reload();
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
        /* one card */
        cardClick: function (e, q) {
          if (this.selecting) { this.picked[q.id] = !this.picked[q.id]; return; }
          if (e.target.closest("a, button, input, select, textarea, .wkc-colors")) return;
          this.openEditor(q);
        },
        setColor: function (q, color) {
          var was = q.color; q.color = color;
          api(D.noteBase + q.id + "/", { action: "color", color: color }).then(function (r) { if (!r.ok && !r.queued) q.color = was; });
        },
        openEditor: function (q) {
          this.edit = { id: q.id, question: q.question, answer: q.answer, chapter: q.chapter, color: q.color || "", starred: q.starred, known: q.known, number: q.number, subject: D.subject };
          this.editFrom = JSON.stringify(this.edit); this.editing = q; this.writeView.edit = false;
          var self = this; this.$nextTick(function () { self.$refs.editQuestion && self.$refs.editQuestion.focus(); });
        },
        closeEditor: function () {
          var self = this, q = this.editing, e = this.edit;
          if (!q) return;
          if (JSON.stringify(e) === this.editFrom) { this.editing = null; return; }
          if (!e.question.trim()) { toast(t("writeFirst"), "warn"); return; }
          var was = JSON.parse(this.editFrom);
          api(D.noteBase + q.id + "/", { action: "update", question: e.question, answer: e.answer, chapter: e.chapter, color: e.color, subject: e.subject }).then(function (r) {
            if (!r.ok && !r.queued) return;
            if (String(e.subject) !== String(D.subject)) {           // moved to another subject
              self.notes.splice(self.notes.indexOf(q), 1);
              var to = D.subjects.find(function (s) { return String(s.id) === String(e.subject); });
              toast(t("moved").replace("%(name)s", to ? to.name : ""), "good");
              self.reload();
              return;
            }
            q.question = e.question.trim(); q.answer = e.answer; q.chapter = (e.chapter || "").trim(); q.color = e.color;
            if (r.note && r.note.chapter !== was.chapter) self.reload();
          });
          if (e.starred !== was.starred) this.flag(q, "star");
          if (e.known !== was.known) this.flag(q, "known");
          this.editing = null;
        },
        removeEditing: function () { var q = this.editing; this.editing = null; this.remove(q); },
        remove: function (q) {
          var self = this;
          api(D.noteBase + q.id + "/", { action: "delete" }).then(function (r) {
            if (!r.ok) return;
            self.notes.splice(self.notes.indexOf(q), 1);
            self.shows.all--; if (!q.known) self.shows.unknown--; if (q.starred) self.shows.starred--; if (q.misses) self.shows.missed--;
            Work.undoable(t("deleted", "Question deleted"), r.undo, function () { self.reload(); });
          });
        },
        /* picking several */
        startSelect: function () { this.selecting = true; this.picked = {}; },
        endSelect: function () { this.selecting = false; this.picked = {}; },
        pickedIds: function () { var self = this; return this.notes.filter(function (q) { return self.picked[q.id]; }).map(function (q) { return q.id; }); },
        pickedText: function () { return t("picked").replace("%(n)s", this.pickedIds().length); },
        pickAll: function () {
          var self = this, on = !this.notes.every(function (q) { return self.picked[q.id]; });
          this.notes.forEach(function (q) { self.picked[q.id] = on; });
        },
        bulk: function (op) {
          var self = this, ids = this.pickedIds(), fields = { action: "bulk", op: op, ids: ids.join(",") };
          if (!ids.length) return;
          if (op === "delete" && !confirm(t("bulkDeleteAsk"))) return;
          if (op === "chapter") { var name = prompt(t("chapterAsk"), ""); if (name === null) return; fields.chapter = name.trim(); }
          if (op === "move") { if (!this.moveTo) return; fields.subject = this.moveTo; }
          api(D.api, fields).then(function (r) {
            if (!r.ok) return;
            self.endSelect(); self.moveTo = "";
            if (op === "move") toast(r.message, "good");
            if (op === "delete") {
              Work.toast(t("deletedMany").replace("%(n)s", ids.length), "good", { label: t("undo", "Undo"), run: function () {
                Promise.all((r.undo || []).map(function (u) { return Work.api(u, {}); })).then(function () { self.reload(); });
              } });
            }
            self.reload();
          });
        },
        /* labels (chapters) */
        renameChapter: function (c) {
          var self = this, name = prompt(t("renameAsk"), c.name);
          if (name === null || name.trim() === c.name) return;
          api(D.api, { action: "rename_chapter", old: c.name, chapter: name.trim() }).then(function (r) { if (r.ok) self.reload(); });
        },
        moveChapter: function (i, step) {
          var self = this, c = this.chapters[i];
          api(D.api, { action: "chapter_move", chapter: c.name, step: step }).then(function (r) { if (r.ok) { self.updateCounts(r); self.reload(); } });
        },
        reset: function () {
          var self = this;
          if (!confirm(t("resetAsk"))) return;
          api(D.api, { action: "reset" }).then(function (r) { if (r.ok) self.reload(); });
        },
        key: function (e) {
          if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey || typing(e) || this.editing) return;
          if (e.key === "c" || e.key === "a") { e.preventDefault(); this.openComposer(false); }
          else if (e.key === "r" && this.shows.all) { e.preventDefault(); location.href = D.review; }
          else if (e.key === "o" && this.shows.all) { e.preventDefault(); location.href = D.overview; }
          else if (e.key === "Escape" && this.selecting) this.endSelect();
        },
      });
    });

    /* ── one page to read everything through before the exam (a page at a time) ── */
    Alpine.data("examOverview", function () {
      var D = data("exam-data"), KEEP = "exam-overview-" + D.subject, kept = recall(KEEP, {}) || {};
      return Object.assign(pager(D), {
        D: D, t: t, answers: kept.answers !== false, size: kept.size || 1,
        searching: false, open: {}, full: {}, long: {}, scrolled: false,
        init: function () {
          var self = this;
          if (["all", "unknown", "missed", "starred"].indexOf(kept.show) >= 0) this.show = kept.show;
          ["show", "answers", "size"].forEach(function (k) { self.$watch(k, function () { self.keep(); }); });
          window.addEventListener("scroll", function () { self.scrolled = window.scrollY > 600; }, { passive: true });
          this.watchEnd();
          this.load();
        },
        keep: function () { store(KEEP, { show: this.show, answers: this.answers, size: this.size }); },
        paint: function (el, text, q) {
          if (el._md !== text) { el._md = text; paint(el, text); }
          if (q && !this.full[q.id]) {
            var self = this;
            requestAnimationFrame(function () { if (el.clientHeight) self.long[q.id] = el.scrollHeight > el.clientHeight + 4; });      // trimmed: offer "Show all"
          }
        },
        known: function () { return this.shows.all - this.shows.unknown; },
        heading: function (i) { return i === 0 || this.notes[i - 1].chapter !== this.notes[i].chapter; },     // a chapter starts here
        count: function (show) { return this.shows[show] || 0; },
        reveal: function (q) { if (!this.answers) this.open[q.id] = !this.open[q.id]; },
        zoom: function (step) { this.size = Math.round(Math.min(1.4, Math.max(0.85, this.size + step * 0.1)) * 100) / 100; },
        toggleSearch: function () {
          var self = this;
          this.searching = !this.searching;
          if (!this.searching) { if (this.query) { this.query = ""; this.reload(); } return; }
          this.$nextTick(function () { self.$refs.find && self.$refs.find.focus(); });
        },
        reviewUrl: function () { return D.review + "?which=" + this.show + (this.chapter !== null ? "&chapter=" + encodeURIComponent(this.chapter) : ""); },
        printIt: function () {
          var self = this;
          this.answers = true;
          (function all() {          // every page first, then print
            if (self.next) { self.load().then(all); return; }
            self.notes.forEach(function (q) { self.full[q.id] = true; });
            self.$nextTick(function () { setTimeout(function () { window.print(); }, 400); });
          })();
        },
        key: function (e) {
          if (e.ctrlKey || e.metaKey || e.altKey || typing(e)) return;
          if (e.key === "/") { e.preventDefault(); if (!this.searching) this.toggleSearch(); else this.$refs.find.focus(); }
          else if (e.defaultPrevented) return;
          else if (e.key === "a") { e.preventDefault(); this.answers = !this.answers; }
        },
      });
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
