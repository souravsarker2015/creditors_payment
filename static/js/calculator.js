/* FinTrack calculator
   --------------------------------------------------------------------------
   One floating calculator for every page (templates/partials/calculator.html).
   - Expression engine: a tiny recursive-descent parser, no eval(). Percent
     follows the business-calculator convention: `500 + 15%` = 575,
     `500 - 10%` = 450, `2000 × 5%` = 100, a lone `15%` = 0.15.
   - History: kept in this browser only, per user, for HISTORY_DAYS, capped at
     HISTORY_MAX entries, and wiped on logout (see base.html).
   - "Insert" writes the result into the amount field you last focused.
   ========================================================================== */
(function () {
  "use strict";

  var HISTORY_MAX = 30;
  var HISTORY_DAYS = 7;
  var POS_KEY = "ft-calc-pos";

  function round(n, dp) {
    var f = Math.pow(10, dp);
    return Math.round((n + Number.EPSILON) * f) / f;
  }

  // ---- expression engine --------------------------------------------------
  function tokenize(src) {
    var s = src.replace(/,/g, "").replace(/[×xX*]/g, "*").replace(/[÷/]/g, "/").replace(/[−–]/g, "-");
    var out = [], i = 0;
    while (i < s.length) {
      var c = s[i];
      if (c === " ") { i++; continue; }
      if (/[0-9.]/.test(c)) {
        var j = i;
        while (j < s.length && /[0-9.]/.test(s[j])) j++;
        var raw = s.slice(i, j);
        if ((raw.match(/\./g) || []).length > 1 || raw === ".") throw new Error("syntax");
        out.push({ t: "num", v: parseFloat(raw) });
        i = j; continue;
      }
      if ("+-*/%()".indexOf(c) !== -1) { out.push({ t: c }); i++; continue; }
      throw new Error("syntax");
    }
    return out;
  }

  function evaluate(src) {
    var toks = tokenize(src), p = 0;
    if (!toks.length) throw new Error("empty");
    function peek() { return toks[p] && toks[p].t; }

    // expr := term (('+'|'-') term)*   — `a + b%` means a + a·b/100
    function expr() {
      var left = term().v;
      while (peek() === "+" || peek() === "-") {
        var op = toks[p++].t, r = term();
        var rv = r.pct ? left * r.v : r.v;
        left = op === "+" ? left + rv : left - rv;
      }
      return left;
    }
    // term := unary (('*'|'/') unary)*  — pct flags a bare `b%` term
    function term() {
      var f = unary(), v = f.v, pct = f.pct;
      while (peek() === "*" || peek() === "/") {
        var op = toks[p++].t, r = unary().v;
        if (op === "/" && r === 0) throw new Error("div0");
        v = op === "*" ? v * r : v / r;
        pct = false;
      }
      return { v: v, pct: pct };
    }
    function unary() {
      if (peek() === "-") { p++; var u = unary(); return { v: -u.v, pct: u.pct }; }
      if (peek() === "+") { p++; return unary(); }
      var v = primary(), pct = false;
      while (peek() === "%") { p++; v = v / 100; pct = true; }
      return { v: v, pct: pct };
    }
    function primary() {
      var t = toks[p++];
      if (!t) throw new Error("syntax");
      if (t.t === "num") return t.v;
      if (t.t === "(") {
        var v = expr();
        if (peek() === ")") p++; // tolerate a missing closing bracket
        return v;
      }
      throw new Error("syntax");
    }

    var result = expr();
    if (p < toks.length) throw new Error("syntax");
    if (!isFinite(result)) throw new Error("div0");
    return round(result, 10);
  }

  // Best-effort preview while typing: ignore a dangling operator/bracket.
  function preview(src) {
    var s = src.trim();
    while (s && /[+\-×÷*/xX(−]$/.test(s)) s = s.slice(0, -1).trim();
    if (!s) return null;
    try { return evaluate(s); } catch (e) { return null; }
  }

  function fmt(n, dp) {
    if (n === null || n === undefined || !isFinite(n)) return "";
    return Number(n).toLocaleString("en-US", { maximumFractionDigits: dp === undefined ? 6 : dp });
  }
  function money(n) { return "৳" + fmt(n, 2); }

  // ---- amount-field targeting ----------------------------------------------
  var lastField = null;
  function isAmountField(el) {
    return el && el.tagName === "INPUT" && !el.closest(".calc") && !el.disabled && !el.readOnly &&
      (el.type === "number" || el.inputMode === "decimal");
  }
  document.addEventListener("focusin", function (e) {
    if (isAmountField(e.target)) lastField = e.target;
  });
  function fieldLabel(el) {
    var label = el.id && document.querySelector('label[for="' + el.id + '"]');
    var text = label ? label.textContent : (el.getAttribute("aria-label") || el.name || "");
    return text.replace(/\(.*?\)|\*/g, "").replace(/\s+/g, " ").trim();
  }

  window.FTCalc = { evaluate: evaluate }; // exposed for quick console checks

  document.addEventListener("alpine:init", function () {
    Alpine.data("calculator", function (cfg) {
      return {
        open: false,
        tab: "calc",
        expr: "",
        result: null,   // last "=" result, shown big until the expression changes
        error: "",
        history: [],
        target: null,
        targetLabel: "",
        tool: "discount",
        t: {            // tool inputs
          price: "", off: "",
          vatAmount: "", vatRate: "15", vatMode: "add",
          cost: "", sell: "",
          splitTotal: "", people: "2",
          principal: "", rate: "", months: "12",
        },
        pos: null,
        savedPos: false,
        key: "ft-calc-history:" + cfg.user,

        init() {
          this.loadHistory();
          try { this.pos = JSON.parse(localStorage.getItem(POS_KEY) || "null"); } catch (e) { this.pos = null; }
          this.savedPos = !!this.pos;
          var self = this;
          window.addEventListener("keydown", function (e) {
            if (e.altKey && !e.ctrlKey && !e.metaKey && e.code === "KeyC") { e.preventDefault(); self.toggle(); }
          });
          window.addEventListener("resize", function () { self.clampPos(); });
        },

        // ---- open / close ----
        toggle() { this.open ? this.close() : this.show(); },
        show() {
          this.target = isAmountField(lastField) && document.body.contains(lastField) ? lastField : null;
          this.targetLabel = this.target ? fieldLabel(this.target) : "";
          this.open = true;
          this.loadHistory();
          this.$nextTick(() => {
            this.avoidTarget();
            this.clampPos();
            if (this.tab === "calc" && this.$refs.expr) this.$refs.expr.focus({ preventScroll: true });
          });
        },
        close() { this.open = false; },
        get isSheet() { return window.matchMedia("(max-width: 639.98px)").matches; },

        // ---- keypad ----
        get live() { return this.error ? null : preview(this.expr); },
        get display() {
          if (this.error) return this.error;
          if (this.result !== null) return fmt(this.result);
          var v = this.live;
          return v === null ? "" : fmt(v);
        },
        press(k) {
          this.error = "";
          if (k === "AC") { this.expr = ""; this.result = null; return this.focusExpr(); }
          if (k === "back") { this.expr = this.expr.replace(/\s*[+−×÷]\s*$|.$/, ""); this.result = null; return this.focusExpr(); }
          if (k === "=") return this.equals();
          var isOp = "+−×÷%".indexOf(k) !== -1;
          if (this.result !== null) {
            // after "=": an operator continues from the answer, a digit starts fresh
            this.expr = isOp && k !== "%" ? fmt(this.result).replace(/,/g, "") : "";
            this.result = null;
          }
          if (isOp && k !== "%" && /[+−×÷]\s*$/.test(this.expr)) this.expr = this.expr.replace(/[+−×÷]\s*$/, "");
          if (isOp && k !== "%" && !this.expr && k !== "−") return this.focusExpr();
          this.expr += isOp && k !== "%" ? " " + k + " " : k;
          this.focusExpr();
        },
        focusExpr() {
          var el = this.$refs.expr;
          if (el && !this.isSheet) { el.focus({ preventScroll: true }); el.setSelectionRange(el.value.length, el.value.length); }
        },
        onType(e) {
          // keep the field to calculator characters; show × ÷ − as the user types * / -
          var v = e.target.value.replace(/\*/g, "×").replace(/\//g, "÷").replace(/-/g, "−").replace(/[^0-9.,+−×÷%() xX]/g, "");
          this.expr = v; this.result = null; this.error = "";
        },
        onKey(e) {
          if (e.key === "Enter" || e.key === "=") { e.preventDefault(); this.equals(); }
          else if (e.key === "Escape") { e.preventDefault(); this.close(); }
        },
        equals() {
          if (!this.expr.trim()) return;
          try {
            var v = evaluate(this.expr);
            this.addHistory(this.expr.replace(/\s*([+−×÷*/xX])\s*/g, " $1 ").replace(/[*xX]/g, "×").replace(/\//g, "÷").trim(), v);
            this.result = v;
          } catch (err) {
            this.error = err.message === "div0" ? cfg.i18n.div0 : cfg.i18n.invalid;
          }
        },

        // ---- the answer: copy / insert ----
        get answer() {
          if (this.result !== null) return this.result;
          return this.live;
        },
        copy(v) {
          var text = String(round(v, 2));
          if (navigator.clipboard) navigator.clipboard.writeText(text).then(function () { FT.toast(cfg.i18n.copied + " " + text); });
        },
        insert(v) {
          if (!this.target || v === null || v === undefined) return;
          var val = round(v, 2);
          var el = this.target;
          el.value = val;
          el.dispatchEvent(new Event("input", { bubbles: true }));
          el.dispatchEvent(new Event("change", { bubbles: true }));
          el.classList.add("just-added");
          setTimeout(function () { el.classList.remove("just-added"); }, 1200);
          FT.toast(cfg.i18n.inserted.replace("{value}", fmt(val, 2)).replace("{field}", this.targetLabel));
          if (this.isSheet) this.close();
          else el.focus({ preventScroll: false });
        },

        // ---- history (this browser, this user, temporary) ----
        loadHistory() {
          var cutoff = Date.now() - HISTORY_DAYS * 864e5;
          try {
            var raw = JSON.parse(localStorage.getItem(this.key) || "[]");
            this.history = Array.isArray(raw) ? raw.filter(function (h) { return h && h.at > cutoff; }) : [];
          } catch (e) { this.history = []; }
        },
        saveHistory() {
          try { localStorage.setItem(this.key, JSON.stringify(this.history)); } catch (e) { /* storage off: session-only */ }
        },
        addHistory(expr, value, label) {
          if (this.history[0] && this.history[0].expr === expr && this.history[0].value === value) return;
          this.history.unshift({ expr: expr, value: value, label: label || "", at: Date.now() });
          this.history = this.history.slice(0, HISTORY_MAX);
          this.saveHistory();
        },
        removeHistory(i) { this.history.splice(i, 1); this.saveHistory(); },
        clearHistory() { this.history = []; this.saveHistory(); },
        reuse(h) { this.tab = "calc"; this.expr = h.expr; this.result = null; this.error = ""; this.$nextTick(() => this.focusExpr()); },
        useValue(v) { this.tab = "calc"; this.expr = String(round(v, 2)); this.result = null; this.error = ""; this.$nextTick(() => this.focusExpr()); },
        when(ts) {
          var d = new Date(ts), now = new Date();
          var time = d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
          return d.toDateString() === now.toDateString() ? time : d.toLocaleDateString([], { day: "numeric", month: "short" }) + ", " + time;
        },

        // ---- business tools ----
        num(v) { var n = parseFloat(String(v).replace(/,/g, "")); return isFinite(n) ? n : null; },
        get rows() {
          var t = this.t, n = this.num.bind(this), L = cfg.i18n.tools;
          switch (this.tool) {
            case "discount": {
              var p = n(t.price), o = n(t.off);
              if (p === null || o === null) return [];
              var d = p * o / 100;
              return [{ k: L.saved, v: d }, { k: L.payable, v: p - d, main: true }];
            }
            case "vat": {
              var a = n(t.vatAmount), r = n(t.vatRate);
              if (a === null || r === null) return [];
              if (t.vatMode === "add") {
                var tax = a * r / 100;
                return [{ k: L.tax, v: tax }, { k: L.withTax, v: a + tax, main: true }];
              }
              var net = a / (1 + r / 100);
              return [{ k: L.tax, v: a - net }, { k: L.beforeTax, v: net, main: true }];
            }
            case "profit": {
              var c = n(t.cost), s = n(t.sell);
              if (c === null || s === null) return [];
              var pr = s - c;
              var out = [{ k: pr >= 0 ? L.profit : L.loss, v: Math.abs(pr), main: true, tone: pr >= 0 ? "good" : "critical" }];
              if (s) out.push({ k: L.margin, v: pr / s * 100, pct: true });
              if (c) out.push({ k: L.markup, v: pr / c * 100, pct: true });
              return out;
            }
            case "split": {
              var tot = n(t.splitTotal), ppl = n(t.people);
              if (tot === null || !ppl || ppl < 1) return [];
              return [{ k: L.each, v: tot / Math.round(ppl), main: true }];
            }
            case "interest": {
              var P = n(t.principal), R = n(t.rate), M = n(t.months);
              if (P === null || R === null || M === null) return [];
              var I = P * R / 100 * M / 12;
              return [{ k: L.interest, v: I }, { k: L.total, v: P + I, main: true }, { k: L.perMonth, v: M ? (P + I) / M : 0 }];
            }
          }
          return [];
        },
        rowText(r) { return r.pct ? fmt(round(r.v, 2), 2) + "%" : money(r.v); },
        logTool() {
          var main = this.rows.filter(function (r) { return r.main; })[0];
          if (main) { this.addHistory(cfg.i18n.toolNames[this.tool], round(main.v, 2), main.k); FT.toast(cfg.i18n.saved); }
        },

        // ---- dragging (desktop floating panel) ----
        get panelStyle() {
          if (this.isSheet || !this.pos) return "";
          return "left:" + this.pos.x + "px;top:" + this.pos.y + "px;right:auto;";
        },
        dragStart(e) {
          if (this.isSheet || e.button !== 0 || e.target.closest("button")) return;
          var panel = this.$refs.panel, rect = panel.getBoundingClientRect();
          var dx = e.clientX - rect.left, dy = e.clientY - rect.top, self = this;
          panel.classList.add("is-dragging");
          function move(ev) { self.pos = { x: ev.clientX - dx, y: ev.clientY - dy }; self.clampPos(); }
          function up() {
            panel.classList.remove("is-dragging");
            window.removeEventListener("pointermove", move);
            window.removeEventListener("pointerup", up);
            self.savedPos = true;
            try { localStorage.setItem(POS_KEY, JSON.stringify(self.pos)); } catch (err) { /* ignore */ }
          }
          window.addEventListener("pointermove", move);
          window.addEventListener("pointerup", up);
          e.preventDefault();
        },
        // Unless the user parked the panel somewhere, keep it off the field
        // it's about to fill: slide it to the left of that field's form.
        avoidTarget() {
          if (this.isSheet || !this.target || this.savedPos) return;
          this.pos = null;
          var panel = this.$refs.panel.getBoundingClientRect();
          var box = (this.target.closest("form") || this.target).getBoundingClientRect();
          var overlaps = !(box.right < panel.left || box.left > panel.right || box.bottom < panel.top || box.top > panel.bottom);
          if (overlaps && box.left - panel.width - 16 >= 8) this.pos = { x: box.left - panel.width - 16, y: panel.top };
        },
        clampPos() {
          if (!this.pos || !this.$refs.panel) return;
          var w = this.$refs.panel.offsetWidth, h = Math.min(this.$refs.panel.offsetHeight, window.innerHeight - 16);
          this.pos = {
            x: Math.max(8, Math.min(this.pos.x, window.innerWidth - w - 8)),
            y: Math.max(8, Math.min(this.pos.y, window.innerHeight - h - 8)),
          };
        },
        resetPos() { this.pos = null; this.savedPos = false; try { localStorage.removeItem(POS_KEY); } catch (e) { /* ignore */ } },
      };
    });
  });
})();
