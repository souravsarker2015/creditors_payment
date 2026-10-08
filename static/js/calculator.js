/* FinTrack calculator
   --------------------------------------------------------------------------
   One floating calculator for every page (templates/partials/calculator.html).
   - Expression engine: a tiny recursive-descent parser, no eval(). Percent
     follows the business-calculator convention: `500 + 15%` = 575,
     `500 - 10%` = 450, `2000 × 5%` = 100, a lone `15%` = 0.15.
   - History: kept in this browser only, per user, for HISTORY_DAYS, capped at
     HISTORY_MAX entries, and wiped on logout (see base.html).
   - "Insert" writes the result into the amount field you last focused.
   - Tools: money (discount, VAT, profit, split), loans & savings (interest,
     EMI, DPS), bazar & farm (rate × quantity, units, cash count) and amount
     in words for cheques. Bangla digits (০–৯) are accepted everywhere.
   ========================================================================== */
(function () {
  "use strict";

  var HISTORY_MAX = 30;
  var HISTORY_DAYS = 7;
  var POS_KEY = "ft-calc-pos";
  var TOOL_KEY = "ft-calc-tool";
  var MON_KEY = "ft-calc-mon";
  var NOTES = ["1000", "500", "200", "100", "50", "20", "10", "5", "2", "1"];   // Bangladeshi notes and coins

  // Bangla digits typed on a Bangla keyboard count as ordinary digits.
  function ascii(v) {
    return String(v).replace(/[০-৯]/g, function (d) { return String(d.charCodeAt(0) - 0x09E6); });
  }
  function store(key, value) { try { localStorage.setItem(key, value); } catch (e) { /* storage off */ } }
  function recall(key) { try { return localStorage.getItem(key); } catch (e) { return null; } }

  // Units, in the base unit of their kind: kg for weight, decimal (shotok) for
  // land. A mon is what the farm says (40 kg in most places); a seer is 1/40 mon.
  // Land as reckoned in most of Bangladesh: 1 bigha = 33 decimal = 20 katha.
  function unitTable(monKg) {
    return {
      weight: [["g", 0.001], ["kg", 1], ["seer", monKg / 40], ["mon", monKg], ["ton", 1000]],
      land: [["sqft", 1 / 435.6], ["katha", 1.65], ["dec", 1], ["bigha", 33], ["acre", 100], ["ha", 247.105]],
    };
  }

  // ---- amount in words (Bangladeshi lakh / crore) ---------------------------
  var EN_ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve",
    "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"];
  var EN_TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"];
  var BN = ("শূন্য এক দুই তিন চার পাঁচ ছয় সাত আট নয় দশ এগারো বারো তেরো চৌদ্দ পনেরো ষোলো সতেরো আঠারো উনিশ " +
    "বিশ একুশ বাইশ তেইশ চব্বিশ পঁচিশ ছাব্বিশ সাতাশ আটাশ উনত্রিশ ত্রিশ একত্রিশ বত্রিশ তেত্রিশ চৌত্রিশ পঁয়ত্রিশ ছত্রিশ সাঁইত্রিশ আটত্রিশ ঊনচল্লিশ " +
    "চল্লিশ একচল্লিশ বিয়াল্লিশ তেতাল্লিশ চুয়াল্লিশ পঁয়তাল্লিশ ছেচল্লিশ সাতচল্লিশ আটচল্লিশ ঊনপঞ্চাশ পঞ্চাশ একান্ন বায়ান্ন তিপ্পান্ন চুয়ান্ন পঞ্চান্ন ছাপ্পান্ন সাতান্ন আটান্ন ঊনষাট " +
    "ষাট একষট্টি বাষট্টি তেষট্টি চৌষট্টি পঁয়ষট্টি ছেষট্টি সাতষট্টি আটষট্টি ঊনসত্তর সত্তর একাত্তর বাহাত্তর তিয়াত্তর চুয়াত্তর পঁচাত্তর ছিয়াত্তর সাতাত্তর আটাত্তর ঊনআশি " +
    "আশি একাশি বিরাশি তিরাশি চুরাশি পঁচাশি ছিয়াশি সাতাশি অষ্টাশি ঊননব্বই নব্বই একানব্বই বিরানব্বই তিরানব্বই চুরানব্বই পঁচানব্বই ছিয়ানব্বই সাতানব্বই আটানব্বই নিরানব্বই").split(" ");

  function enTwo(n) { return n < 20 ? EN_ONES[n] : EN_TENS[Math.floor(n / 10)] + (n % 10 ? "-" + EN_ONES[n % 10] : ""); }
  function bnTwo(n) { return n ? BN[n] : ""; }
  // Whole taka in words, crore / lakh / thousand / hundred; crores can be any size.
  function inWords(n, two, hundred, scales) {
    var out = [], crore = Math.floor(n / 1e7), rest = n % 1e7;
    if (crore) out.push(inWords(crore, two, hundred, scales) + " " + scales[0]);
    var lakh = Math.floor(rest / 1e5), thousand = Math.floor((rest % 1e5) / 1000), h = Math.floor((rest % 1000) / 100), r = rest % 100;
    if (lakh) out.push(two(lakh) + " " + scales[1]);
    if (thousand) out.push(two(thousand) + " " + scales[2]);
    if (h) out.push(two(h) + " " + hundred);
    if (r) out.push(two(r));
    return out.join(" ");
  }
  function takaWords(amount) {
    if (amount === null || !isFinite(amount) || amount < 0 || amount >= 1e15) return null;
    var paisa = Math.round(amount * 100), taka = Math.floor(paisa / 100);
    paisa = paisa % 100;
    var en = taka ? inWords(taka, enTwo, "Hundred", ["Crore", "Lakh", "Thousand"]) : "Zero";
    var bn = taka ? inWords(taka, bnTwo, "শত", ["কোটি", "লক্ষ", "হাজার"]) : BN[0];
    return {
      en: "Taka " + en + (paisa ? " and " + enTwo(paisa) + " Paisa" : "") + " Only",
      bn: bn + " টাকা" + (paisa ? " " + BN[paisa] + " পয়সা" : "") + " মাত্র",
    };
  }

  function round(n, dp) {
    var f = Math.pow(10, dp);
    return Math.round((n + Number.EPSILON) * f) / f;
  }

  // ---- expression engine --------------------------------------------------
  function tokenize(src) {
    var s = ascii(src).replace(/,/g, "").replace(/[×xX*]/g, "*").replace(/[÷/]/g, "/").replace(/[−–]/g, "-");
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
    return Number(n).toLocaleString("en-IN", { maximumFractionDigits: dp === undefined ? 6 : dp });
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

  window.FTCalc = { evaluate: evaluate, takaWords: takaWords }; // exposed for quick console checks

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
        tool: null,     // null: the list of tools
        t: {            // tool inputs
          price: "", off: "",
          vatAmount: "", vatRate: "15", vatMode: "add",
          cost: "", sell: "",
          splitTotal: "", people: "2",
          principal: "", rate: "", months: "12",
          emiAmount: "", emiRate: "", emiMonths: "12",
          dpsAmount: "", dpsRate: "", dpsYears: "5",
          qty: "", qtyUnit: "kg", unitRate: "", rateUnit: "mon",
          convKind: "weight", convValue: "", convFrom: "mon",
          cash: {},
          wordsAmount: "",
        },
        monKg: "40",
        notes: NOTES,
        pos: null,
        savedPos: false,
        key: "ft-calc-history:" + cfg.user,

        init() {
          this.loadHistory();
          try { this.pos = JSON.parse(localStorage.getItem(POS_KEY) || "null"); } catch (e) { this.pos = null; }
          this.savedPos = !!this.pos;
          var tool = recall(TOOL_KEY);
          this.tool = tool && cfg.i18n.toolNames[tool] ? tool : null;
          // The mon: what you last set, else this farm's, else 40 kg.
          var farmMon = parseFloat(cfg.monKg);
          this.monKg = recall(MON_KEY) || (farmMon > 0 ? String(farmMon) : "40");
          this.$watch("monKg", function (v) { if (parseFloat(ascii(v)) > 0) store(MON_KEY, ascii(v)); });
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
          var v = ascii(e.target.value).replace(/\*/g, "×").replace(/\//g, "÷").replace(/-/g, "−").replace(/[^0-9.,+−×÷%() xX]/g, "");
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
        copyText(text) {
          if (text && navigator.clipboard) navigator.clipboard.writeText(text).then(function () { FT.toast(cfg.i18n.copied); });
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

        // ---- tools ----
        num(v) { var n = parseFloat(ascii(v).replace(/,/g, "")); return isFinite(n) ? n : null; },
        pick(name) { this.tool = name; store(TOOL_KEY, name); },
        allTools() { this.tool = null; try { localStorage.removeItem(TOOL_KEY); } catch (e) { /* ignore */ } },
        get toolTitle() { return this.tool ? cfg.i18n.toolNames[this.tool] : ""; },
        get mon() { var m = this.num(this.monKg); return m && m > 0 ? m : 40; },
        get units() { return unitTable(this.mon); },
        unitName(key) { return cfg.i18n.units[key] || key; },
        unitSym(key) { return cfg.i18n.sym[key] || key; },
        setKind(kind) { this.t.convKind = kind; this.t.convFrom = kind === "land" ? "bigha" : "mon"; },
        factor(key) {
          var all = this.units.weight.concat(this.units.land);
          for (var i = 0; i < all.length; i++) if (all[i][0] === key) return all[i][1];
          return 1;
        },
        fmtMoney(v) { return money(v); },
        cashLine(d) { var c = this.num(this.t.cash[d]); return c ? c * Number(d) : 0; },
        clearCash() { this.t.cash = {}; },
        get words() { return takaWords(this.num(this.t.wordsAmount)); },
        get rows() {
          var t = this.t, n = this.num.bind(this), L = cfg.i18n.tools, self = this;
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
            case "emi": {
              // Reducing balance, paid monthly — how banks quote a term loan.
              var LP = n(t.emiAmount), LR = n(t.emiRate), LN = Math.round(n(t.emiMonths) || 0);
              if (LP === null || LR === null || LN < 1) return [];
              var mr = LR / 1200, emi = mr ? LP * mr * Math.pow(1 + mr, LN) / (Math.pow(1 + mr, LN) - 1) : LP / LN;
              return [{ k: L.emi, v: emi, main: true }, { k: L.interest, v: emi * LN - LP }, { k: L.total, v: emi * LN }];
            }
            case "dps": {
              // A deposit at the start of every month, interest added monthly.
              var D = n(t.dpsAmount), DR = n(t.dpsRate), DY = n(t.dpsYears);
              if (D === null || DR === null || !DY || DY <= 0) return [];
              var dn = Math.round(DY * 12), dr = DR / 1200, paid = D * dn;
              var fv = dr ? D * (Math.pow(1 + dr, dn) - 1) / dr * (1 + dr) : paid;
              return [{ k: L.deposited, v: paid }, { k: L.earned, v: fv - paid, tone: "good" }, { k: L.maturity, v: fv, main: true }];
            }
            case "rate": {
              var q = n(t.qty), ur = n(t.unitRate);
              if (q === null || ur === null) return [];
              var kg = q * this.factor(t.qtyUnit), perKg = ur / this.factor(t.rateUnit), mon = this.mon;
              return [
                { k: L.price, v: kg * perKg, main: true },
                { k: L.weight, text: fmt(round(kg, 3)) + " " + this.unitSym("kg") + " = " + fmt(round(kg / mon, 3)) + " " + this.unitSym("mon") },
                { k: L.perKg, v: perKg },
                { k: L.perMon, v: perKg * mon },
              ];
            }
            case "units": {
              var cv = n(t.convValue);
              if (cv === null) return [];
              var base = cv * this.factor(t.convFrom);
              return this.units[t.convKind].filter(function (u) { return u[0] !== t.convFrom; }).map(function (u) {
                return { k: self.unitName(u[0]), v: round(base / u[1], 4), unit: self.unitSym(u[0]) };
              });
            }
            case "cash": {
              var sum = 0, count = 0;
              NOTES.forEach(function (d) { var c = n(t.cash[d]); if (c) { sum += c * Number(d); count += c; } });
              if (!count) return [];
              return [{ k: L.cashTotal, v: sum, main: true }, { k: L.pieces, text: fmt(count) }];
            }
          }
          return [];
        },
        rowText(r) {
          if (r.text !== undefined) return r.text;
          if (r.unit) return fmt(r.v, 4) + " " + r.unit;
          return r.pct ? fmt(round(r.v, 2), 2) + "%" : money(r.v);
        },
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
