/* The notes board (Productivity → Notes, nothing open): notes as cards, like
   Google Keep. "Take a note…" opens into a title and a note; it's saved on
   Ctrl+Enter, on Save, or when you click away (an empty one is dropped), and
   the new card goes to the top. On a card: pin, colour, archive, delete; a
   click anywhere else opens the note in the editor. Loaded after work.js. */
(function () {
  "use strict";
  var d = document;
  function urls() { return Work.cfg.urls; }
  function t(key, fallback) { return (Work.cfg.text || {})[key] || fallback; }

  document.addEventListener("alpine:init", function () {
    Alpine.data("noteBoard", function () {
      var DRAFT = "work-note-quick";
      return {
        open: false, title: "", body: "", color: "", pinned: false, saving: false,
        init: function () {
          var self = this, saved = Work.recall(DRAFT, null);           // what was being written when the page closed
          if (saved && (saved.title || saved.body)) { Object.assign(this, saved); this.open = true; }
          ["title", "body", "color", "pinned"].forEach(function (k) { self.$watch(k, function () { self.keep(); }); });
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
          Work.api(urls().noteSave, { title: this.title.trim(), body: this.body, color: this.color, pinned: this.pinned ? "1" : "" }).then(function (r) {
            self.saving = false;
            if (!r || !r.ok) { if (!(r && r.queued)) Work.toast(t("notSaved", "Not saved."), "warn"); return; }
            self.addCard(r);
            self.title = ""; self.body = ""; self.color = ""; self.pinned = false;
            Work.store(DRAFT, null);
            if (again) self.$nextTick(function () { self.$refs.body.focus(); }); else self.open = false;
            Work.toast(t("noteSaved", "Note saved"), "good");
          });
        },
        addCard: function (r) {
          var card = this.$refs.cardTpl.content.firstElementChild.cloneNode(true), grid = this.$refs.grid;
          card.setAttribute("x-data", "noteCard(" + Number(r.id) + ", " + (this.pinned ? "true" : "false") + ", '" + (this.color || "").replace(/[^a-z]/g, "") + "')");
          card.setAttribute("data-url", r.url);
          var a = card.querySelector(".wnc-title");
          a.href = r.url; a.textContent = r.title;
          var body = this.body.trim(), lines = this.title.trim() ? body : body.split("\n").slice(1).join("\n").trim();
          card.querySelector(".wnc-body").textContent = lines.slice(0, 420);
          var none = grid.querySelector(".wnb-none");
          if (none) none.remove();
          // Under its heading: "Pinned" for a pinned one, "Others" for the rest; at the top when there are no headings.
          var head = grid.querySelector(this.pinned ? '[data-head="pinned"]' : '[data-head="others"]');
          if (head) head.after(card);
          else if (!this.pinned && grid.querySelector('[data-head="pinned"]')) grid.append(card);
          else grid.prepend(card);
        },
      };
    });

    Alpine.data("noteCard", function (id, pinned, color) {
      return {
        id: id, pinned: pinned, color: color, gone: false,
        go: function (e) {
          if (e.target.closest("a, button, .wkc-colors")) return;
          location.href = this.$el.getAttribute("data-url");
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
