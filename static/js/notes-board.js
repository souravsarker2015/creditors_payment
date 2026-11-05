/* The notes board (Productivity → Notes, nothing open): notes as cards, like
   Google Keep — made to take few clicks:
   - "Take a note…" opens into a title and a note; it's saved on Ctrl+Enter,
     on Save, or when you click away (an empty one is dropped), and the new
     card goes to the top.
   - A click on a card opens it right here, over the board: written in place,
     saved as you type, Esc closes it (the full editor — history, links,
     diagrams — is one button away, or Ctrl/⌘-click the title).
   - The to-dos on a card are ticked right on it; the search filters as you
     type; pin, colour, archive and delete are on the card.
   A card that changes is drawn again by the server (its HTML comes back with
   the save) and swapped in. Loaded after work.js. */
(function () {
  "use strict";
  var d = document;
  function urls() { return Work.cfg.urls; }
  function t(key, fallback) { return (Work.cfg.text || {})[key] || fallback; }
  function fromHTML(html) {
    var box = d.createElement("div"); box.innerHTML = (html || "").trim();
    return box.firstElementChild;
  }
  function cardOf(id) { return d.querySelector('[data-note-card="' + id + '"]'); }

  document.addEventListener("alpine:init", function () {
    Alpine.data("noteBoard", function () {
      var DRAFT = Work.noteDraftKey("quick");
      var CATS = JSON.parse((d.getElementById("note-cats") || {}).textContent || "{}");
      return Work.withCategories({
        open: false, title: "", body: "", color: "", pinned: false, saving: false,
        cats: CATS.categories || [], catN: CATS.counts || {}, category: CATS.category === undefined ? null : CATS.category,
        picked: [], sideClosed: Work.recall("work-note-side", {}) || {},
        ed: null, edPreview: false, edRead: false, edState: "saved", edTimer: null, edSending: null, edAgain: false, edSaved: "", edTitle: "", finding: null,
        init: function () {
          var self = this, older = Work.recall("work-note-quick", null);
          if (older) { Work.store(DRAFT, older); Work.store("work-note-quick", null); }      // (kept for everyone on this browser until now)
          var saved = Work.recall(DRAFT, null);                        // what was being written when the page closed
          if (saved && (saved.title || saved.body)) { Object.assign(this, saved); this.open = true; }
          ["title", "body", "color", "pinned"].forEach(function (k) { self.$watch(k, function () { self.keep(); }); });
          this.$watch("ed", function () { self.edChanged(); }, { deep: true });
          d.addEventListener("note-open", function (e) { self.openNote(e.detail.id, e.detail.mode); });
          d.addEventListener("work:synced", function (e) {            // written offline, and it's there now
            if (!self.ed || e.detail.same !== "note:" + self.ed.id) return;
            self.ed.rev = e.detail.rev || "";
            if (self.edState === "offline") self.edState = "saved";
          });
          window.addEventListener("beforeunload", function () { self.flushNote(); });
          var asked = new URLSearchParams(location.search).get("open");          // ?open=N: that note, opened
          if (/^\d+$/.test(asked || "")) this.openNote(+asked);
        },
        keep: function () {
          Work.store(DRAFT, this.title.trim() || this.body.trim() ? { title: this.title, body: this.body, color: this.color, pinned: this.pinned } : null);
        },
        start: function () {
          var self = this;
          this.open = true;
          this.$nextTick(function () { self.$refs.body.focus(); });
        },
        close: function () {
          if (this.title.trim() || this.body.trim()) { this.save(false); return; }
          this.open = false;
        },
        save: function (again) {
          var self = this;
          if (this.saving || !(this.title.trim() || this.body.trim())) return;
          this.saving = true;
          // showing one category: a quick note goes into it (as Keep does with a label)
          Work.api(urls().noteSave, { title: this.title.trim(), body: this.body, color: this.color, pinned: this.pinned ? "1" : "", card: "1",
                                      categories: typeof this.category === "number" ? String(this.category) : "" }).then(function (r) {
            self.saving = false;
            if (!r || !r.ok) { if (!(r && r.queued)) Work.toast(t("notSaved", "Not saved."), "warn"); return; }
            if (r.card) self.place(fromHTML(r.card), self.pinned);
            self.title = ""; self.body = ""; self.color = ""; self.pinned = false;
            Work.store(DRAFT, null);
            if (again) self.$nextTick(function () { self.$refs.body.focus(); }); else self.open = false;
            Work.toast(t("noteSaved", "Note saved"), "good");
          });
        },
        // A card first in its group — the pinned ones, then the others (as the server orders them: the one just
        // changed is the newest) — gliding there from where it was; the headings follow.
        place: function (card, pinned) {
          var grid = this.$refs.grid, self = this;
          card.toggleAttribute("data-pinned", !!pinned);
          return Work.flip(grid, function () {
            var none = grid.querySelector(".wnb-none");
            if (none) none.remove();
            var cards = Array.prototype.filter.call(grid.querySelectorAll("[data-note-card]"), function (c) { return c !== card; });
            var firstOther = cards.find(function (c) { return !c.hasAttribute("data-pinned"); });
            var lastPinned = cards.filter(function (c) { return c.hasAttribute("data-pinned"); }).pop();
            if (pinned || !lastPinned) grid.prepend(card);
            else if (firstOther) firstOther.before(card);
            else lastPinned.after(card);
            self.heads();
          });
        },
        // "Pinned" over the pinned cards and "Others" over the rest — only while some are pinned (as Keep)
        heads: function () {
          var grid = this.$refs.grid;
          grid.querySelectorAll(".wnb-head").forEach(function (h) { h.remove(); });
          var cards = Array.prototype.slice.call(grid.querySelectorAll("[data-note-card]"));
          if (!cards.some(function (c) { return c.hasAttribute("data-pinned"); })) return;
          var tpl = this.$refs.heads;
          grid.prepend(tpl.content.querySelector('[data-head="pinned"]').cloneNode(true));
          var other = cards.find(function (c) { return !c.hasAttribute("data-pinned"); });
          if (other) other.before(tpl.content.querySelector('[data-head="others"]').cloneNode(true));
        },

        /* ── search as you type: the cards (and the pages after them) come from the server ── */
        find: function (form) {
          var self = this, params = new URLSearchParams(new FormData(form));
          if (!params.get("q")) params.delete("q");
          var url = location.pathname + (params.toString() ? "?" + params : "");
          if (this.finding) this.finding.abort();
          this.finding = new AbortController();
          fetch(url, { credentials: "same-origin", headers: { "X-Requested-With": "fetch" }, signal: this.finding.signal })
            .then(function (r) { return r.text(); })
            .then(function (html) {
              var page = new DOMParser().parseFromString(html, "text/html");
              var grid = page.querySelector(".wnb-grid"), pager = page.querySelector("nav.pager");
              if (!grid) return;
              self.$refs.grid.innerHTML = grid.innerHTML;
              self.$refs.pager.innerHTML = pager ? pager.outerHTML : "";
              history.replaceState(history.state, "", url);
              if (window.FTInfinite) FTInfinite.scan(self.$refs.pager);
            })
            .catch(function () {});
        },

        /* ── a note opened over the board ── */
        openNote: function (id, mode) {
          var self = this;
          this.flushNote();
          fetch(urls().noteBase + id + "/get/", { credentials: "same-origin", headers: { Accept: "application/json" } })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (n) {
              if (!n || !n.ok) { location.href = (urls().notes || "/work/notes/") + id + "/"; return; }
              self.edSaved = JSON.stringify([n.title, n.body]); self.edTitle = n.title;
              self.ed = { id: n.id, title: n.title, icon: n.icon || "", body: n.body, color: n.color, pinned: n.pinned, url: n.url, archived: n.archived, rev: n.rev, categories: n.categories || [] };
              // a card's Edit button: Write; a click on the card: View; otherwise as notes were last read here
              var seen = mode || Work.recall("work-board-view", "write");
              if (seen === true) seen = "preview"; else if (seen === false) seen = "write";
              self.edState = "saved"; self.edPreview = seen === "preview" || seen === "view"; self.edRead = seen === "view";
              var draft = Work.recall(Work.noteDraftKey(n.id), null);      // what wasn't saved last time comes back, and is saved now
              if (draft && draft.at > n.updated && (draft.title !== n.title || draft.body !== n.body)) {
                self.ed.title = draft.title; self.ed.body = draft.body;
                Work.toast(t("noteDraftBack", "Your unsaved writing is back."), "good");
              }
              var url = new URL(location.href); url.searchParams.set("open", n.id);
              history.replaceState(history.state, "", url.pathname + url.search);
              self.$nextTick(function () {
                var ta = self.$refs.edBody;
                if (ta) { ta.focus(); ta.setSelectionRange(ta.value.length, ta.value.length); ta.scrollTop = ta.scrollHeight; }
              });
            })
            .catch(function () { location.href = (urls().notes || "/work/notes/") + id + "/"; });
        },
        edChanged: function () {
          if (!this.ed || JSON.stringify([this.ed.title, this.ed.body]) === this.edSaved) return;      // (colour and pin save themselves)
          var self = this;
          this.edState = "dirty";
          Work.store(Work.noteDraftKey(this.ed.id), { title: this.ed.title, body: this.ed.body, at: Date.now() });     // kept here until the server has it
          clearTimeout(this.edTimer);
          this.edTimer = setTimeout(function () { self.saveNote(); }, 700);
        },
        saveNote: function () {
          var self = this, n = this.ed;
          clearTimeout(this.edTimer);
          if (!n || (this.edState !== "dirty" && this.edState !== "error")) return this.edSending || Promise.resolve();
          if (this.edSending) { this.edAgain = true; return this.edSending; }       // one save at a time
          this.edState = "saving";
          var sent = { title: n.title, body: n.body };
          this.edSending = Work.api(urls().noteSave, { id: n.id, title: n.title, body: n.body, rev: n.rev || "", card: "1", _ft_same: "note:" + n.id, _ft_draft: Work.noteDraftKey(n.id) }).then(function (r) {
            self.edSending = null;
            if (r && r.queued) { if (self.ed === n) self.edState = "offline"; return; }
            if (!r || !r.ok) {
              if (self.ed === n) { self.edState = "error"; return; }
              Work.toast(t("notSaved", "Not saved."), "warn");             // closed meanwhile: it opens again, with what was written
              self.openNote(n.id);
              return;
            }
            n.rev = r.rev;
            if (r.conflict) Work.toast(t("noteConflict", "This note was changed somewhere else too. That text is kept in History."), "warn");
            if (n.title === sent.title && n.body === sent.body) Work.store(Work.noteDraftKey(n.id), null);
            self.swap(n.id, r.card);
            if (self.ed === n) { self.edSaved = JSON.stringify([sent.title, sent.body]); self.edState = n.title === sent.title && n.body === sent.body ? "saved" : "dirty"; }
            if (self.edAgain || (self.ed === n && self.edState === "dirty")) { self.edAgain = false; self.saveNote(); }
          });
          return this.edSending;
        },
        flushNote: function () { if (this.ed && (this.edState === "dirty" || this.edState === "error")) this.saveNote(); },
        /* renamed (the title box left): the [[links]] in other notes follow */
        titleChanged: function () {
          var self = this, n = this.ed, old = this.edTitle;
          if (!n || !old.trim() || old.trim() === n.title.trim()) return;
          this.edTitle = n.title;
          Promise.resolve(this.saveNote()).then(function () {
            return Work.api(urls().noteBase + n.id + "/", { action: "relink", old: old });
          }).then(function (r) { if (r && r.ok && r.count) Work.toast(t(r.count === 1 ? "linksUpdatedOne" : "linksUpdated", "Links updated: %(n)s").replace("%(n)s", r.count), "good"); });
        },
        swap: function (id, html) {
          var old = cardOf(id);
          if (old && html) old.replaceWith(fromHTML(html));
        },
        edView: function (mode) {          // "write", "preview" (click a part to change it) or "view" (just to read)
          if (mode === true) mode = "preview"; else if (mode === false) mode = "write";
          Work.liveDone();
          this.edPreview = mode !== "write"; this.edRead = mode === "view"; Work.store("work-board-view", mode);
          var self = this;
          if (mode === "write") this.$nextTick(function () { if (self.$refs.edBody) self.$refs.edBody.focus(); });
        },
        /* several cards picked (the round tick, as in Keep): pin, file, archive or delete them all at once */
        togglePick: function (id) {
          var i = this.picked.indexOf(id);
          if (i >= 0) this.picked.splice(i, 1); else this.picked.push(id);
          var card = cardOf(id), on = i < 0;
          if (card) { card.classList.toggle("is-picked", on); var b = card.querySelector(".wnc-pick"); if (b) b.setAttribute("aria-pressed", String(on)); }
        },
        unmark: function () {
          d.querySelectorAll(".wnc.is-picked").forEach(function (c) { c.classList.remove("is-picked"); var b = c.querySelector(".wnc-pick"); if (b) b.setAttribute("aria-pressed", "false"); });
        },
        bulk: function (action, on, extra) {
          var self = this, ids = this.picked.slice();
          if (!ids.length) return;
          var go = function () {
            Work.api(urls().notesBulk, Object.assign({ ids: ids.join(","), action: action, on: on || "" }, extra || {})).then(function (r) {
              if (!r || !r.ok) { if (!(r && r.queued)) Work.toast((r && r.error) || t("notSaved", "Not saved."), "warn"); return; }
              self.picked = []; location.reload();
            });
          };
          if (action !== "delete") return go();
          FT.ask({ message: t("deletePicked", "Delete the %(n)s picked notes? You can bring them back from Recently deleted.").replace("%(n)s", ids.length), danger: true, after: "back" })
            .then(function (sure) { if (sure) go(); });
        },
        bulkCats: function () {
          var self = this, list = [];
          this.pickCats(list, function () { if (list.length) self.bulk("categories", "", { categories: list.join(",") }); });
        },
        /* categories: the board shows one (with what's inside it); an open note's are picked in the pop-up */
        setCategory: function (id) { location.href = urls().notes + (id === null ? "" : "?category=" + id); },
        reload: function () {},
        pickEdCats: function () { var self = this; this.pickCats(this.ed.categories, function () { self.saveEdCats(); }); },
        dropEdCat: function (id) { this.catRemove(this.ed.categories, id); this.saveEdCats(); },
        saveEdCats: function () {
          var self = this, n = this.ed; if (!n) return;
          Work.api(urls().noteSave, { id: n.id, categories: n.categories.join(","), card: "1" }).then(function (r) { if (r && r.ok) self.swap(n.id, r.card); });
        },
        closeNote: function () {
          var id = this.ed && this.ed.id;
          Work.liveDone();          // a part being changed in the preview goes in first
          this.flushNote();
          this.ed = null;
          var url = new URL(location.href); url.searchParams.delete("open");
          history.replaceState(history.state, "", url.pathname + url.search);
          var card = id && cardOf(id); if (card) card.scrollIntoView({ block: "nearest" });
        },
        /* the side list of categories (Keep's labels, OneNote's sections): folded or open, as left */
        sideRows: function () {
          var closed = this.sideClosed, byId = {};
          this.cats.forEach(function (c) { byId[c.id] = c; });
          return this.cats.filter(function (c) {
            for (var p = c.parent, seen = 0; p && seen < 50; p = byId[p] && byId[p].parent, seen++) if (closed[p]) return false;
            return true;
          });
        },
        sideToggle: function (id) {
          var o = Object.assign({}, this.sideClosed);
          if (o[id]) delete o[id]; else o[id] = 1;
          this.sideClosed = o; Work.store("work-note-side", o);
        },
        sideHref: function (id) {
          var u = new URL(location.href), keep = u.searchParams.get("sort");
          return (urls().notes || "/work/notes/") + "?" + (id === null ? "" : "category=" + id) + (keep ? (id === null ? "" : "&") + "sort=" + encodeURIComponent(keep) : "");
        },
        // on a phone: the top-level categories, and those inside the one shown (a row of chips)
        chipCats: function () {
          var on = this.category, byId = {};
          this.cats.forEach(function (c) { byId[c.id] = c; });
          var here = typeof on === "number" ? byId[on] : null;
          return this.cats.filter(function (c) { return !c.parent || (here && (c.parent === here.id || c.id === here.id || c.id === here.parent || c.parent === here.parent)); });
        },
        /* its icon (Notion's page icon), chosen right here: saved at once, the card follows */
        edIcon: function (el) {
          var self = this, n = this.ed; if (!n) return;
          Work.pickIcon(el, n.icon).then(function (v) {
            if (v == null || !self.ed || v === n.icon) return;
            n.icon = v;
            Work.api(urls().noteSave, { id: n.id, icon: v, card: "1" }).then(function (r) { if (r && r.ok && r.card) self.swap(n.id, r.card); });
          });
        },
        noteColor: function (c) {
          var n = this.ed; n.color = c;
          Work.api(urls().noteBase + n.id + "/", { action: "color", color: c }).then(function (r) {
            var card = cardOf(n.id); if (card && r && r.ok) Alpine.$data(card).color = c;
          });
        },
        noteAct: function (what) {
          var n = this.ed, self = this;
          Promise.resolve(this.saveNote()).then(function () {
            return Work.api(urls().noteBase + n.id + "/", { action: what, card: "1" });
          }).then(function (r) {
            if (!r || !r.ok) return;
            var card = cardOf(n.id);
            if (what === "pin") {
              n.pinned = r.pinned;                     // the card moves under "Pinned" (or back under "Others")
              var fresh = r.card ? fromHTML(r.card) : null;
              if (card && fresh) card.replaceWith(fresh);
              if (fresh || card) self.place(fresh || card, n.pinned);
              return;
            }
            self.ed = null;
            if (card) card.remove();
            var url = new URL(location.href); url.searchParams.delete("open");
            history.replaceState(history.state, "", url.pathname + url.search);
            if (what === "delete") Work.undoable(t("noteDeleted", "Note deleted"), r.undo, function () { location.reload(); });
            else Work.toast(r.archived ? t("noteArchived", "Archived") : t("noteUnarchived", "Back from the archive"), "good");
          });
        },
      }, urls().noteCategories);
    });

    Alpine.data("noteCard", function (id, pinned, color) {
      return {
        id: id, pinned: pinned, color: color, gone: false,
        // a click on the card (or its title) opens it on the board; Ctrl/⌘/Shift-click or the middle button: the full editor
        go: function (e) {
          if (e.target.closest("button, .wkc-colors, input")) return;
          var link = e.target.closest("a");
          if (link && !link.classList.contains("wnc-title")) return;
          if (e.ctrlKey || e.metaKey || e.shiftKey || e.button === 1) { if (!link) location.href = this.$el.getAttribute("data-url"); return; }
          e.preventDefault();
          if (this.$root.closest(".wnb.is-picking")) { this.$dispatch("note-pick", { id: this.id }); return; }     // picking: a click picks
          this.$dispatch("note-open", { id: this.id, mode: "view" });
        },
        // a to-do on the card: ticked here (and its task, if it became one)
        tick: function (index, el) {
          var on = !el.classList.contains("is-done");
          el.classList.toggle("is-done", on); el.setAttribute("aria-checked", String(on));
          Work.api(urls().noteBase + this.id + "/", { action: "tick", index: index, done: on ? "1" : "0" }).then(function (r) {
            if (!r || (!r.ok && !r.queued)) {
              el.classList.toggle("is-done", !on); el.setAttribute("aria-checked", String(!on));
              if (r && r.error) Work.toast(r.error, "warn");
            }
          });
        },
        // pinned (or not) at once: the card moves to its group straight away, and back if the server says no
        pin: function () {
          var self = this, card = this.$el.closest("[data-note-card]");
          this.pinned = !this.pinned;
          this.$dispatch("note-pin", { card: card, pinned: this.pinned });
          Work.api(urls().noteBase + this.id + "/", { action: "pin" }).then(function (r) {
            if (r && !r.ok && !r.queued) { self.pinned = !self.pinned; self.$dispatch("note-pin", { card: card, pinned: self.pinned }); }
          });
        },
        paint: function (c) {
          var was = this.color, self = this;
          this.color = c;
          Work.api(urls().noteBase + this.id + "/", { action: "color", color: c }).then(function (r) { if (!r || (!r.ok && !r.queued)) self.color = was; });
        },
        act: function (what) {
          var self = this;
          Work.api(urls().noteBase + this.id + "/", { action: what }).then(function (r) {
            if (!r || !r.ok) return;
            self.gone = true;
            if (what === "delete") Work.undoable(t("noteDeleted", "Note deleted"), r.undo, function () { location.reload(); });
            else Work.toast(r.archived ? t("noteArchived", "Archived") : t("noteUnarchived", "Back from the archive"), "good");
          });
        },
      };
    });
  });
})();
