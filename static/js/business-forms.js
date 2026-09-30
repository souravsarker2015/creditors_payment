/* Business module: add/remove line rows in a Django formset, and share a
   newly created option (e.g. a deduction type) with every row's dropdown.
   Removed new rows simply leave a gap: Django ignores empty extra forms. */
document.addEventListener("alpine:init", function () {
  Alpine.data("formRows", function (prefix) {
    var root;   // the section itself: `this.$el` is whichever element fired the event
    return {
      // Not called "total": the sale/purchase totals around these rows have a `total` of their own.
      totalForms() { return document.getElementById("id_" + prefix + "-TOTAL_FORMS"); },
      // `prep(row)` fills the new row in before Alpine starts it, so its own
      // x-data (e.g. a deduction's method) begins from those values.
      add(prep) {
        var total = this.totalForms(), i = parseInt(total.value, 10);
        var html = this.$refs.tpl.innerHTML.replace(/__prefix__/g, i);
        var wrap = document.createElement("div");
        wrap.innerHTML = html.trim();
        var row = wrap.firstElementChild;
        if (typeof prep === "function") prep(row);
        this.$refs.list.appendChild(row);
        total.value = i + 1;
        var first = row.querySelector("select, input:not([type=hidden])");
        if (first && !this.silent) first.focus();
        this.$dispatch("row-added", { row: row });
        return row;
      },
      init() {
        root = this.$el;
        // "+ New …" created an option: add it to every row and to the row template.
        window.addEventListener("new-option", (e) => {
          var d = e.detail;
          if (!d || !d.value) return;
          var name = d.field || "deduction_type";      // which dropdown of the rows it belongs in
          var tpl = this.$refs.tpl, inTpl = new RegExp('(<select[^>]*-' + name + '"[^>]*>)');
          if (!inTpl.test(tpl.innerHTML)) return;      // these rows have no such dropdown
          var selects = Array.from(root.querySelectorAll("select[name$='-" + name + "']"));
          selects.forEach(function (sel) {
            if (!Array.from(sel.options).some(function (o) { return o.value === d.value; })) sel.add(new Option(d.text, d.value));
          });
          tpl.innerHTML = tpl.innerHTML.replace(inTpl, '$1<option value="' + d.value + '">' + d.text.replace(/</g, "&lt;") + "</option>");
          var empty = selects.filter(function (s) { return !s.value && !s.closest("template"); });
          if (!empty.length) { this.add(); empty = [this.$refs.list.lastElementChild.querySelector("select[name$='-" + name + "']")]; }
          empty[0].value = d.value;
          empty[0].dispatchEvent(new Event("change", { bubbles: true }));   // totals, default unit and last price follow
        });
      },
    };
  });
});

/* Searchable multi-selects (e.g. a feed's suppliers). */
document.addEventListener("DOMContentLoaded", function () {
  document.querySelectorAll("select[data-multi]").forEach(function (el) { if (window.FT) FT.multiSelect(el.id, el.getAttribute("data-placeholder") || ""); });
});


/* Live totals for a purchase ("feed") or a fish sale ("sale") form.
   Reads the rows straight from the page, so added/removed rows just work. */
document.addEventListener("alpine:init", function () {
  Alpine.data("docTotals", function (data, mode) {
    var num = function (v) { var n = parseFloat(v); return isNaN(n) ? 0 : n; };
    var root;   // the form itself: in a method, `this.$el` is whichever element called it (a chip, a wrapper)
    return {
      data: data, mode: mode,
      kg: 0, subtotal: 0, extra: 0, less: 0, total: 0, paid: 0, due: 0,
      gross: 0, deductions: 0, net: 0,
      init() {
        root = this.$el;
        // A feed created with "+ New feed": remember its bag size and price for the totals.
        window.addEventListener("quick-added", (e) => {
          var d = e.detail || {};
          if (d.kind === "feed" && this.data.products) this.data.products[d.id] = d.extra || {};
          if (d.kind === "species" && this.data.species) this.data.species[d.id] = d.extra || {};
        });
        this.$nextTick(() => {
          if (this.mode === "sale") this.rows(".sale-line").forEach((row) => this.autoSaleRate(row));
          this.calc();
        });
      },
      field(row, name) { return row.querySelector("[name$='-" + name + "']"); },
      rows(sel) { return Array.from(root.querySelectorAll(sel)).filter(function (r) { return !r.closest("template") && r.dataset.gone !== "true" && r.offsetParent !== null; }); },
      money(n) { return "৳" + (Math.round(n * 100) / 100).toLocaleString("en-IN", { maximumFractionDigits: 2 }); },
      fmtNum(n) { return (Math.round(n * 10) / 10).toLocaleString("en-IN", { maximumFractionDigits: 1 }); },
      setPaid(v) { var el = root.querySelector("[name=paid_now], [name=received_now]"); if (el) { el.value = v ? Math.round(v * 100) / 100 : ""; } this.calc(); },
      // Fill the rate from the feed's usual price (per bag, or per kg/mon…) unless the user typed one.
      autoRate(row) {
        var p = this.data.products[(this.field(row, "product") || {}).value];
        var rate = this.field(row, "rate");
        if (!p || !p.price || !rate || (rate.value && rate.dataset.auto !== "1")) return;
        var unit = this.data.units[this.field(row, "unit").value];
        var v = unit ? num(p.price) / num(p.bag_kg) * num(unit.factor) : num(p.price);
        rate.value = Math.round(v * 100) / 100; rate.dataset.auto = "1";
      },
      // A sale line: start from the last price this fish sold for (at this market if it has
      // sold there, else anywhere), in the unit chosen, unless the user typed a rate.
      autoSaleRate(row) {
        var rates = this.data.rates || {}, sp = (this.field(row, "species") || {}).value;
        var unit = this.data.units[(this.field(row, "unit") || {}).value];
        var market = (root.querySelector("[name=market]") || {}).value || "0";
        var last = sp && unit ? (rates[sp + ":" + market + ":" + unit.type] || rates[sp + ":*:" + unit.type]) : null;
        var hint = row.querySelector("[data-rate-hint]"), rate = this.field(row, "rate");
        var value = last ? Math.round(num(last.per_base) * num(unit.factor) * 100) / 100 : 0;
        if (hint) hint.textContent = last ? (this.data.text.last || "").replace("{rate}", this.money(value)).replace("{unit}", unit.symbol)
          .replace("{date}", last.date + (last.market ? " · " + last.market : "")) : "";
        if (!last || !rate || (rate.value && rate.dataset.auto !== "1")) return;
        rate.value = value; rate.dataset.auto = "1";
      },
      calc(e) {
        var self = this;
        if (e && e.target && e.target.name && /-rate$/.test(e.target.name) && e.type === "input") e.target.dataset.auto = "0";
        if (this.mode === "feed") {
          var kg = 0, sub = 0;
          this.rows(".doc-line").forEach(function (row) {
            if (e && e.type === "change" && row.contains(e.target) && /-(product|unit)$/.test(e.target.name)) self.autoRate(row);
            var q = num(self.field(row, "quantity").value), rate = num(self.field(row, "rate").value);
            var p = self.data.products[self.field(row, "product").value], unit = self.data.units[self.field(row, "unit").value];
            var lineKg = p ? q * (unit ? num(unit.factor) : num(p.bag_kg)) : 0;
            kg += lineKg; sub += q * rate;
            row.querySelector("[data-line-amount]").textContent = q && rate ? self.money(q * rate) : "";
            row.querySelector("[data-line-kg]").textContent = lineKg ? self.fmtNum(lineKg) + " kg" : "";
            var per = row.querySelector("[data-rate-per]"); if (per) per.textContent = "/ " + (unit ? unit.symbol : (self.data.bagWord || "bag"));
          });
          this.kg = kg; this.subtotal = sub;
          this.extra = num((root.querySelector("[name=transport]") || {}).value);
          this.less = num((root.querySelector("[name=discount]") || {}).value);
          this.total = Math.max(sub + this.extra - this.less, 0);
          this.paid = num((root.querySelector("[name=paid_now]") || {}).value);
          this.due = Math.max(this.total - this.paid, 0);
          return;
        }
        // sale
        var gross = 0, base = {};   // base[unit_type] = total in base units
        this.rows(".sale-line").forEach(function (row) {
          var q = num(self.field(row, "quantity").value), rate = num(self.field(row, "rate").value);
          var unit = self.data.units[self.field(row, "unit").value];
          if (e && e.type === "change" && row.contains(e.target) && /-species$/.test(e.target.name)) {
            var sp = self.data.species[e.target.value]; var u = self.field(row, "unit");
            if (sp && sp.unit && !self.field(row, "quantity").value) u.value = sp.unit;
          }
          if (e && e.type === "change" && (e.target.name === "market" || (row.contains(e.target) && /-(species|unit)$/.test(e.target.name)))) self.autoSaleRate(row);
          gross += q * rate;
          if (unit) base[unit.type] = (base[unit.type] || 0) + q * num(unit.factor);
          row.querySelector("[data-line-amount]").textContent = q && rate ? self.money(q * rate) : "";
          var per = row.querySelector("[data-rate-per]"); if (per && unit) per.textContent = "/ " + unit.symbol;
        });
        var ded = 0;
        this.rows(".ded-line").forEach(function (row) {
          var method = self.field(row, "method").value, value = num(self.field(row, "value").value), amount = 0;
          if (method === "percent") amount = gross * value / 100;
          else if (method === "fixed") amount = value;
          else { var u = self.data.units[(self.field(row, "unit") || {}).value]; if (u) amount = value * (base[u.type] || 0) / num(u.factor); }
          ded += amount;
          row.querySelector("[data-line-amount]").textContent = amount ? "− " + self.money(amount) : "";
        });
        this.gross = gross; this.deductions = ded; this.net = gross - ded;
        this.paid = num((root.querySelector("[name=received_now]") || {}).value);
        this.due = Math.max(this.net - this.paid, 0); this.total = this.net;
      },
      // Buyer chosen while the market is still empty: use the buyer's usual market.
      applyBuyer(id) {
        var market = (this.data.buyers || {})[id], sel = root.querySelector("[name=market]");
        if (!market || !sel || sel.value) return;
        sel.value = String(market);
        if (sel.value !== String(market)) return;   // that market is no longer in the list
        if (sel.tomselect) sel.tomselect.setValue(String(market), true);
        this.applyMarket(String(market));
        this.rows(".sale-line").forEach((row) => this.autoSaleRate(row));   // prices can differ by market
      },
      // Market chosen: replace the deductions that haven't been saved yet with its usual ones.
      applyMarket(id) {
        var list = this.data.markets[id]; var box = root.querySelector("[data-rows='ded']");
        if (!box || !list) return;
        var rows = Alpine.$data(box);
        box.querySelectorAll(".ded-line").forEach(function (r) {
          if (r.closest("template")) return;
          var del = r.querySelector("[name$='-DELETE']");
          if (del) { del.checked = true; del.dispatchEvent(new Event("change")); } else r.remove();
        });
        rows.silent = true;
        list.forEach(function (d) {
          rows.add(function (row) {
            // The row's x-data holds the method; set it there, or Alpine resets the select to "fixed".
            row.setAttribute("x-data", row.getAttribute("x-data").replace(/method: '[^']*'/, "method: '" + d.method + "'"));
            row.querySelector("[name$='-deduction_type']").value = d.type;
            row.querySelector("[name$='-value']").value = d.value;
            if (d.unit) row.querySelector("[name$='-unit']").value = d.unit;
          });
        });
        rows.silent = false;
        this.$nextTick(() => this.calc());
      },
    };
  });
});
