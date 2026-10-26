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
      var DRAFT = "work-note-quick";
      return {
        open: false, title: "", body: "", color: "", pinned: false, saving: false,
        ed: null, edPreview: false, edState: "saved", edTimer: null, edSending: null, edAgain: false, edSaved: "", finding: null,
        init: function () {
          var self = this, saved = Work.recall(DRAFT, null);           // what was being written when the page closed
          if (saved && (saved.title || saved.body)) { Object.assign(this, saved); this.open = true; }
          ["title", "body", "color", "pinned"].forEach(function (k) { self.$watch(k, function () { self.keep(); }); });
          this.$watch("ed", function () { self.edChanged(); }, { deep: true });
          d.addEventListener("note-open", function (e) { self.openNote(e.detail.id); });
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
          Work.api(urls().noteSave, { title: this.title.trim(), body: this.body, color: this.color, pinned: this.pinned ? "1" : "", card: "1" }).then(function (r) {
            self.saving = false;
            if (!r || !r.ok) { if (!(r && r.queued)) Work.toast(t("notSaved", "Not saved."), "warn"); return; }
            if (r.card) self.place(fromHTML(r.card), self.pinned);
            self.title = ""; self.body = ""; self.color = ""; self.pinned = false;
            Work.store(DRAFT, null);
            if (again) self.$nextTick(function () { self.$refs.body.focus(); }); else self.open = false;
            Work.toast(t("noteSaved", "Note saved"), "good");
          });
        },
        // A card under its heading: "Pinned" for a pinned one, "Others" for the rest; at the top when there are no headings.
        place: function (card, pinned) {
          var grid = this.$refs.grid, none = grid.querySelector(".wnb-none");
          if (none) none.remove();
          var head = grid.querySelector(pinned ? '[data-head="pinned"]' : '[data-head="others"]');
          if (head) head.after(card);
          else if (!pinned && grid.querySelector('[data-head="pinned"]')) grid.append(card);
          else grid.prepend(card);
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
        openNote: function (id) {
          var self = this;
          this.flushNote();
          fetch(urls().noteBase + id + "/get/", { credentials: "same-origin", headers: { Accept: "application/json" } })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (n) {
              if (!n || !n.ok) { location.href = (urls().notes || "/work/notes/") + id + "/"; return; }
              self.edSaved = JSON.stringify([n.title, n.body]);
              self.ed = { id: n.id, title: n.title, body: n.body, color: n.color, pinned: n.pinned, url: n.url, archived: n.archived };
              self.edState = "saved"; self.edPreview = false;
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
          clearTimeout(this.edTimer);
          this.edTimer = setTimeout(function () { self.saveNote(); }, 700);
        },
        saveNote: function () {
          var self = this, n = this.ed;
          clearTimeout(this.edTimer);
          if (!n || this.edState !== "dirty") return this.edSending || Promise.resolve();
          if (this.edSending) { this.edAgain = true; return this.edSending; }       // one save at a time
          this.edState = "saving";
          var sent = { title: n.title, body: n.body };
          this.edSending = Work.api(urls().noteSave, { id: n.id, title: n.title, body: n.body, card: "1" }).then(function (r) {
            self.edSending = null;
            if (!r || !r.ok) { if (self.ed === n) self.edState = r && r.queued ? "offline" : "error"; return; }
            self.swap(n.id, r.card);
            if (self.ed === n) { self.edSaved = JSON.stringify([sent.title, sent.body]); self.edState = n.title === sent.title && n.body === sent.body ? "saved" : "dirty"; }
            if (self.edAgain || (self.ed === n && self.edState === "dirty")) { self.edAgain = false; self.saveNote(); }
          });
          return this.edSending;
        },
        flushNote: function () { if (this.ed && this.edState === "dirty") this.saveNote(); },
        swap: function (id, html) {
          var old = cardOf(id);
          if (old && html) old.replaceWith(fromHTML(html));
        },
        closeNote: function () {
          var id = this.ed && this.ed.id;
          this.flushNote();
          this.ed = null;
          var url = new URL(location.href); url.searchParams.delete("open");
          history.replaceState(history.state, "", url.pathname + url.search);
          var card = id && cardOf(id); if (card) card.scrollIntoView({ block: "nearest" });
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
              if (card) card.remove();
              if (r.card) self.place(fromHTML(r.card), n.pinned);
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
      };
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
          this.$dispatch("note-open", { id: this.id });
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
        pin: function () {
          var self = this;
          this.pinned = !this.pinned;
          Work.api(urls().noteBase + this.id + "/", { action: "pin" }).then(function (r) { if (r && r.ok) self.pinned = r.pinned; });
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
