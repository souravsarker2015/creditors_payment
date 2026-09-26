/* Business module: add/remove line rows in a Django formset, and share a
   newly created option (e.g. a deduction type) with every row's dropdown.
   Removed new rows simply leave a gap: Django ignores empty extra forms. */
document.addEventListener("alpine:init", function () {
  Alpine.data("formRows", function (prefix) {
    return {
      total() { return document.getElementById("id_" + prefix + "-TOTAL_FORMS"); },
      add() {
        var total = this.total(), i = parseInt(total.value, 10);
        var html = this.$refs.tpl.innerHTML.replace(/__prefix__/g, i);
        var wrap = document.createElement("div");
        wrap.innerHTML = html.trim();
        var row = wrap.firstElementChild;
        this.$refs.list.appendChild(row);
        total.value = i + 1;
        var first = row.querySelector("select, input:not([type=hidden])");
        if (first) first.focus();
      },
      init() {
        // "+ New …" created an option: add it to every row and to the row template.
        window.addEventListener("new-option", (e) => {
          var d = e.detail;
          if (!d || !d.value) return;
          var selects = Array.from(this.$el.querySelectorAll("select[name$='-deduction_type']"));
          selects.forEach(function (sel) {
            if (!Array.from(sel.options).some(function (o) { return o.value === d.value; })) sel.add(new Option(d.text, d.value));
          });
          var tpl = this.$refs.tpl;
          tpl.innerHTML = tpl.innerHTML.replace(/(<select[^>]*-deduction_type"[^>]*>)/, '$1<option value="' + d.value + '">' + d.text.replace(/</g, "&lt;") + "</option>");
          var empty = selects.filter(function (s) { return !s.value && !s.closest("template"); });
          if (!empty.length) { this.add(); empty = [this.$refs.list.lastElementChild.querySelector("select[name$='-deduction_type']")]; }
          empty[0].value = d.value;
        });
      },
    };
  });
});

/* Searchable multi-selects (e.g. a feed's suppliers). */
document.addEventListener("DOMContentLoaded", function () {
  document.querySelectorAll("select[data-multi]").forEach(function (el) { if (window.FT) FT.multiSelect(el.id, el.getAttribute("data-placeholder") || ""); });
});
