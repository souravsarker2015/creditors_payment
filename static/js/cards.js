/* Flashcards (Productivity): the review session and a deck's page.
   Loaded after work.js on those two pages.

   A review shows one card at a time: the question, then (Space, a tap or a
   click) the answer turned over, then four buttons — or a swipe on a phone —
   for how well it was known. Each answer is saved in the background (and
   queued on the phone with no signal); a card answered "Again" comes back a
   few cards later in the same session. */
(function () {
  "use strict";
  var d = document;
  var REDUCED = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
  var TEXT = (function () { try { return JSON.parse(d.getElementById("card-text").textContent); } catch (e) { return {}; } })();
  function toast(msg, tone, act) { if (window.Work && Work.toast) Work.toast(msg, tone, act); }
  function md(text) { return window.Work && Work.markdown ? Work.markdown(text || "") : String(text || ""); }
  function url(name) { return (Work.cfg && Work.cfg.urls && Work.cfg.urls[name]) || ""; }
  function typing(el) { return el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName)); }
  // the same "question :: answer" (or tab) lines the server reads (cards.parse_pairs)
  var PAIR = /^\s*(?:[-*+]\s+|\d+[.)]\s+)?(.+?)\s*(?:::|\t)\s*(.+?)\s*$/;

  /* Fill an element with a card side: Markdown, code coloured, ```mermaid drawn. */
  function show(el, text) {
    el.innerHTML = md(text);
    if (window.Work && Work.mermaidIn) Work.mermaidIn(el);
    if (window.hljs) el.querySelectorAll("pre code:not(.language-mermaid)").forEach(function (c) { hljs.highlightElement(c); });
  }

  document.addEventListener("alpine:init", function () {
    /* ── A review session ──────────────────────────────────────────────── */
    Alpine.data("cardReview", function () {
      var S = JSON.parse(d.getElementById("review-data").textContent), queue = S.cards.slice();
      return {
        stage: queue.length ? "card" : "empty", card: null, flipped: false, busy: false, back: S.back, practice: S.practice,
        total: queue.length, done: 0, answered: 0, knew: 0, started: Date.now(), took: "", left: { fresh: 0, again: 0, due: 0 },
        singleDeck: S.cards.every(function (c) { return c.deckId === (S.cards[0] || {}).deckId; }),
        init: function () {
          if (queue.length) this.next(true);
          this.swipes();
        },
        tally: function () {
          var all = (this.card ? [this.card] : []).concat(queue), left = { fresh: 0, again: 0, due: 0 };
          all.forEach(function (c) { if (c._again) left.again++; else if (c.isNew) left.fresh++; else left.due++; });
          this.left = left;
        },
        next: function (first) {
          var self = this, wrap = this.$refs.wrap;
          this.card = queue.shift() || null;
          if (!this.card) { this.finish(); return; }
          this.flipped = false;
          show(this.$refs.front, this.card.front); show(this.$refs.q, this.card.front);
          if (this.card.back) show(this.$refs.back, this.card.back); else this.$refs.back.innerHTML = '<p class="wfc-muted">' + (TEXT.noAnswer || "") + "</p>";
          this.tally();
          wrap.style.transform = ""; wrap.className = "wfr-card-wrap";
          if (!REDUCED && !first) { void wrap.offsetWidth; wrap.classList.add("is-in"); }
          this.busy = false;
          this.$nextTick(function () { self.$refs.card.focus({ preventScroll: true }); });
        },
        flip: function () {
          if (this.stage !== "card" || this.busy || this._dragged) return;
          this.flipped = !this.flipped;
        },
        hint: function (r) {
          if (!this.card) return "";
          if (this.practice) return r === 1 ? (this.card.previews || {})[1] || "" : "";
          return (this.card.previews || {})[r] || "";
        },
        rate: function (r) {
          if (!this.flipped || this.busy || !this.card) return;
          var self = this, c = this.card, wrap = this.$refs.wrap;
          this.busy = true; this.answered++; if (r > 1) this.knew++;
          // again soon: forgotten, or still being learnt and only just remembered (the server agrees: interval 0)
          var again = r === 1 || (!this.practice && r === 2 && (c.isNew || c._again));
          if (!this.practice) {
            Work.api(url("cardBase") + c.id + "/", { action: "answer", rating: r, at: new Date().toISOString() }).then(function (res) {
              if (res && res.ok && res.card && again) { c.previews = res.card.previews; c.isNew = res.card.isNew; }
            });
          }
          if (again) { c._again = true; queue.splice(Math.min(queue.length, r === 1 ? 3 : 6), 0, c); }
          else this.done++;
          var dir = r === 1 ? "is-out-left" : r === 2 ? "is-out-down" : "is-out-right";
          if (REDUCED) { this.next(); return; }
          wrap.style.transform = ""; wrap.classList.add(dir);
          setTimeout(function () { self.next(); }, 260);
        },
        finish: function () {
          var s = Math.round((Date.now() - this.started) / 1000), m = Math.floor(s / 60);
          this.took = m ? m + "m " + (s % 60) + "s" : s + "s";
          this.stage = "done"; this.tally();
          if (window.Work && Work.play) try { Work.play(); } catch (e) { /* sounds off or not allowed */ }
        },
        key: function (e) {
          if (typing(e.target) || e.ctrlKey || e.metaKey || e.altKey) return;
          var k = e.key;
          if (k === "Escape") { location.href = this.back; return; }
          if (this.stage !== "card") return;
          if ((k === " " || k === "Enter") && !this.flipped) { e.preventDefault(); this.flip(); }
          else if (this.flipped && /^[1-4]$/.test(k)) { e.preventDefault(); this.rate(+k); }
          else if (this.flipped && k === " ") { e.preventDefault(); this.rate(3); }
        },
        /* On a phone: drag the turned-over card right (knew it) or left (again). */
        swipes: function () {
          var self = this, wrap = this.$refs.wrap, start = null;
          wrap.addEventListener("pointerdown", function (e) {
            if (e.pointerType === "mouse" || !self.flipped || self.busy) return;
            start = { x: e.clientX, y: e.clientY, id: e.pointerId }; self._dragged = false;
          });
          wrap.addEventListener("pointermove", function (e) {
            if (!start || e.pointerId !== start.id) return;
            var dx = e.clientX - start.x, dy = e.clientY - start.y;
            if (!self._dragged && Math.abs(dx) < 10) return;
            if (!self._dragged && Math.abs(dy) > Math.abs(dx)) { start = null; return; }   // scrolling, not swiping
            self._dragged = true; try { wrap.setPointerCapture(e.pointerId); } catch (err) { /* gone */ }
            wrap.style.transform = "translateX(" + dx + "px) rotate(" + dx / 22 + "deg)";
            wrap.style.setProperty("--swipe", Math.max(-1, Math.min(1, dx / 110)));
          });
          function end(e) {
            if (!start || e.pointerId !== start.id) return;
            var dx = e.clientX - start.x; start = null;
            wrap.style.removeProperty("--swipe");
            if (self._dragged && Math.abs(dx) > 100) self.rate(dx > 0 ? 3 : 1);
            else wrap.style.transform = "";
            setTimeout(function () { self._dragged = false; }, 50);
          }
          wrap.addEventListener("pointerup", end); wrap.addEventListener("pointercancel", end);
        },
      };
    });

    /* ── A deck: add, edit, pause, move and delete cards ──────────────── */
    Alpine.data("deckPage", function (deckId, openSettings) {
      return {
        list: JSON.parse(d.getElementById("deck-cards").textContent), texts: TEXT, mode: "one", front: "", back: "", many: "", busy: false,
        editing: null, draft: { front: "", back: "" }, settings: !!openSettings,
        get manyCount() { return this.many.split("\n").filter(function (l) { var m = PAIR.exec(l); return m && m[1].trim() && m[2].trim(); }).length; },
        md: md,
        init: function () { if (location.hash === "#add") { var self = this; this.$nextTick(function () { self.$refs.front.focus(); }); } },
        addOne: function () {
          var self = this; if (!this.front.trim() || this.busy) return;
          this.busy = true;
          Work.api(url("cardAdd"), { deck: deckId, front: this.front, back: this.back }).then(function (res) {
            self.busy = false;
            if (!res || !res.ok) { toast((res && res.error) || TEXT.error || "", "warn"); return; }
            if (res.card) { res.card.fresh = true; self.list.unshift(res.card); }
            self.front = ""; self.back = ""; toast(TEXT.added, "good");
            self.$nextTick(function () { self.$refs.front.focus(); });
          });
        },
        addMany: function () {
          var self = this; if (!this.manyCount || this.busy) return;
          this.busy = true;
          Work.api(url("cardAdd"), { deck: deckId, text: this.many }).then(function (res) {
            self.busy = false;
            if (!res || !res.ok) { toast((res && res.error) || "", "warn"); return; }
            if (res.queued) { self.many = ""; return; }
            toast(TEXT.addedMany + ": " + res.added + (res.skipped ? " · " + res.skipped + " " + TEXT.skipped : ""), "good");
            setTimeout(function () { location.href = "?show=new"; }, 700);
          });
        },
        edit: function (c) { this.editing = c.id; this.draft = { front: c.front, back: c.back }; },
        saveEdit: function (c) {
          var self = this; if (!this.draft.front.trim()) return;
          Work.api(url("cardBase") + c.id + "/", { action: "save", front: this.draft.front, back: this.draft.back }).then(function (res) {
            if (!res || !res.ok) { toast((res && res.error) || "", "warn"); return; }
            if (res.card) Object.assign(c, res.card); else { c.front = self.draft.front; c.back = self.draft.back; }
            self.editing = null; toast(TEXT.saved, "good");
          });
        },
        act: function (c, action, extra) {
          var self = this;
          if (action === "reset" && !confirm(TEXT.resetConfirm)) return;
          Work.api(url("cardBase") + c.id + "/", Object.assign({ action: action }, extra || {})).then(function (res) {
            if (!res || !res.ok) { if (res && res.error) toast(res.error, "warn"); return; }
            if (action === "delete") { self.drop(c); Work.undoable(TEXT.deleted, res.undo); }
            else if (action === "move") { self.drop(c); toast(TEXT.moved + ": " + res.deck); }
            else if (res.card) {
              Object.assign(c, res.card);
              toast(action === "pause" ? (c.paused ? TEXT.paused : TEXT.resumed) : TEXT.reset);
            }
          });
        },
        drop: function (c) { this.list = this.list.filter(function (x) { return x.id !== c.id; }); },
        deckAction: function (name) {
          if (name === "delete" && !confirm(TEXT.deleteDeck)) return;
          Work.api("/work/api/decks/" + deckId + "/", { action: name }).then(function (res) {
            if (!res || !res.ok) return;
            if (name === "delete") { Work.undoable(TEXT.deleted, res.undo, function () { location.reload(); }); setTimeout(function () { location.href = url("cards"); }, 400); }
            else location.href = res.url;
          });
        },
      };
    });
  });
})();
