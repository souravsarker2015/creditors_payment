/* Dev tools (work/tools.html): the small jobs of a developer's day, as DevUtils or it-tools do them —
   JSON, JWT, Base64, URLs, timestamps, regex, cron, UUIDs, hashes, diffs, naming cases.
   Everything runs here in the browser: nothing typed is sent anywhere, so a real token can be pasted.
   A JWT is only read, never verified. A regex runs in a worker, stopped after a moment: a pattern that
   backtracks for ever can't freeze the page. */
(function () {
  "use strict";
  var enc = new TextEncoder(), dec = new TextDecoder("utf-8", { fatal: true });

  function b64encode(text) { var s = ""; enc.encode(text).forEach(function (b) { s += String.fromCharCode(b); }); return btoa(s); }
  function b64decode(text) {
    var t = text.trim().replace(/-/g, "+").replace(/_/g, "/").replace(/\s+/g, "");
    while (t.length % 4) t += "=";
    var bin = atob(t), bytes = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return dec.decode(bytes);
  }
  function fmtJson(text, indent, sortKeys) {
    var value = JSON.parse(text);
    function sorted(v) {
      if (Array.isArray(v)) return v.map(sorted);
      if (v && typeof v === "object") return Object.keys(v).sort().reduce(function (o, k) { o[k] = sorted(v[k]); return o; }, {});
      return v;
    }
    return JSON.stringify(sortKeys ? sorted(value) : value, null, indent);
  }
  function readJwt(token) {
    var parts = token.trim().split(".");
    if (parts.length < 2) throw new Error("jwt");
    var header = JSON.parse(b64decode(parts[0])), payload = JSON.parse(b64decode(parts[1]));
    var times = ["iat", "nbf", "exp"].filter(function (k) { return typeof payload[k] === "number"; }).map(function (k) { return { key: k, at: new Date(payload[k] * 1000) }; });
    return { header: JSON.stringify(header, null, 2), payload: JSON.stringify(payload, null, 2), times: times,
             expired: typeof payload.exp === "number" ? payload.exp * 1000 < Date.now() : null };
  }
  function readTime(text) {
    var t = text.trim(); if (!t) return null;
    var d;
    if (/^-?\d+(\.\d+)?$/.test(t)) { var n = Number(t); d = new Date(Math.abs(n) >= 1e11 ? n : n * 1000); } else d = new Date(t);
    return isNaN(d.getTime()) ? null : d;
  }
  /* Cron: five fields (or @daily…), a list of the next times it runs */
  var MONTHS = "jan feb mar apr may jun jul aug sep oct nov dec".split(" "), DAYS = "sun mon tue wed thu fri sat".split(" ");
  var ALIASES = { "@hourly": "0 * * * *", "@daily": "0 0 * * *", "@midnight": "0 0 * * *", "@weekly": "0 0 * * 0", "@monthly": "0 0 1 * *", "@yearly": "0 0 1 1 *", "@annually": "0 0 1 1 *" };
  function cronField(text, lo, hi, names) {
    var out = {};
    function num(v) {
      var at = names ? names.indexOf(v.toLowerCase()) : -1;
      var n = at >= 0 ? at + (lo === 1 ? 1 : 0) : (/^\d+$/.test(v) ? Number(v) : NaN);
      if (isNaN(n)) throw new Error("cron");
      return n;
    }
    text.split(",").forEach(function (part) {
      var m = /^([^/]+)(?:\/(\d+))?$/.exec(part); if (!m) throw new Error("cron");
      var step = m[2] ? Number(m[2]) : 1, a = lo, b = hi;
      if (!step) throw new Error("cron");
      if (m[1] !== "*") {
        var r = m[1].split("-"); if (r.length > 2) throw new Error("cron");
        a = num(r[0]); b = r.length === 2 ? num(r[1]) : (m[2] ? hi : a);
      }
      var top = lo === 0 && hi === 6 ? 7 : hi;        // (a weekday may be written 7 for Sunday)
      if (a < lo || b > top || a > b) throw new Error("cron");
      for (var i = a; i <= b; i += step) out[lo === 0 && hi === 6 ? i % 7 : i] = true;
    });
    return out;
  }
  function cronNext(expr, count, from) {
    var t = expr.trim().toLowerCase(), f = (ALIASES[t] || expr.trim()).split(/\s+/);
    if (f.length !== 5) throw new Error("cron");
    var mins = cronField(f[0], 0, 59), hours = cronField(f[1], 0, 23), dom = cronField(f[2], 1, 31), mon = cronField(f[3], 1, 12, MONTHS), dow = cronField(f[4], 0, 6, DAYS);
    var domAny = f[2] === "*", dowAny = f[4] === "*", out = [];
    var day = new Date(from.getFullYear(), from.getMonth(), from.getDate());
    for (var n = 0; n < 366 * 8 && out.length < count; n++) {
      var d = day.getDate(), wd = day.getDay();
      // as cron has it: with both a day of the month and a weekday, either will do
      var hit = domAny || dowAny ? (domAny || dom[d]) && (dowAny || dow[wd]) : dom[d] || dow[wd];
      if (mon[day.getMonth() + 1] && hit) {
        for (var h = 0; h < 24 && out.length < count; h++) {
          if (!hours[h]) continue;
          for (var m = 0; m < 60 && out.length < count; m++) {
            if (!mins[m]) continue;
            var at = new Date(day.getFullYear(), day.getMonth(), d, h, m);
            if (at > from) out.push(at);
          }
        }
      }
      day.setDate(d + 1);
    }
    return out;
  }
  function uuid() {
    if (crypto.randomUUID) return crypto.randomUUID();
    var b = crypto.getRandomValues(new Uint8Array(16)), h = [];
    b[6] = (b[6] & 15) | 64; b[8] = (b[8] & 63) | 128;
    b.forEach(function (x) { h.push((x + 256).toString(16).slice(1)); });
    return h.slice(0, 4).join("") + "-" + h.slice(4, 6).join("") + "-" + h.slice(6, 8).join("") + "-" + h.slice(8, 10).join("") + "-" + h.slice(10).join("");
  }
  /* Line diff: the longest common run of lines (LCS), with what's the same at both ends set aside first */
  var DIFF_MAX = 2000;
  function diffLines(a, b) {
    var x = a.split("\n"), y = b.split("\n"), head = [], tail = [];
    while (x.length && y.length && x[0] === y[0]) { head.push({ k: "=", t: x.shift() }); y.shift(); }
    while (x.length && y.length && x[x.length - 1] === y[y.length - 1]) { tail.unshift({ k: "=", t: x.pop() }); y.pop(); }
    if (x.length > DIFF_MAX || y.length > DIFF_MAX) throw new Error("diff");
    var n = x.length, m = y.length, L = [], i, j;
    for (i = 0; i <= n; i++) L.push(new Uint16Array(m + 1));
    for (i = n - 1; i >= 0; i--) for (j = m - 1; j >= 0; j--) L[i][j] = x[i] === y[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
    var mid = []; i = 0; j = 0;
    while (i < n || j < m) {
      if (i < n && j < m && x[i] === y[j]) { mid.push({ k: "=", t: x[i] }); i++; j++; }
      else if (j < m && (i === n || L[i][j + 1] > L[i + 1][j])) mid.push({ k: "+", t: y[j++] });
      else mid.push({ k: "-", t: x[i++] });
    }
    return head.concat(mid, tail);
  }
  function words(text) { return text.replace(/([a-z0-9])([A-Z])/g, "$1 $2").replace(/([A-Z]+)([A-Z][a-z])/g, "$1 $2").split(/[^\p{L}\p{N}]+/u).filter(Boolean).map(function (w) { return w.toLowerCase(); }); }
  function cap(w) { return w.charAt(0).toUpperCase() + w.slice(1); }
  function cases(text) {
    var w = words(text); if (!w.length) return [];
    return [["camelCase", w[0] + w.slice(1).map(cap).join("")], ["PascalCase", w.map(cap).join("")], ["snake_case", w.join("_")], ["kebab-case", w.join("-")],
            ["CONSTANT_CASE", w.join("_").toUpperCase()], ["Title Case", w.map(cap).join(" ")], ["dot.case", w.join(".")]];
  }
  function esc(s) { return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }
  var RX_WORKER = "onmessage=function(e){var d=e.data,o=[],r,m,f=d.f;if(f.indexOf('g')<0)f+='g';try{r=new RegExp(d.p,f)}catch(x){postMessage({error:x.message});return}" +
                  "while((m=r.exec(d.t))&&o.length<1000){o.push({i:m.index,t:m[0],g:m.slice(1)});if(!m[0].length)r.lastIndex++}postMessage({m:o})}";
  window.FTDevTools = { b64encode: b64encode, b64decode: b64decode, fmtJson: fmtJson, readJwt: readJwt, readTime: readTime, cronNext: cronNext, uuid: uuid, diffLines: diffLines, cases: cases };

  document.addEventListener("alpine:init", function () {
    Alpine.data("devTools", function () {
      var T = {}; try { T = JSON.parse(document.getElementById("devtools-text").textContent); } catch (e) { T = {}; }
      var KEY = "work-devtool", worker = null, timer = null;
      return {
        tool: "json", T: T,
        json: "", jsonOut: "", jsonError: "", jsonSort: false,
        jwt: "", jwtOut: null, jwtError: "",
        b64: "", b64Out: "", b64Error: "",
        url: "", urlOut: "", urlError: "",
        time: "", timeAt: null,
        rx: "", rxFlags: "gi", rxText: "", rxHits: [], rxError: "", rxBusy: false,
        cron: "*/15 9-17 * * 1-5", cronRuns: [], cronError: "",
        uuids: [], hashIn: "", hashes: [], hashError: "",
        left: "", right: "", diff: [], diffError: "",
        caseIn: "", caseOut: [],
        init: function () {
          var self = this, saved = location.hash.slice(1) || Work.recall(KEY, "");
          if (document.querySelector('[data-tool="' + saved + '"]')) this.tool = saved;
          this.$watch("tool", function (v) { Work.store(KEY, v); history.replaceState(null, "", "#" + v); });
          this.runCron(); this.moreUuids();
        },
        copy: function (text) {
          var done = function () { Work.toast(T.copied || "Copied"); };
          if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(done, function () { prompt("", text); }); else prompt("", text);
        },
        runJson: function (indent) {
          this.jsonError = "";
          if (!this.json.trim()) { this.jsonOut = ""; return; }
          try { this.jsonOut = FTDevTools.fmtJson(this.json, indent, this.jsonSort); } catch (e) { this.jsonOut = ""; this.jsonError = e.message; }
        },
        runJwt: function () {
          this.jwtError = ""; this.jwtOut = null;
          if (!this.jwt.trim()) return;
          try { this.jwtOut = FTDevTools.readJwt(this.jwt); } catch (e) { this.jwtError = T.badJwt || "Not a JWT."; }
        },
        runB64: function (way) {
          this.b64Error = "";
          try { this.b64Out = way === "encode" ? FTDevTools.b64encode(this.b64) : FTDevTools.b64decode(this.b64); } catch (e) { this.b64Out = ""; this.b64Error = T.badB64 || "Not Base64 text."; }
        },
        runUrl: function (way) {
          this.urlError = "";
          try { this.urlOut = way === "encode" ? encodeURIComponent(this.url) : decodeURIComponent(this.url.replace(/\+/g, " ")); } catch (e) { this.urlOut = ""; this.urlError = T.badUrl || "Not valid."; }
        },
        now: function () { this.time = String(Math.floor(Date.now() / 1000)); this.runTime(); },
        runTime: function () { this.timeAt = FTDevTools.readTime(this.time); },
        when: function (d) { return d ? d.toLocaleString() : ""; },
        iso: function (d) { return d ? d.toISOString() : ""; },
        secs: function (d) { return d ? String(Math.floor(d.getTime() / 1000)) : ""; },
        ago: function (d) {
          if (!d) return "";
          var s = Math.round((d.getTime() - Date.now()) / 1000), a = Math.abs(s), units = [["year", 31536000], ["month", 2592000], ["day", 86400], ["hour", 3600], ["minute", 60], ["second", 1]];
          var u = units.find(function (x) { return a >= x[1]; }) || units[5];
          return new Intl.RelativeTimeFormat(document.documentElement.lang || "en", { numeric: "auto" }).format(Math.trunc(s / u[1]), u[0]);
        },
        runRx: function () {
          var self = this;
          clearTimeout(timer); if (worker) { worker.terminate(); worker = null; }
          this.rxError = "";
          if (!this.rx || !this.rxText) { this.rxHits = []; this.rxBusy = false; return; }
          timer = setTimeout(function () {
            self.rxBusy = true;
            var w = worker = new Worker(URL.createObjectURL(new Blob([RX_WORKER], { type: "text/javascript" })));
            var stop = setTimeout(function () { w.terminate(); if (worker === w) { worker = null; self.rxBusy = false; self.rxHits = []; self.rxError = T.rxSlow || "Too slow."; } }, 1500);
            w.onmessage = function (e) {
              clearTimeout(stop); w.terminate(); if (worker !== w) return;
              worker = null; self.rxBusy = false;
              if (e.data.error) { self.rxHits = []; self.rxError = e.data.error; } else self.rxHits = e.data.m;
            };
            w.postMessage({ p: self.rx, f: self.rxFlags.replace(/[^dgimsuvy]/g, ""), t: self.rxText });
          }, 200);
        },
        get rxHtml() {
          var out = "", at = 0, t = this.rxText;
          this.rxHits.forEach(function (h) { out += esc(t.slice(at, h.i)) + "<mark>" + esc(h.t) + "</mark>"; at = h.i + h.t.length; });
          return out + esc(t.slice(at));
        },
        runCron: function () {
          this.cronError = "";
          try { this.cronRuns = FTDevTools.cronNext(this.cron, 6, new Date()); if (!this.cronRuns.length) this.cronError = T.cronNever || "Never runs."; }
          catch (e) { this.cronRuns = []; this.cronError = T.badCron || "Not a cron line."; }
        },
        moreUuids: function () { var o = []; for (var i = 0; i < 5; i++) o.push(FTDevTools.uuid()); this.uuids = o; },
        runHash: function () {
          var self = this, text = this.hashIn;
          this.hashError = "";
          if (!window.crypto || !crypto.subtle) { this.hashes = []; this.hashError = T.noHash || "Needs https."; return; }
          Promise.all(["SHA-1", "SHA-256", "SHA-512"].map(function (name) {
            return crypto.subtle.digest(name, enc.encode(text)).then(function (buf) {
              return { name: name, hex: Array.prototype.map.call(new Uint8Array(buf), function (b) { return (b + 256).toString(16).slice(1); }).join("") };
            });
          })).then(function (r) { if (self.hashIn === text) self.hashes = r; });
        },
        runDiff: function () {
          this.diffError = "";
          try { this.diff = FTDevTools.diffLines(this.left, this.right); } catch (e) { this.diff = []; this.diffError = T.diffBig || "Too long."; }
        },
        get diffCount() { return this.diff.filter(function (d) { return d.k !== "="; }).length; },
        runCase: function () { this.caseOut = FTDevTools.cases(this.caseIn); },
      };
    });
  });
})();
