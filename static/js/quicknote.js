/* Quick note, from any page of the site (templates/partials/quick_note.html): the ✎ in the top bar, Alt+N anywhere
   (even while typing), or n on the Productivity pages. A title if you like, the text, the categories — saved to
   Notes with Ctrl+Enter. Nothing is ever lost: what's written is kept on this device as you type (a page change, a
   closed tab, no signal), until it's saved. Loaded before Alpine, as calculator.js. */
(function () {
  "use strict";
  var d = document;
  function csrf() { var m = d.cookie.match(/csrftoken=([^;]+)/); return m ? decodeURIComponent(m[1]) : ""; }
  function recall(k) { try { return JSON.parse(localStorage.getItem(k) || "null"); } catch (e) { return null; } }
  function store(k, v) { try { if (v == null) localStorage.removeItem(k); else localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* private mode */ } }
  function toast(msg, tone) { if (window.FT && FT.toast) FT.toast(msg, tone || "good"); }

  d.addEventListener("alpine:init", function () {
    Alpine.data("quickNote", function () {
      var root = d.getElementById("quick-note"), KEY = "ft-quicknote:" + (d.documentElement.getAttribute("data-user") || "0");
      function T(k) { return root ? root.getAttribute("data-t-" + k) || "" : ""; }
      return {
        open: false, title: "", body: "", cats: [], all: null, picking: false, busy: false, kept: false, last: null, error: "",
        init: function () {
          var self = this, was = recall(KEY);
          if (was) { this.title = was.title || ""; this.body = was.body || ""; this.cats = was.cats || []; }
          window.addEventListener("quick-note", function (e) { self.show(e.detail); });
          d.addEventListener("keydown", function (e) {
            if (e.altKey && !e.ctrlKey && !e.metaKey && e.code === "KeyN") { e.preventDefault(); if (self.open) self.hide(); else self.show(); }
          });
          ["title", "body", "cats"].forEach(function (k) { self.$watch(k, function () { self.keep(); }); });
        },
        get has() { return !!(this.title.trim() || this.body.trim()); },
        get words() { var n = this.body.trim() ? this.body.trim().split(/\s+/).length : 0; return n; },
        show: function (detail) {
          if (detail && detail.text && !this.body.trim()) this.body = detail.text;
          this.open = true; this.error = ""; this.last = null;
          var self = this;
          this.$nextTick(function () { var b = self.$refs.body; if (b) { b.focus(); b.setSelectionRange(b.value.length, b.value.length); self.grow(); } });
          if (!this.all) this.loadCats();
        },
        hide: function () { this.open = false; this.picking = false; if (this.has) toast(T("kept")); },
        keep: function () {
          store(KEY, this.has || this.cats.length ? { title: this.title, body: this.body, cats: this.cats, at: Date.now() } : null);
          this.kept = this.has;
        },
        grow: function () { var b = this.$refs.body; if (!b) return; b.style.height = "auto"; b.style.height = Math.min(b.scrollHeight, innerHeight * 0.45) + "px"; },
        loadCats: function () {
          var self = this;
          fetch(root.getAttribute("data-cats"), { credentials: "same-origin", headers: { Accept: "application/json" } })
            .then(function (r) { return r.ok ? r.json() : null; }).then(function (x) { self.all = (x && x.categories) || []; })
            .catch(function () { self.all = []; });
        },
        catName: function (id) { var c = (this.all || []).filter(function (x) { return x.id === id; })[0]; return c ? c.name : ""; },
        toggleCat: function (id) { var i = this.cats.indexOf(id); if (i >= 0) this.cats.splice(i, 1); else this.cats.push(id); },
        clear: function () { this.title = ""; this.body = ""; this.cats = []; store(KEY, null); this.kept = false; },
        save: function (thenOpen) {
          var self = this;
          if (!this.has || this.busy) { if (!this.has && this.$refs.body) this.$refs.body.focus(); return; }
          this.busy = true; this.error = "";
          var f = new FormData();
          f.append("title", this.title.trim()); f.append("body", this.body); f.append("categories", this.cats.join(","));
          fetch(root.getAttribute("data-save"), { method: "POST", body: f, credentials: "same-origin",
                                                   headers: { "X-CSRFToken": csrf(), "X-Requested-With": "fetch", Accept: "application/json" } })
            .then(function (r) { return r.json().catch(function () { return { ok: r.ok }; }); })
            .then(function (res) {
              self.busy = false;
              if (!res || !res.ok) { self.error = (res && res.error) || T("notSaved"); return; }
              self.clear(); self.last = { url: res.url, title: res.title };
              if (thenOpen && res.url) { location.href = res.url; return; }
              self.open = false;
              toast("✓ " + T("saved") + ": " + (res.title || ""));
              d.dispatchEvent(new CustomEvent("work:note-added", { detail: res }));
            })
            .catch(function () { self.busy = false; self.error = T("offline"); });
        },
      };
    });
  });
}());
