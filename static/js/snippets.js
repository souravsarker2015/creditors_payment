/* Snippets: copy in one tap. A snippet can have blanks to fill in before it's
   copied — ${1:container} (as in VS Code snippets) or {{container}}, with a
   default as {{branch:main}}. The values are kept in this browser for the
   next time; a blank left empty keeps its text. Pages further down come in
   as the list scrolls (static/js/infinite.js), highlighted like the first. */
(function () {
  "use strict";
  var d = document;
  var BLANK = /\$\{(\d+):([^}\n]+)\}|\{\{([A-Za-z_][\w-]*)(?::([^}\n]*))?\}\}/g;

  function blanks(code) {
    var seen = {}, out = [];
    code.replace(BLANK, function (all, n, label, name, fallback) {
      var key = (label || name).trim();
      if (!seen[key]) { seen[key] = true; out.push({ key: key, fallback: fallback || "" }); }
      return all;
    });
    return out;
  }
  function highlight(root) {
    if (window.hljs) root.querySelectorAll(".wsn-code code:not(.hljs)").forEach(function (c) { hljs.highlightElement(c); });
  }
  d.addEventListener("DOMContentLoaded", function () { highlight(d); });
  d.addEventListener("ft:more", function (e) { e.detail.rows.forEach(function (row) { if (row.nodeType === 1) highlight(row); }); });

  d.addEventListener("alpine:init", function () {
    Alpine.data("snippet", function (id, url, fav, open) {
      var KEY = "work-snippet-fill:" + id;
      return {
        fav: fav, open: open, filling: false, values: {}, done: false,
        card: null,
        init: function () { this.card = this.$el; },          // (inside the ⋮ menu, $root is the menu)
        get code() { var c = this.card && this.card.querySelector(".wsn-code code"); return c ? c.textContent : ""; },
        get fields() { return blanks(this.code); },
        star: function () { this.fav = !this.fav; Work.api(url, { action: "favorite" }); },
        copy: function () {
          var fields = this.fields;
          if (!fields.length) return this.send(this.code);
          if (this.filling) return this.copyFilled();
          var kept = Work.recall(KEY, {}) || {}, self = this;
          this.values = {};
          fields.forEach(function (f) { self.values[f.key] = kept[f.key] != null ? kept[f.key] : f.fallback; });
          this.filling = true; this.open = true;
          this.$nextTick(function () { var first = self.card.querySelector(".wsn-fill input"); if (first) { first.focus(); first.select(); } });
        },
        filled: function () {
          var values = this.values;
          return this.code.replace(BLANK, function (all, n, label, name) {
            var v = values[(label || name).trim()];
            return v ? v : all;
          });
        },
        copyFilled: function () {
          Work.store(KEY, this.values);
          this.send(this.filled());
          this.filling = false;
        },
        send: function (text) {
          var self = this;
          var done = function () {
            Work.toast((Work.cfg.text || {}).copied || "Copied");
            self.done = true; setTimeout(function () { self.done = false; }, 1200);
            Work.api(url, { action: "copied" });
          };
          if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(done, function () { FT.showText(text); });
          else FT.showText(text);
        },
        remove: function () {
          var self = this, msg = this.$el.getAttribute("data-deleted");
          Work.api(url, { action: "delete" }).then(function (r) { self.card.remove(); Work.undoable(msg, r.undo); });
        },
      };
    });
  });
})();
