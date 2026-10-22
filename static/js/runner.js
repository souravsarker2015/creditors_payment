/* Running code on the page (Interview prep): Python, JavaScript and SQL.

   The code runs in a worker inside a sandboxed frame of its own (no access
   to this page, its cookies or the account), and is stopped if it takes too
   long. Python (Pyodide) and SQLite (sql.js) are fetched the first time they
   are needed and then kept.

   Work.runCode(language, code, {tests, expected}) → a promise of
     {ok, out, error, ms, table: {columns, rows}, verdict: "pass"|"fail"|"match"|"differ"|""}
   `tests` runs after the code (asserts) — or, for SQL, first (the tables and rows).
   `expected` (SQL only) is the model query: the two results are compared. */
(function () {
  "use strict";
  var d = document;
  var PYODIDE = "https://cdn.jsdelivr.net/pyodide/v0.26.4/full/";
  var SQLJS = "https://cdnjs.cloudflare.com/ajax/libs/sql.js/1.10.3/";
  var LANGS = { python: "python", py: "python", python3: "python", javascript: "javascript", js: "javascript", node: "javascript",
                sql: "sql", sqlite: "sql", postgres: "sql", postgresql: "sql", mysql: "sql" };

  // ── What runs in the worker ──────────────────────────────────────────────
  function worker() {
    /* global importScripts, loadPyodide, initSqlJs */
    var py = null, SQL = null, PY = "%PY%", SQ = "%SQ%";
    function fmt(v) {
      if (typeof v === "string") return v;
      try { return JSON.stringify(v, function (k, x) { return typeof x === "bigint" ? x.toString() : x; }) || String(v); } catch (e) { return String(v); }
    }
    function lastTable(results) {
      var r = results && results.length ? results[results.length - 1] : null;
      return r ? { columns: r.columns, rows: r.values.slice(0, 200), count: r.values.length } : { columns: [], rows: [], count: 0 };
    }
    function same(a, b, ordered) {
      var x = a.rows.map(function (r) { return JSON.stringify(r); }), y = b.rows.map(function (r) { return JSON.stringify(r); });
      if (!ordered) { x.sort(); y.sort(); }
      return a.count === b.count && JSON.stringify(x) === JSON.stringify(y);
    }
    onmessage = async function (ev) {
      var m = ev.data, out = [], t0;
      function log() { if (out.length < 400) out.push(Array.prototype.map.call(arguments, fmt).join(" ")); }
      try {
        if (m.lang === "python" && !py) { postMessage({ id: m.id, loading: true }); importScripts(PY + "pyodide.js"); py = await loadPyodide({ indexURL: PY }); }
        if (m.lang === "sql" && !SQL) { postMessage({ id: m.id, loading: true }); importScripts(SQ + "sql-wasm.js"); SQL = await initSqlJs({ locateFile: function (f) { return SQ + f; } }); }
        postMessage({ id: m.id, started: true });
        t0 = performance.now();
        var res = { id: m.id, ok: true, verdict: "" };
        if (m.lang === "javascript") {
          var cons = { log: log, info: log, warn: log, error: log, table: log };
          var assert = function (ok, msg) { if (!ok) throw new Error(msg || "A check failed"); };
          assert.equal = function (a, b, msg) { if (a !== b) throw new Error((msg ? msg + ": " : "") + "expected " + fmt(b) + ", got " + fmt(a)); };
          assert.deepEqual = function (a, b, msg) { if (fmt(a) !== fmt(b)) throw new Error((msg ? msg + ": " : "") + "expected " + fmt(b) + ", got " + fmt(a)); };
          var Async = Object.getPrototypeOf(async function () {}).constructor;
          var value = await new Async("console", "assert", '"use strict";\n' + m.code + "\n;\n" + (m.tests || ""))(cons, assert);
          if (value !== undefined) log(value);
          if (m.tests) res.verdict = "pass";
        } else if (m.lang === "python") {
          py.setStdout({ batched: log }); py.setStderr({ batched: log });
          var scope = py.globals.get("dict")();
          try { await py.runPythonAsync(m.code + "\n\n" + (m.tests || ""), { globals: scope }); } finally { scope.destroy(); }
          if (m.tests) res.verdict = "pass";
        } else if (m.lang === "sql") {
          var db = new SQL.Database();
          try {
            if (m.tests) db.run(m.tests);
            res.table = lastTable(db.exec(m.code));
          } finally { db.close(); }
          if (m.expected) {
            var db2 = new SQL.Database();
            try { if (m.tests) db2.run(m.tests); res.want = lastTable(db2.exec(m.expected)); } finally { db2.close(); }
            res.verdict = same(res.table, res.want, /order\s+by/i.test(m.expected)) ? "match" : "differ";
          }
        }
        res.out = out.join("\n"); res.ms = Math.round(performance.now() - t0);
        postMessage(res);
      } catch (err) {
        var msg = String((err && err.message) || err);
        if (m.lang === "python") {       // from the user's own code on: Pyodide's inner lines say nothing useful
          var lines = msg.split("\n"), at = -1;
          for (var i = 0; i < lines.length; i++) if (/File "<exec>"/.test(lines[i])) { at = i; break; }
          msg = (at >= 0 ? lines.slice(at) : lines.slice(-4)).join("\n").replace(/File "<exec>", /g, "").trim();
        }
        postMessage({ id: m.id, ok: false, out: out.join("\n"), error: msg, verdict: m.tests || m.expected ? "fail" : "", ms: t0 ? Math.round(performance.now() - t0) : 0 });
      }
    };
  }

  // ── The sandboxed frame: starts the worker, passes messages, stops runaway code ──
  function frameSource() {
    var src = "(" + worker.toString().replace("%PY%", PYODIDE).replace("%SQ%", SQLJS) + ")()";
    return "<!doctype html><meta charset=utf-8><script>(" + function (code) {
      var w = null, url = URL.createObjectURL(new Blob([code], { type: "text/javascript" })), job = null, timer = null, next = null;
      function fresh() { if (w) w.terminate(); w = new Worker(url); w.onmessage = back; }
      function back(ev) {
        var m = ev.data;
        if (!job || m.id !== job.id) return;
        if (m.loading) { parent.postMessage({ id: m.id, loading: true }, "*"); return; }
        if (m.started) { clearTimeout(timer); timer = setTimeout(stop, job.limit); return; }
        clearTimeout(timer); job = null; parent.postMessage(m, "*");
        if (next) { var n = next; next = null; start(n); }
      }
      function stop() { var j = job; job = null; fresh(); if (j) parent.postMessage({ id: j.id, ok: false, timeout: true, verdict: "fail" }, "*"); }
      fresh();
      function start(m) {
        job = { id: m.id, limit: m.limit || 8000, warm: m.warm };
        clearTimeout(timer); timer = setTimeout(stop, 180000);       // loading Python can take a while the first time
        w.postMessage(m);
      }
      onmessage = function (ev) {
        var m = ev.data;
        if (job && job.warm) { next = m; parent.postMessage({ id: m.id, loading: true }, "*"); return; }   // still getting ready: run it straight after
        if (job) stop();
        start(m);
      };
      parent.postMessage({ ready: true }, "*");
    }.toString() + ")(" + JSON.stringify(src).replace(/<\//g, "<\\/") + ")<\/script>";
  }

  var frame = null, ready = null, seq = 0, waiting = {};
  function open() {
    if (ready) return ready;
    ready = new Promise(function (resolve) {
      frame = d.createElement("iframe");
      frame.setAttribute("sandbox", "allow-scripts");
      frame.setAttribute("aria-hidden", "true"); frame.tabIndex = -1;
      frame.style.cssText = "position:absolute;width:0;height:0;border:0;visibility:hidden";
      window.addEventListener("message", function (ev) {
        if (!frame || ev.source !== frame.contentWindow) return;
        var m = ev.data || {};
        if (m.ready) { resolve(); return; }
        var job = waiting[m.id]; if (!job) return;
        if (m.loading) { if (job.onLoading) job.onLoading(); return; }
        delete waiting[m.id]; job.resolve(m);
      });
      frame.srcdoc = frameSource();
      d.body.appendChild(frame);
    });
    return ready;
  }

  window.Work = window.Work || {};
  Work.runLanguage = function (lang) { return LANGS[String(lang || "").toLowerCase().trim()] || ""; };
  Work.runCode = function (lang, code, opts) {
    opts = opts || {};
    var language = Work.runLanguage(lang);
    if (!language) return Promise.resolve({ ok: false, error: "language" });
    return open().then(function () {
      return new Promise(function (resolve) {
        var id = ++seq;
        waiting[id] = { resolve: resolve, onLoading: opts.onLoading };
        frame.contentWindow.postMessage({ id: id, lang: language, code: String(code || ""), tests: opts.tests || "", expected: opts.expected || "",
                                          limit: opts.limit || 8000, warm: !!opts.warm }, "*");
      });
    });
  };
  /* Start fetching Python or SQLite while the question is read, so Run is quick. */
  var warmed = {};
  Work.warmRunner = function (lang) {
    var language = Work.runLanguage(lang);
    if (!language || language === "javascript" || warmed[language]) return;
    warmed[language] = true;
    Work.runCode(language, language === "sql" ? "SELECT 1" : "pass", { warm: true, limit: 2000 });
  };
  /* The first ```sql block of a model answer (or the whole of it when there's none). */
  Work.firstCode = function (markdown) {
    var m = /```[\w-]*\n([\s\S]*?)```/.exec(markdown || "");
    return m ? m[1].trim() : "";
  };
})();
