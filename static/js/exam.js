/* Exam notes (Productivity): a subject's questions and answers — added one by
   one or pasted as a list (with a preview first), edited, starred, moved and
   deleted in place, chapter by chapter — and flipping through them one at a
   time. Loaded after work.js on those pages.

   Answers are Markdown: lists, tables, code, ```mermaid diagrams, pictures,
   and formulas ($…$, $$…$$, \(…\), \[…\] — what ChatGPT and Claude write).
   Pasting a ChatGPT or Claude reply that was copied as formatted text turns
   it back into Markdown (static/js/writing.js, for every Markdown box).

   On the subject's page questions are dragged into order (and into another
   chapter), picked to be changed together, and a question being written is
   kept in the browser as a draft until it's added.

   Review: the question first (optionally: write your answer first); think of
   the answer, turn the card over, then "I knew it" (marked as known) or "Not
   yet" (it comes back at the end of the round, is marked as not known, and
   counts as missed once more). Swipe right / left on a phone; Z undoes.

   A question being edited is saved as you type and kept on this device until the
   server has it. With no signal the board and the overview read the subject from
   the review page kept on the phone (it holds every question). */
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

  function paint(el, text) {
    if (!el) return;
    el.innerHTML = Work.markdown(text || "");     // (with formulas: work.js)
    if (window.Work && Work.mermaidIn) Work.mermaidIn(el);
    if (window.hljs) el.querySelectorAll("pre code:not(.language-mermaid)").forEach(function (c) { hljs.highlightElement(c); });
  }

  /* (A ChatGPT / Claude reply pasted as formatted text comes in as Markdown: static/js/writing.js) */

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
        notes: [], next: 1, loading: false, query: "", show: "all", chapter: null, sort: "order", kept: null,
        shows: D.shows || { all: 0, unknown: 0, missed: 0, starred: 0 }, chapters: D.chapters || [],
        cats: D.categories || [], catN: D.categoryN || {}, category: null, catOpen: false, catMode: "pick", catList: [], catThen: null,
        catQuery: "", catShut: {}, catManage: false, catUnder: null, catNewName: "", catEdit: null,
        params: function (page) {
          var p = new URLSearchParams({ show: this.show, sort: this.sort, page: page });
          if (this.chapter !== null) p.set("chapter", this.chapter);
          if (this.category !== null) p.set("category", this.category);
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
              if (page === 1) { self.notes = []; self.updateCounts(r); }
              // (a card that moved — starred, or added — may come again on the next page: it's there once)
              var have = {}; self.notes.forEach(function (n) { have[n.id] = true; });
              r.notes.forEach(function (n) { if (!have[n.id]) self.notes.push(n); });
              self.next = r.next;
              self.$nextTick(function () { if (self.loaded) self.loaded(); self.more(); });
              if (page === 1) self.keepForOffline();
            })
            .catch(function () { return self.fromPhone(); })
            .then(function () { self.loading = false; });
        },
        /* the review page, kept on the phone (an hour old at most, while online): what this page shows with no signal */
        keepForOffline: function () {
          var key = "exam-kept-" + D.subject;
          if (!navigator.serviceWorker || !navigator.serviceWorker.controller || Date.now() - (recall(key, 0) || 0) < 3600000) return;
          store(key, Date.now());
          fetch(D.review, { credentials: "same-origin", headers: { "X-FT-Keep": "1" } }).catch(function () {});
        },
        fromPhone: function () {
          var self = this, got = this.kept ? Promise.resolve(this.kept) : fetch(D.review, { credentials: "same-origin", headers: { "X-FT-Keep": "1" } })
            .then(function (r) { return r.text(); })
            .then(function (html) { return JSON.parse(new DOMParser().parseFromString(html, "text/html").getElementById("exam-data").textContent).notes; });
          return got.then(function (all) {
            var words = self.query.toLowerCase().split(/\s+/).filter(Boolean), chapters = [], by = {}, shows = { all: all.length, unknown: 0, due: 0, missed: 0, starred: 0 };
            var inBranch = self.category === null || self.category === "none" ? null : self.catBranch(self.category), catN = { none: 0 };
            self.kept = all;
            all.forEach(function (n) {
              if (!(n.categories || []).length) catN.none++;
              self.catUp(n.categories || []).forEach(function (id) { catN[id] = (catN[id] || 0) + 1; });
              shows.unknown += n.known ? 0 : 1; shows.due += n.due ? 1 : 0; shows.missed += n.misses ? 1 : 0; shows.starred += n.starred ? 1 : 0;
              if (!by[n.chapter]) { by[n.chapter] = { name: n.chapter, n: 0, known: 0 }; chapters.push(by[n.chapter]); }
              by[n.chapter].n++; by[n.chapter].known += n.known ? 1 : 0;
            });
            self.shows = shows; self.chapters = chapters; self.catN = catN; self.next = null;
            self.notes = all.filter(function (n) {
              var text = (n.question + " " + n.answer + " " + n.chapter).toLowerCase();
              var mine = n.categories || [];
              return (self.chapter === null || n.chapter === self.chapter)
                && (self.category === null || (inBranch ? mine.some(function (id) { return inBranch[id]; }) : !mine.length))
                && (self.show === "all" || (self.show === "unknown" ? !n.known : self.show === "due" ? n.due : self.show === "missed" ? n.misses : n.starred))
                && words.every(function (w) { return text.indexOf(w) >= 0; });
            });
            if (self.pinnedFirst && self.pinnedFirst()) self.notes.sort(function (a, b) { return (b.starred - a.starred) || (a.number - b.number); });
            self.$nextTick(function () { if (self.loaded) self.loaded(); });
          }).catch(function () { toast(t("notHere", "This subject isn't on this device yet. Open it once with a connection."), "warn"); });
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
        updateCounts: function (r) { if (r && r.shows) { this.shows = r.shows; this.chapters = r.chapters; this.catN = r.categoryN || this.catN; } },
        setShow: function (show) { this.show = show; this.reload(); },
        setChapter: function (name) { this.chapter = name; this.reload(); },
        /* ── categories: the popup (pick any number for a question, or one to show), and the chips ── */
        setCategory: function (id) { this.category = id; this.reload(); },
        catOf: function (id) { return this.cats.find(function (c) { return c.id === id; }); },
        catChips: function (ids) { var self = this; return (ids || []).map(function (id) { return self.catOf(id); }).filter(Boolean); },
        catLabel: function () {
          if (this.category === null) return t("catAll");
          if (this.category === "none") return t("catNone");
          var c = this.catOf(this.category);
          return c ? c.name : t("catAll");
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
          fetch(D.categoriesUrl, { credentials: "same-origin", headers: { Accept: "application/json" } }).then(function (r) { return r.json(); })
            .then(function (r) { if (r.ok) self.cats = r.categories; }).catch(function () { /* no signal: the ones on this page */ });
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
          return Work.ask(D.categoriesUrl, fields).then(function (r) {
            if (!r) { toast(t("catOffline"), "warn"); return null; }
            if (!r.ok) { toast(r.error || t("notSaved"), "warn"); return null; }
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
          FT.ask({ message: t("catDeleteAsk").replace("%(name)s", c.name), danger: true, after: "back" }).then(function (sure) {
            if (!sure) return;
            self.catSend({ action: "delete", id: c.id }).then(function (r) {
              if (!r) return;
              if (self.category !== null && !self.catOf(self.category) && self.category !== "none") self.category = null;
              self.catRemove(self.catList, c.id);
              self.reload();
              Work.undoable(t("catDeleted"), r.undo, function () { self.catRefresh(); });
            });
          });
        },
        catRefresh: function () {
          var self = this;
          fetch(D.categoriesUrl, { credentials: "same-origin", headers: { Accept: "application/json" } }).then(function (r) { return r.json(); })
            .then(function (r) { if (r.ok) { self.cats = r.categories; self.reload(); } });
        },
        withCategory: function (url) {   // a review of what's being shown
          return this.category === null ? url : url + (url.indexOf("?") < 0 ? "?" : "&") + "category=" + this.category;
        },
        pct: function () { return this.shows.all ? Math.round(100 * (this.shows.all - this.shows.unknown) / this.shows.all) : 0; },
        flag: function (q, what) {
          var self = this, key = what === "star" ? "starred" : "known";
          q[key] = !q[key];
          if (key === "starred") this.restar(q);
          api(D.noteBase + q.id + "/", { action: what, value: q[key] ? "1" : "0" }).then(function (r) {
            if (!r.ok && !r.queued) { q[key] = !q[key]; if (key === "starred") self.restar(q); return; }
            self.shows[key === "starred" ? "starred" : "unknown"] += (key === "starred") === q[key] ? 1 : -1;
          });
        },
        /* Starred (pinned) or not: on the board the card moves at once — the important ones first, the rest in
           the subject's order (their numbers), as the server lists them; under "Important", an unstarred one leaves. */
        restar: function (q) {
          var self = this, grid = this.$refs.grid;
          if (!grid || !this.notes) return;
          if (this.notes.indexOf(q) < 0) return;           // (moved to another subject meanwhile)
          if (this.show === "starred" && !q.starred) {
            Work.flip(grid, function () { self.notes.splice(self.notes.indexOf(q), 1); return self.$nextTick(); });
          } else if (this.pinnedFirst && this.pinnedFirst()) {
            Work.flip(grid, function () {
              self.notes.sort(function (a, b) { return (b.starred - a.starred) || ((a.number || 1e9) - (b.number || 1e9)) || (a.id - b.id); });
              return self.$nextTick();
            });
          }
        },
      };
    }

    /* ── a subject's board: cards like Google Keep, a page at a time ── */
    Alpine.data("examBoard", function () {
      var D = data("exam-data"), DRAFT = "exam-draft-" + D.subject, EDIT = "exam-edit-" + D.subject, PREFS = "exam-board", prefs = recall(PREFS, {}) || {};
      function blank(keep) { return { question: "", answer: "", chapter: keep ? keep.chapter : "", categories: keep ? keep.categories.slice() : [], color: "", starred: false }; }      // the label and categories stay for the next one
      return Object.assign(pager(D), {
        D: D, t: t, answers: prefs.answers !== false, composing: false, many: false, draft: blank(), writeView: { add: false, edit: false },
        paste: "", pasteChapter: "", pasteCats: [], preview: null, checking: false, previewTimer: null, histOpen: false, histLoading: false, versions: [], shown: null,
        selecting: false, picked: {}, moveTo: "", editing: null, edit: {}, editFrom: "", editFirst: null, editState: "saved", editTimer: null, editSending: null, labelsOpen: false,
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
          this.$watch("edit", function () { self.editChanged(); }, { deep: true });
          document.addEventListener("work:synced", function (e) {     // written offline, and it's there now
            var q = self.notes.find(function (n) { return "exam:" + n.id === e.detail.same; });
            if (!q) return;
            q.rev = e.detail.rev || "";
            if (self.editing === q && self.editState === "offline") self.editState = "saved";
          });
          this.$watch("answers", function () { self.keepPrefs(); });
          this.$watch("sort", function () { self.keepPrefs(); });
          window.addEventListener("beforeunload", function (e) {
            if (self.editing && self.editState !== "saved") { e.preventDefault(); e.returnValue = t("leave"); }
          });
          if (!this.shows.all) this.composing = true;
          this.watchEnd();
          this.load().then(function () { self.openAsked(); });
        },
        /* ?open=N (a question found in search): its editor opens, wherever it is in the list */
        openAsked: function () {
          var url = new URL(location.href), kept = recall(EDIT, null), self = this;
          var id = +(url.searchParams.get("open") || (/^#q(\d+)$/.exec(location.hash) || [])[1] || (kept && kept.id) || 0);     // or the one that wasn't saved last time
          if (!id) return;
          url.searchParams.delete("open"); url.hash = "";
          history.replaceState(history.state, "", url.pathname + url.search);
          var here = this.notes.find(function (n) { return n.id === id; });
          if (here) return this.openEditor(here);
          fetch(D.notes + "?id=" + id, { credentials: "same-origin", headers: { "X-Requested-With": "fetch" } })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (r) {
              if (r && r.notes && r.notes[0]) self.openEditor(r.notes[0]);
              else if (kept && kept.id === id) store(EDIT, null);       // deleted since
            })
            .catch(function () {});
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
        pinnedFirst: function () { return this.sort === "order" && this.show === "all" && this.chapter === null && this.category === null && !this.query.trim(); },
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
              api(D.api, { action: "move", id: moved.id, before: before ? before.id : "", ids: self.notes.map(function (n) { return n.id; }).join(",") }).then(function (r) {
                if (!r.ok) return;
                moved.chapter = r.chapter; self.updateCounts(r);
                self.notes.forEach(function (n) { if (r.numbers && r.numbers[n.id]) n.number = r.numbers[n.id]; });
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
          api(D.api, { action: "add", question: x.question.trim(), answer: x.answer, chapter: x.chapter, categories: x.categories.join(","), color: x.color, starred: x.starred ? "1" : "0" }).then(function (r) {
            if (r.queued) { self.draft = blank(x); self.writeView.add = false; return; }        // sent when there's signal (or after signing in)
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
          Work.ask(D.api, { action: "add_many", text: text, chapter: this.pasteChapter, preview: "1" }).then(function (r) {
            self.checking = false;
            if (text !== self.paste) return;
            if (!r) { self.preview = null; return; }           // no connection: no preview, and it can be added all the same
            if (r && r.ok) r.found.forEach(function (p) { p.on = !p.dupe; });
            self.preview = r && r.ok ? r : { found: [], error: r && r.error };
          });
        },
        ticked: function () { return this.preview ? this.preview.found.filter(function (p) { return p.on; }).length : 0; },
        tickAll: function (on) { this.preview.found.forEach(function (p) { p.on = on; }); },
        addMany: function () {
          var self = this, pick = [];
          if (!this.paste.trim()) { toast(t("pasteFirst"), "warn"); return; }
          var fields = { action: "add_many", text: this.paste, chapter: this.pasteChapter, categories: this.pasteCats.join(",") };
          if (this.preview) {
            this.preview.found.forEach(function (p, i) { if (p.on) pick.push(i); });
            if (!pick.length) return;
            fields.pick = pick.join(",");
          }
          api(D.api, fields).then(function (r) {
            if (r.queued) { self.paste = ""; self.pasteCats = []; self.preview = null; self.many = false; self.composing = false; return; }
            if (!r.ok || !r.notes) return;
            self.paste = ""; self.pasteCats = []; self.preview = null; self.many = false; self.composing = false;
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
          this.edit = { id: q.id, question: q.question, answer: q.answer, chapter: q.chapter, categories: (q.categories || []).slice(), color: q.color || "", starred: q.starred, known: q.known, number: q.number, subject: D.subject };
          this.editFrom = JSON.stringify(this.edit); this.editFirst = JSON.parse(this.editFrom); this.editing = q; this.writeView.edit = false; this.editState = "saved";
          var kept = recall(EDIT, null);                  // what wasn't saved last time comes back
          if (kept && kept.id === q.id) {
            this.edit.question = kept.question; this.edit.answer = kept.answer; this.edit.chapter = kept.chapter; this.edit.color = kept.color;
            this.edit.categories = kept.categories || this.edit.categories;
            toast(t("draftBack"), "good");
          }
          var self = this; this.$nextTick(function () { self.$refs.editQuestion && self.$refs.editQuestion.focus(); });
        },
        /* saved as you type, and kept on this device until the server has it (a phone can close the app at any moment) */
        editChanged: function () {
          if (!this.editing || !this.editFirst) return;
          var self = this, e = this.edit;
          if (JSON.stringify(e) === this.editFrom) return;
          this.editState = "dirty";
          store(EDIT, { id: e.id, question: e.question, answer: e.answer, chapter: e.chapter, categories: e.categories, color: e.color });
          clearTimeout(this.editTimer);
          if (e.question.trim()) this.editTimer = setTimeout(function () { self.saveEditing(); }, 900);
        },
        /* What's in the editor, to the server (`to`: a subject to move it to). One save at a time, in order. */
        sendEdit: function (q, e, to) {
          var self = this, fields = { action: "update", question: e.question, answer: e.answer, chapter: e.chapter, categories: (e.categories || []).join(","), color: e.color };
          if (to) fields.subject = to; else fields._ft_same = "exam:" + q.id;
          var sent = JSON.stringify(e);
          this.editSending = Promise.resolve(this.editSending).then(function () {
            fields.rev = q.rev || "";                     // (as the save before this one left it)
            return api(D.noteBase + q.id + "/", fields);
          }).then(function (r) {
            self.editSending = null;
            if (!r.ok && !r.queued) return r;
            if (r.ok) { q.question = e.question.trim(); q.answer = e.answer; q.chapter = (e.chapter || "").trim(); q.categories = (e.categories || []).slice(); q.color = e.color; }
            if (r.rev) q.rev = r.rev;
            if (r.conflict) toast(t("conflict"), "warn");
            if (JSON.stringify(self.edit) === sent || self.editing !== q) store(EDIT, null);
            return r;
          });
          return this.editSending;
        },
        /* earlier versions of this question: one can be read and brought back */
        openHistory: function () {
          var self = this, q = this.editing;
          if (!q) return;
          this.histOpen = true; this.histLoading = true; this.versions = []; this.shown = null;
          this.saveEditing();
          Promise.resolve(this.editSending).then(function () {
            return fetch(D.noteBase + q.id + "/versions/", { credentials: "same-origin", headers: { Accept: "application/json" } });
          }).then(function (r) { return r.json(); }).then(function (r) { self.versions = r.versions || []; self.shown = self.versions[0] || null; })
            .catch(function () { self.versions = []; }).then(function () { self.histLoading = false; });
        },
        restoreVersion: function (v) {
          var self = this, q = this.editing;
          if (!v || !q) return;
          FT.ask(t("restoreAsk")).then(function (sure) {
            if (!sure) return;
            api(D.noteBase + q.id + "/", { action: "restore", version: v.id }).then(function (r) {
              if (!r.ok || r.queued) return;
              q.question = r.note.question; q.answer = r.note.answer; q.rev = r.rev;
              self.edit.question = q.question; self.edit.answer = q.answer;
              self.editFrom = JSON.stringify(self.edit); self.editState = "saved"; self.histOpen = false;
              store(EDIT, null);
            });
          });
        },
        saveEditing: function () {
          var self = this, q = this.editing, e = this.edit, sent = JSON.stringify(e);
          clearTimeout(this.editTimer);
          if (!q || this.editState !== "dirty") return;
          this.editState = "saving";
          this.sendEdit(q, e).then(function (r) {
            if (self.editing !== q) return;
            if (!r.ok && !r.queued) { self.editState = "error"; return; }
            self.editFrom = sent;
            self.editState = JSON.stringify(self.edit) !== sent ? "dirty" : r.queued ? "offline" : "saved";
            if (self.editState === "dirty") self.editChanged();
          });
        },
        closeEditor: function () {
          var self = this, q = this.editing, e = this.edit, was = this.editFirst, from = this.editFrom;
          if (!q) return;
          clearTimeout(this.editTimer);
          var unsent = JSON.stringify(e) !== from || this.editState === "error", to = String(e.subject) !== String(D.subject) ? e.subject : "";
          if (unsent && !e.question.trim()) { toast(t("writeFirst"), "warn"); return; }
          this.editing = null;
          function done() {
            if ((e.chapter || "").trim() !== was.chapter || JSON.stringify(e.categories) !== JSON.stringify(was.categories)) self.reload();
          }
          if (!unsent) { this.flags(q, e, was); done(); return; }
          this.sendEdit(q, e, to).then(function (r) {
            if (!r.ok && !r.queued) {                     // not saved: nothing is lost, the editor comes back with what was written
              self.editFirst = was; self.editFrom = from; self.edit = e; self.editState = "error"; self.editing = q;
              return;
            }
            if (to) {                                     // moved to another subject
              self.notes.splice(self.notes.indexOf(q), 1);
              var named = D.subjects.find(function (s) { return String(s.id) === String(to); });
              toast(t("moved").replace("%(name)s", named ? named.name : ""), "good");
              self.reload();
              return;
            }
            done();
          });
          this.flags(q, e, was);
        },
        flags: function (q, e, was) {
          if (e.starred !== was.starred) this.flag(q, "star");
          if (e.known !== was.known) this.flag(q, "known");
        },
        /* the next or previous question, without closing the editor (this one is saved first); past the
           last loaded one, the next page comes */
        canStep: function (dir) {
          var i = this.notes.indexOf(this.editing);
          return i >= 0 && (dir < 0 ? i > 0 : i < this.notes.length - 1 || !!this.next);
        },
        stepEditor: function (dir) {
          var self = this, i = this.notes.indexOf(this.editing);
          if (i < 0) return;
          function go(q) {
            self.closeEditor();
            if (self.editing) return;                     // not closed: the question is empty
            self.openEditor(q);
            var card = self.$refs.grid.querySelector('[data-id="' + q.id + '"]');
            if (card) card.scrollIntoView({ block: "nearest" });
          }
          if (this.notes[i + dir]) return go(this.notes[i + dir]);
          if (dir > 0 && this.next) this.load().then(function () { if (self.notes[i + 1]) go(self.notes[i + 1]); });
        },
        editorKey: function (e) {
          if (e.altKey && !e.ctrlKey && !e.metaKey && (e.key === "ArrowLeft" || e.key === "ArrowRight")) {
            e.preventDefault(); this.stepEditor(e.key === "ArrowLeft" ? -1 : 1);
          }
        },
        removeEditing: function () { var q = this.editing; clearTimeout(this.editTimer); store(EDIT, null); this.editing = null; this.remove(q); },
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
          if (op === "delete") return FT.ask({ message: t("bulkDeleteAsk"), danger: true, after: "back" }).then(function (sure) { if (sure) self.bulkSend(op, ids, fields); });
          if (op === "chapter") {
            return FT.ask({ title: t("chapterAsk"), input: {} }).then(function (name) {
              if (name === null) return;
              fields.chapter = name.trim(); self.bulkSend(op, ids, fields);
            });
          }
          if (op === "move") { if (!this.moveTo) return; fields.subject = this.moveTo; }
          if (op === "categories") {               // chosen in the popup, added on Done
            var chosen = [];
            this.pickCats(chosen, function () {
              if (!chosen.length) return;
              api(D.api, Object.assign(fields, { categories: chosen.join(",") })).then(function (r) {
                if (!r.ok) return;
                self.endSelect(); toast(t("catAdded"), "good"); self.reload();
              });
            });
            return;
          }
          this.bulkSend(op, ids, fields);
        },
        bulkSend: function (op, ids, fields) {
          var self = this;
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
          var self = this;
          FT.ask({ title: t("renameAsk"), input: { value: c.name } }).then(function (name) {
            if (name === null || name.trim() === c.name) return;
            api(D.api, { action: "rename_chapter", old: c.name, chapter: name.trim() }).then(function (r) {
              if (!r.ok) return;
              if (self.chapter === c.name) self.chapter = name.trim();         // the page stays on it
              self.reload();
            });
          });
        },
        moveChapter: function (i, step) {
          var self = this, c = this.chapters[i];
          api(D.api, { action: "chapter_move", chapter: c.name, step: step }).then(function (r) { if (r.ok) { self.updateCounts(r); self.reload(); } });
        },
        reset: function () {
          var self = this;
          FT.ask(t("resetAsk")).then(function (sure) {
            if (sure) api(D.api, { action: "reset" }).then(function (r) { if (r.ok) self.reload(); });
          });
        },
        key: function (e) {
          if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey || typing(e) || this.editing || this.catOpen) return;
          var cards = Array.prototype.slice.call(this.$refs.grid.querySelectorAll(".wkc"));
          var card = d.activeElement && d.activeElement.closest && d.activeElement.closest(".wkc");
          var q = card && this.notes.find(function (n) { return String(n.id) === card.getAttribute("data-id"); });
          if (e.key === "j" || e.key === "k") {         // from card to card, without the mouse
            if (!cards.length) return;
            e.preventDefault();
            var at = cards.indexOf(card), to = cards[at < 0 ? 0 : Math.max(0, Math.min(cards.length - 1, at + (e.key === "j" ? 1 : -1)))];
            to.focus(); to.scrollIntoView({ block: "nearest" });
            if (e.key === "j" && cards.indexOf(to) >= cards.length - 3) this.more();
            return;
          }
          if (q && (e.key === "x" || e.key === "s" || e.key === "e")) {
            e.preventDefault();
            if (e.key === "e") this.openEditor(q); else this.flag(q, e.key === "x" ? "known" : "star");
            return;
          }
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
        reviewUrl: function () {         // these questions: what's shown here, search and "No chapter" too
          return this.withCategory(D.review + "?which=" + this.show + (this.chapter ? "&chapter=" + encodeURIComponent(this.chapter) : this.chapter === "" ? "&nochapter=1" : "")
            + (this.query.trim() ? "&q=" + encodeURIComponent(this.query.trim()) : ""));
        },
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
          if (e.ctrlKey || e.metaKey || e.altKey || typing(e) || this.catOpen) return;
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
        t: t, all: D.notes || [], chapters: D.chapters || [], chapter: D.chapter || "", which: D.which || "unknown", back: D.back,
        shuffle: D.shuffle || !!recall("exam-shuffle", false), writeFirst: !!recall("exam-write-first", false), mine: "",
        queue: [], pos: 0, card: null, flipped: false, stage: "card", editing: false, draft: {}, history: [],
        seen: 0, firstTry: 0, missed: [], started: 0, took: "", swipe: null, swiped: 0,
        test: null, testN: 10, testMins: 15, tick: null, left: 0, perChapter: [],
        init: function () {
          var self = this;
          if (D.test) { this.stage = "setup"; return; }
          this.$watch("shuffle", function (v) { store("exam-shuffle", v || null); });
          this.$watch("writeFirst", function (v) { store("exam-write-first", v || null); });
          this.start(this.which);
        },
        start: function (which, only) {
          var chapter = this.chapter;
          this.which = which;
          var list = only ? only.slice() : this.all.filter(function (q) {
            if (chapter && q.chapter !== chapter) return false;
            if (which === "today") return !q.known || q.due;          // to learn, and due again (spaced repetition)
            if (which === "due") return q.due;
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
        /* A practice test: a set number of questions, the weakest and least known first, against the clock. Each one
           comes once ("Not yet" doesn't bring it back) and the end says how it went, chapter by chapter. */
        startTest: function () {
          var self = this, score = function (q) { return (q.known ? 0 : 2) + Math.min(q.misses, 3) + Math.random(); };
          var list = this.all.filter(function (q) { return !self.chapter || q.chapter === self.chapter; });
          list = list.map(function (q) { return [score(q), q]; }).sort(function (a, b) { return b[0] - a[0]; }).map(function (x) { return x[1]; }).slice(0, Math.max(1, this.testN));
          this.test = {}; this.left = this.testMins * 60;
          this.start("all", list);
          clearInterval(this.tick);
          this.tick = setInterval(function () { if (--self.left <= 0) self.endTest(); }, 1000);
        },
        endTest: function () {
          var self = this, chapters = {}, order = [];
          clearInterval(this.tick);
          this.queue.forEach(function (q, i) {
            var name = q.chapter, row = chapters[name];
            if (!row) { row = chapters[name] = { name: name, right: 0, n: 0 }; order.push(row); }
            row.n++; row.right += self.test[q.id] ? 1 : 0;
          });
          this.perChapter = order.sort(function (a, b) { return a.right / a.n - b.right / b.n; });
          this.took = window.Work && Work.clock ? Work.clock(Math.round((Date.now() - this.started) / 1000)) : "";
          this.stage = "result";
        },
        score: function () { var n = this.queue.length; return n ? Math.round(100 * this.perChapter.reduce(function (s, c) { return s + c.right; }, 0) / n) : 0; },
        leftClock: function () { var m = Math.floor(this.left / 60), s = this.left % 60; return m + ":" + (s < 10 ? "0" : "") + s; },
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
          this.history.push({ q: q, knew: knew, known: q.known, misses: q.misses, due: q.due, dueOn: q.dueOn, interval: q.interval, firstTry: this.firstTry, missed: this.missed.slice() });
          if (knew && this.missed.indexOf(q) < 0) this.firstTry++;
          if (this.test) this.test[q.id] = knew;
          if (!knew) { if (this.missed.indexOf(q) < 0) this.missed.push(q); if (!this.test) this.queue.push(q); q.misses++; }
          q.known = knew; q.due = false;
          api(D.noteBase + q.id + "/", { action: "review", knew: knew ? "1" : "0" }).then(function (r) { if (r && r.dueOn) { q.dueOn = r.dueOn; q.interval = r.interval; } });
          this.pos++;
          if (this.test && this.pos >= this.queue.length) { this.endTest(); return; }
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
          if (!h.knew && !this.test) this.queue.pop();
          if (this.test) delete this.test[h.q.id];
          h.q.known = h.known; h.q.misses = h.misses; h.q.due = h.due; h.q.dueOn = h.dueOn; h.q.interval = h.interval;
          this.firstTry = h.firstTry; this.missed = h.missed;
          api(D.noteBase + h.q.id + "/", { action: "unreview", known: h.known ? "1" : "0", misses: String(h.misses), dueOn: h.dueOn || "", interval: String(h.interval || 0) });
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
          api(D.noteBase + q.id + "/", { action: "update", question: e.question, answer: e.answer, rev: q.rev || "" }).then(function (r) {
            if (!r.ok && !r.queued) return;
            q.question = e.question.trim(); q.answer = e.answer; self.editing = false; q.rev = r.rev || "";
            if (r.conflict) toast(t("conflict"), "warn");
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
          if (this.stage === "setup" || this.stage === "result") return;
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
