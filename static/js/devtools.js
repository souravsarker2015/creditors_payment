/* Dev tools (work/tools.html): the small jobs of a developer's day, as DevUtils or it-tools do them —
   JSON, YAML, JWT, Base64, URLs, timestamps, regex, cron, UUIDs, hashes, diffs, naming cases, SQL, number bases, chmod, lines.
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
  /* JSON.parse keeps numbers as doubles: 12345678901234567890 would come back as …567000, and 1.10 as 1.1, with no
     sign of it. So a number that wouldn't survive stays exactly as it was written. */
  var KEEP = "\\u0001num:", JSON_NUMBER = /^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?$/;      // (written as an escape: it goes into JSON text)
  function parseExact(text) {
    var kept = text.replace(/"(?:[^"\\]|\\.)*"|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/g, function (token) {
      return token[0] === '"' || !JSON_NUMBER.test(token) || String(Number(token)) === token ? token : '"' + KEEP + token + '"';
    });
    return JSON.parse(kept);
  }
  function showExact(value, indent) {
    return JSON.stringify(value, null, indent).replace(/"\\u0001num:([^"]*)"/g, "$1");
  }
  function fmtJson(text, indent, sortKeys) {
    var value = parseExact(text);
    function sorted(v) {
      if (Array.isArray(v)) return v.map(sorted);
      if (v && typeof v === "object") return Object.keys(v).sort().reduce(function (o, k) { o[k] = sorted(v[k]); return o; }, {});
      return v;
    }
    return showExact(sortKeys ? sorted(value) : value, indent);
  }
  function readJwt(token) {
    var parts = token.trim().split(".");
    if (parts.length < 2) throw new Error("jwt");
    var header = parseExact(b64decode(parts[0])), payload = parseExact(b64decode(parts[1]));
    var times = ["iat", "nbf", "exp"].filter(function (k) { return typeof payload[k] === "number"; }).map(function (k) { return { key: k, at: new Date(payload[k] * 1000) }; });
    return { header: showExact(header, 2), payload: showExact(payload, 2), times: times,
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
  /* Cron in words: the plain cases, in the language of the page's texts; anything else stays the runs below it */
  function cronWords(expr, T) {
    var t = expr.trim().toLowerCase(), f = (ALIASES[t] || expr.trim()).split(/\s+/);
    if (f.length !== 5) return "";
    var two = function (n) { return (n < 10 ? "0" : "") + n; }, at = /^\d+$/.test(f[0]) && /^\d+$/.test(f[1]) ? two(+f[1]) + ":" + two(+f[0]) : "";
    var every = /^\*\/(\d+)$/.exec(f[0]), when = at ? (T.cronAt || "at %s").replace("%s", at)
      : every ? (T.cronMins || "every %s minutes").replace("%s", every[1]) : f[0] === "*" && f[1] === "*" ? (T.cronMinute || "every minute")
      : f[0] === "0" && f[1] === "*" ? (T.cronHour || "every hour") : "";
    if (!when) return "";
    var hours = /^(\d+)-(\d+)$/.exec(f[1]), out = when;
    if (every && hours) out += ", " + two(+hours[1]) + ":00–" + two(+hours[2]) + ":59";
    else if (every && f[1] !== "*") return "";
    if (f[3] !== "*") return "";
    if (f[2] !== "*" && f[4] !== "*") return "";
    if (f[2] !== "*") return /^\d+$/.test(f[2]) ? out + ", " + (T.cronDay || "on day %s of the month").replace("%s", f[2]) : "";
    if (f[4] === "1-5") return out + ", " + (T.cronWeekdays || "Monday to Friday");
    if (f[4] !== "*") {
      var names = f[4].split(",").map(function (d) { var n = /^\d$/.test(d) ? +d % 7 : DAYS.indexOf(d.toLowerCase()); return n < 0 ? null : new Intl.DateTimeFormat(document.documentElement.lang || "en", { weekday: "long", timeZone: "UTC" }).format(new Date(Date.UTC(2023, 0, n + 1))); });
      return names.indexOf(null) < 0 ? out + ", " + names.join(", ") : "";
    }
    return out + (at ? ", " + (T.cronDaily || "every day") : "");
  }
  /* UUID v7: time first, so ids sort by when they were made (good as database keys) */
  function uuid7() {
    var b = crypto.getRandomValues(new Uint8Array(16)), ms = Date.now();
    for (var i = 5; i >= 0; i--) { b[i] = ms % 256; ms = Math.floor(ms / 256); }
    b[6] = (b[6] & 15) | 112; b[8] = (b[8] & 63) | 128;
    var h = Array.prototype.map.call(b, function (x) { return (x + 256).toString(16).slice(1); });
    return [h.slice(0, 4).join(""), h.slice(4, 6).join(""), h.slice(6, 8).join(""), h.slice(8, 10).join(""), h.slice(10).join("")].join("-");
  }
  /* SQL: keywords in capitals and each clause on its line. Strings, quoted names and comments are left alone. */
  var SQL_WORDS = "select from where and or join inner left right full outer cross on group by order having limit offset union all insert into values update set delete create table alter drop index as in not null is like between exists case when then else end distinct asc desc with returning primary key foreign references default".split(" ");
  var SQL_BREAK = /^(SELECT|FROM|WHERE|GROUP BY|ORDER BY|HAVING|LIMIT|OFFSET|UNION|UNION ALL|INSERT INTO|VALUES|UPDATE|SET|DELETE|WITH|RETURNING|(?:(?:INNER|LEFT|RIGHT|FULL|CROSS)(?: OUTER)? )?JOIN)$/;
  function fmtSql(text) {
    var tokens = text.match(/--[^\n]*|\/\*[\s\S]*?\*\/|'(?:[^']|'')*'|"(?:[^"]|"")*"|`[^`]*`|[A-Za-z_][\w$]*|\d+(?:\.\d+)?|<=|>=|<>|!=|::|\S/g) || [];
    var out = "", line = "";
    function flush() { if (line.trim()) { out += line.replace(/\s+$/, "") + "\n"; } line = ""; }
    for (var i = 0; i < tokens.length; i++) {
      var tk = tokens[i], low = tk.toLowerCase(), word = SQL_WORDS.indexOf(low) >= 0 ? tk.toUpperCase() : tk, two = word;
      var next = (tokens[i + 1] || "").toLowerCase();
      if ((low === "group" || low === "order" || low === "primary" || low === "foreign") && next === "by") { two = word + " BY"; i++; }
      else if (low === "union" && next === "all") { two = "UNION ALL"; i++; }
      else if (low === "insert" && next === "into") { two = "INSERT INTO"; i++; }
      else if (["inner", "left", "right", "full", "cross"].indexOf(low) >= 0) {
        while (["outer", "join"].indexOf((tokens[i + 1] || "").toLowerCase()) >= 0) { two += " " + tokens[++i].toUpperCase(); if (/JOIN$/.test(two)) break; }
      }
      if (SQL_BREAK.test(two)) { flush(); line = two + " "; }
      else if (two === "AND" || two === "OR") { flush(); line = "  " + two + " "; }
      else if (tk === ",") { line = line.replace(/\s+$/, "") + ", "; }
      else if (tk === ";") { line = line.replace(/\s+$/, "") + ";"; flush(); out += "\n"; }
      else if (tk === "(") { line += "("; }
      else if (tk === ")") { line = line.replace(/\s+$/, "") + ") "; }
      else if (tk === "." || (tokens[i + 1] === "." )) { line += tk; }
      else line += two + ((tokens[i + 1] === "(" && word === tk) || tokens[i + 1] === ")" ? "" : " ");      // count(*), but IN (…)
    }
    flush();
    return out.trim();
  }
  /* A number in any base: 255, 0xff, 0b1111, 0o17. BigInt, so a 64-bit id stays exact. */
  function bases(text) {
    var t = text.trim().replace(/[_,\s]/g, "");
    if (!/^-?(0[xX][0-9a-fA-F]+|0[bB][01]+|0[oO][0-7]+|\d+)$/.test(t)) throw new Error("number");
    var minus = t[0] === "-", n = BigInt(minus ? t.slice(1) : t), sign = minus ? "-" : "";
    return [["Decimal", sign + n.toString(10)], ["Hex", sign + "0x" + n.toString(16)], ["Octal", sign + "0o" + n.toString(8)], ["Binary", sign + "0b" + n.toString(2)]];
  }
  /* chmod: 755 ↔ rwxr-xr-x */
  function chmod(text) {
    var t = text.trim(), digits;
    if (/^[0-7]{3,4}$/.test(t)) digits = t.slice(-3);
    else if (/^-?[rwxsStT-]{9}$/.test(t)) {
      var s = t.slice(-9); digits = [0, 3, 6].map(function (i) { return (s[i] === "r" ? 4 : 0) + (s[i + 1] === "w" ? 2 : 0) + (/[xst]/.test(s[i + 2]) ? 1 : 0); }).join("");
    } else throw new Error("mode");
    var who = digits.split("").map(function (d) { d = +d; return { r: !!(d & 4), w: !!(d & 2), x: !!(d & 1), text: (d & 4 ? "r" : "-") + (d & 2 ? "w" : "-") + (d & 1 ? "x" : "-") }; });
    return { octal: digits, symbolic: who.map(function (w) { return w.text; }).join(""), who: who };
  }
  function lines(text, how) {
    var ls = text.split("\n");
    if (how === "sort") return ls.slice().sort(function (a, b) { return a.localeCompare(b, undefined, { numeric: true }); });
    if (how === "reverse") return ls.slice().reverse();
    if (how === "unique") return ls.filter(function (l, i) { return ls.indexOf(l) === i; });
    if (how === "trim") return ls.map(function (l) { return l.trim(); }).filter(Boolean);
    return ls;
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
  window.FTDevTools = { b64encode: b64encode, b64decode: b64decode, fmtJson: fmtJson, readJwt: readJwt, readTime: readTime, cronNext: cronNext, cronWords: cronWords, uuid: uuid, uuid7: uuid7, diffLines: diffLines, cases: cases,
                        fmtSql: fmtSql, bases: bases, chmod: chmod, lines: lines };
  var YAML = "https://cdn.jsdelivr.net/npm/js-yaml@4.1.0/dist/js-yaml.min.js", yamlLoading = null;
  function loadYaml() {
    if (window.jsyaml) return Promise.resolve(window.jsyaml);
    return yamlLoading = yamlLoading || new Promise(function (resolve, reject) {
      var s = document.createElement("script"); s.src = YAML; s.onload = function () { resolve(window.jsyaml); }; s.onerror = reject; document.head.appendChild(s);
    });
  }

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
        cron: "*/15 9-17 * * 1-5", cronRuns: [], cronError: "", cronText: "",
        uuids: [], uuidV: 4, hashIn: "", hashes: [], hashError: "",
        yaml: "", yamlOut: "", yamlError: "", sql: "", sqlOut: "", httpQ: "", base: "", baseOut: [], baseError: "", mode: "755", modeOut: null, modeError: "", text: "",
        left: "", right: "", diff: [], diffError: "",
        caseIn: "", caseOut: [],
        init: function () {
          var self = this, saved = location.hash.slice(1) || Work.recall(KEY, "");
          if (document.querySelector('[data-tool="' + saved + '"]')) this.tool = saved;
          this.$watch("tool", function (v) { Work.store(KEY, v); history.replaceState(null, "", "#" + v); });
          this.runCron(); this.moreUuids(); this.runMode();
        },
        copy: function (text) {
          var done = function () { Work.toast(T.copied || "Copied"); };
          if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(done, function () { FT.showText(text); }); else FT.showText(text);
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
          this.cronText = FTDevTools.cronWords(this.cron, T);
          try { this.cronRuns = FTDevTools.cronNext(this.cron, 6, new Date()); if (!this.cronRuns.length) this.cronError = T.cronNever || "Never runs."; }
          catch (e) { this.cronRuns = []; this.cronError = T.badCron || "Not a cron line."; }
        },
        moreUuids: function (v) {
          if (v) this.uuidV = v;
          var o = []; for (var i = 0; i < 5; i++) o.push(this.uuidV === 7 ? FTDevTools.uuid7() : FTDevTools.uuid());
          this.uuids = o;
        },
        runYaml: function (to) {
          var self = this;
          this.yamlError = ""; this.yamlOut = "";
          if (!this.yaml.trim()) return;
          loadYaml().then(function (y) {
            try { self.yamlOut = to === "json" ? JSON.stringify(y.load(self.yaml), null, 2) : y.dump(JSON.parse(self.yaml), { lineWidth: -1, noRefs: true }); }
            catch (e) { self.yamlError = e.message.split("\n")[0]; }
          }, function () { self.yamlError = T.noYaml || "Couldn't load the YAML reader."; });
        },
        runSql: function () { this.sqlOut = FTDevTools.fmtSql(this.sql); },
        get httpHits() {
          var q = this.httpQ.trim().toLowerCase(), all = (T.http || []);
          return q ? all.filter(function (h) { return (h[0] + " " + h[1] + " " + h[2]).toLowerCase().indexOf(q) >= 0; }) : all;
        },
        runBase: function () {
          this.baseError = "";
          if (!this.base.trim()) { this.baseOut = []; return; }
          try { this.baseOut = FTDevTools.bases(this.base); } catch (e) { this.baseOut = []; this.baseError = T.badNumber || "Not a number."; }
        },
        runMode: function () {
          this.modeError = "";
          try { this.modeOut = FTDevTools.chmod(this.mode); } catch (e) { this.modeOut = null; this.modeError = T.badMode || "Not a mode."; }
        },
        toggleMode: function (who, what) {
          var m = this.modeOut; if (!m) return;
          m.who[who][what] = !m.who[who][what];
          this.mode = m.who.map(function (w) { return (w.r ? 4 : 0) + (w.w ? 2 : 0) + (w.x ? 1 : 0); }).join("");
          this.runMode();
        },
        runLines: function (how) { this.text = FTDevTools.lines(this.text, how).join("\n"); },
        get lineCount() { return this.text ? this.text.split("\n").length : 0; },
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
