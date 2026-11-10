/* Writing in the Markdown boxes (notes, task notes, answers, cards, the
   journal…: textarea[data-paste-images], [data-md-paste] or [data-md]) and
   in code boxes (textarea[data-code]) — the keys an editor has:

   - Enter carries a list on ("- ", "1. ", "- [ ] ", "> "); Enter on an empty
     item ends the list. In a ``` block the line's indent is kept (one step
     more after ":", "{", "[" or "("), and ```lang + Enter closes the block.
   - Tab / Shift+Tab indent and outdent the line, or every chosen line
     (Esc first, then Tab, leaves the box — for keyboards).
   - Ctrl+B bold, Ctrl+I italic, Alt+↑ / Alt+↓ move the line(s).
   - "/" at the start of a line opens a menu of blocks (headings, to-dos,
     code, a table, a diagram, today's date…), as in Notion.
   - Pasting a link over chosen words makes [words](link); a reply copied
     from ChatGPT, Claude or a web page as formatted text comes in as
     Markdown (turndown, fetched the first time it's needed).

   Every change goes through the browser's own typing (insertText), so
   Ctrl+Z takes it back like anything typed. Typing Bangla (IME) is left alone. */
(function () {
  "use strict";
  var d = document;
  var MD = "textarea[data-paste-images], textarea[data-md-paste], textarea[data-md]";
  var TURNDOWN = ["https://cdn.jsdelivr.net/npm/turndown@7.2.0/dist/turndown.js",
                  "https://cdn.jsdelivr.net/npm/turndown-plugin-gfm@1.0.2/dist/turndown-plugin-gfm.js"];

  function box(e) {
    var ta = e.target;
    if (!ta || ta.tagName !== "TEXTAREA" || ta.readOnly || ta.disabled) return null;
    if (ta.matches("textarea[data-code]")) return "code";
    return ta.matches(MD) ? "md" : null;
  }

  // Replace [s, e) with text the way typing does (so Ctrl+Z undoes it), then choose [a, z).
  function put(ta, s, e, text, a, z) {
    ta.focus();
    ta.setSelectionRange(s, e);
    var ok = false;
    try { ok = text ? d.execCommand("insertText", false, text) : (s === e || d.execCommand("delete")); } catch (err) { ok = false; }
    if (!ok) {
      ta.setRangeText(text, s, e, "end");
      ta.dispatchEvent(new Event("input", { bubbles: true }));
    }
    if (a != null) ta.setSelectionRange(a, z == null ? a : z);
  }

  function lineStart(v, i) { return v.lastIndexOf("\n", i - 1) + 1; }
  function lineEnd(v, i) { var n = v.indexOf("\n", i); return n < 0 ? v.length : n; }
  function inFence(v, at) {      // is the caret inside a ``` block?
    return ((v.slice(0, lineStart(v, at)).match(/^[ \t]*(```|~~~)/gm) || []).length % 2) === 1;
  }
  var LIST = /^([ \t]*)([-*+] \[[ xX]\] |[-*+] |(\d+)([.)]) |> )/;

  function enter(ta, mode) {
    var v = ta.value, s = ta.selectionStart, e = ta.selectionEnd;
    if (s !== e) return false;
    var ls = lineStart(v, s), le = lineEnd(v, s), line = v.slice(ls, le), before = v.slice(ls, s);
    var indent = (/^[ \t]*/.exec(line) || [""])[0];
    var code = mode === "code" || inFence(v, s);
    if (code) {
      if (mode !== "code" && /^[ \t]*(```|~~~)[ \t]*$/.test(line)) return false;     // the closing fence: just a new line
      if (/[:{[(][ \t]*$/.test(before)) indent += "    ";
      if (indent.length > before.length) indent = before.match(/^[ \t]*/)[0];         // caret within the indent
      put(ta, s, e, "\n" + indent);
      return true;
    }
    // ```lang at the end of a line, not closed yet: close it and write inside
    var fence = /^([ \t]*)(```|~~~)[\w+#.-]*[ \t]*$/.exec(line);
    if (fence && s === le && ((v.match(/^[ \t]*(```|~~~)/gm) || []).length % 2) === 1) {
      var inner = "\n" + fence[1];
      put(ta, s, e, inner + inner + fence[2], s + inner.length);
      return true;
    }
    var m = LIST.exec(line);
    if (!m || s - ls < m[0].length) return false;
    if (!line.slice(m[0].length).trim() && s === le) {          // an empty item: the list ends here
      put(ta, ls, le, "", ls);
      return true;
    }
    var mark = m[3] ? (+m[3] + 1) + m[4] + " " : /\[[ xX]\]/.test(m[2]) ? m[2].charAt(0) + " [ ] " : m[2];
    put(ta, s, e, "\n" + m[1] + mark);
    return true;
  }

  // Tab / Shift+Tab: the chosen lines (or a list item) move in or out; elsewhere Tab types the indent.
  function tab(ta, mode, out) {
    var v = ta.value, s = ta.selectionStart, e = ta.selectionEnd;
    var unit = mode === "code" || inFence(v, s) ? "    " : "  ";
    var ls = lineStart(v, s), le = lineEnd(v, e > s && v.charAt(e - 1) === "\n" ? e - 1 : e);
    var many = v.slice(s, e).indexOf("\n") >= 0, item = LIST.test(v.slice(ls, lineEnd(v, s)));
    if (!out && !many && !item) { put(ta, s, e, unit); return; }
    var lines = v.slice(ls, le).split("\n"), first = 0, total = 0;
    var next = lines.map(function (l, i) {
      var n;
      if (out) { n = l.replace(new RegExp("^( {1," + unit.length + "}|\\t)"), ""); }
      else n = (l.trim() || !many ? unit : "") + l;
      if (i === 0) first = n.length - l.length;
      total += n.length - l.length;
      return n;
    }).join("\n");
    if (!total) return;
    var a = Math.max(ls, s + first), z = many || s !== e ? e + total : a;
    put(ta, ls, le, next, a, Math.max(a, z));
  }

  // Ctrl+B / Ctrl+I: wrap the chosen words (or take the marks off again)
  function wrap(ta, mark) {
    var v = ta.value, s = ta.selectionStart, e = ta.selectionEnd, n = mark.length;
    // (italic inside bold — **word** — gets its own marks: ***word***)
    if (v.slice(s - n, s) === mark && v.slice(e, e + n) === mark && (mark !== "*" || v.charAt(s - 2) !== "*" || v.slice(s - 3, s) === "***")) {
      put(ta, s - n, e + n, v.slice(s, e), s - n, e - n);
      return;
    }
    put(ta, s, e, mark + v.slice(s, e) + mark, s + n, e + n);
  }

  /* Highlighting the chosen words (Work.hl in work.js does the Markdown): color "yellow", "green"…, null takes it
     off, "toggle" uses the colour used last — or takes it off when the words are highlighted already (Ctrl+Shift+H).
     Only the part that changes is typed over, so Ctrl+Z takes it back. */
  function highlight(ta, color) {
    var H = window.Work && Work.hl;
    if (!H) return;
    var v = ta.value, s = ta.selectionStart, e = ta.selectionEnd;
    if (s === e) {                                          // nothing chosen: the word the caret is in
      var a = s, z = s;
      while (a > 0 && /[^\s=]/.test(v.charAt(a - 1))) a--;
      while (z < v.length && /[^\s=]/.test(v.charAt(z))) z++;
      if (a === z) return;
      s = a; e = z;
    }
    if (color === "toggle") color = inHighlight(v, s, e) ? null : H.last();
    if (color) H.remember(color);
    var r = H.apply(v, s, e, color), next = r.text;
    if (next === v) { ta.setSelectionRange(r.s, r.e); return; }
    var p = 0, q = 0;
    while (p < v.length && p < next.length && v.charAt(p) === next.charAt(p)) p++;
    while (q < v.length - p && q < next.length - p && v.charAt(v.length - 1 - q) === next.charAt(next.length - 1 - q)) q++;
    put(ta, p, v.length - q, next.slice(p, next.length - q), r.s, r.e);
  }
  function inHighlight(v, s, e) {
    return Work.hl.spans(v).some(function (h) { return s >= h.s && e <= h.e && e > h.inS && s < h.inE; });
  }

  // Alt+↑ / Alt+↓: the line (or the chosen lines) changes places with the one above or below
  function moveLines(ta, up) {
    var v = ta.value, s = ta.selectionStart, e = ta.selectionEnd;
    var ls = lineStart(v, s), le = lineEnd(v, e > s && v.charAt(e - 1) === "\n" ? e - 1 : e), block = v.slice(ls, le);
    if (up) {
      if (!ls) return;
      var ps = lineStart(v, ls - 1), prev = v.slice(ps, ls - 1);
      put(ta, ps, le, block + "\n" + prev, s - prev.length - 1, e - prev.length - 1);
    } else {
      if (le >= v.length) return;
      var ne = lineEnd(v, le + 1), nxt = v.slice(le + 1, ne);
      put(ta, ls, ne, nxt + "\n" + block, s + nxt.length + 1, e + nxt.length + 1);
    }
  }

  d.addEventListener("keydown", function (e) {
    var mode = box(e);
    if (!mode || e.defaultPrevented || e.isComposing || e.keyCode === 229) return;
    var ta = e.target, key = e.key, mod = e.ctrlKey || e.metaKey;
    if (key === "Escape") { ta._tabOut = true; return; }
    var leaving = ta._tabOut; ta._tabOut = false;
    if (key === "Tab" && !mod && !e.altKey) {
      if (leaving) return;
      e.preventDefault(); tab(ta, mode, e.shiftKey);
    } else if (key === "Enter" && !mod && !e.shiftKey && !e.altKey) {
      if (enter(ta, mode)) e.preventDefault();
    } else if (e.altKey && !mod && !e.shiftKey && (key === "ArrowUp" || key === "ArrowDown")) {
      e.preventDefault(); moveLines(ta, key === "ArrowUp");
    } else if (mode === "md" && mod && !e.altKey && !e.shiftKey && (key === "b" || key === "i")) {
      e.preventDefault(); wrap(ta, key === "b" ? "**" : "*");
    } else if (mode === "md" && mod && e.shiftKey && !e.altKey && (key === "h" || key === "H")) {
      e.preventDefault(); highlight(ta, "toggle");
    }
  });

  /* ── "/" at the start of a line (or after a space): a menu of blocks to put in, as in
     Notion or Obsidian — headings, to-dos, code, a table, a diagram… Typing filters it;
     ↑ ↓ and Enter (or a click) put one in; Esc, a space or a click elsewhere closes it. ── */
  function label(id, fallback) { var x = ((window.Work && Work.cfg && Work.cfg.text) || {}).slash || {}; return x[id] || fallback; }
  function pad(n) { return (n < 10 ? "0" : "") + n; }
  // what each puts in: "line" marks the start of the line; "block" goes on lines of its own; "|" is where the caret lands
  var BLOCKS = [
    { id: "h1", icon: "H1", line: "# ", words: "heading title" },
    { id: "h2", icon: "H2", line: "## ", words: "heading subtitle" },
    { id: "h3", icon: "H3", line: "### ", words: "heading" },
    { id: "todo", icon: "☐", line: "- [ ] ", words: "todo checkbox task check" },
    { id: "bullet", icon: "•", line: "- ", words: "bullet list unordered" },
    { id: "numbered", icon: "1.", line: "1. ", words: "numbered list ordered" },
    { id: "quote", icon: "❝", line: "> ", words: "quote blockquote" },
    { id: "callout", icon: "ℹ", line: "> **Note:** ", words: "callout note tip warning info" },
    { id: "code", icon: "{}", block: "```|\n\n```", words: "code block snippet fence" },
    { id: "python", icon: "py", block: "```python\n|\n```", words: "code python py" },
    { id: "js", icon: "js", block: "```js\n|\n```", words: "code javascript js typescript ts" },
    { id: "sql", icon: "sql", block: "```sql\n|\n```", words: "code sql query database" },
    { id: "bash", icon: "$_", block: "```bash\n|\n```", words: "code bash shell terminal command" },
    { id: "json", icon: "{ }", block: "```json\n|\n```", words: "code json yaml config" },
    { id: "mermaid", icon: "⇄", block: "```mermaid\nflowchart LR\n    A[|Start] --> B[End]\n```", words: "diagram mermaid flowchart sequence chart graph" },
    { id: "table", icon: "▦", block: "| | |\n| --- | --- |\n| | |", caretAt: 2, words: "table grid columns" },
    { id: "details", icon: "▸", block: "<details><summary>|</summary>\n\n\n\n</details>", words: "collapsible toggle details fold spoiler" },
    { id: "divider", icon: "—", block: "---\n|", words: "divider line rule hr separator" },
    { id: "math", icon: "∑", block: "$$\n|\n$$", words: "math formula equation latex katex", when: function () { return !!window.katex; } },
    { id: "link", icon: "[[", text: "[[|]]", words: "link note wiki page", when: notes },
    { id: "embed", icon: "![[", block: "![[|]]", words: "embed transclude include note show insert", when: notes },
    { id: "tasks", icon: "☑", block: "```tasks\ndue: week|\n```", words: "tasks list query filter live database board", when: notes },
    { id: "card", icon: "::", text: " :: |", words: "flashcard card question answer" },
    { id: "mark", icon: "==", text: "==|==", words: "highlight mark cloze blank hide" },
    { id: "date", icon: "📅", words: "date today now day", text: function () { var n = new Date(); return n.getFullYear() + "-" + pad(n.getMonth() + 1) + "-" + pad(n.getDate()) + "|"; } },
    { id: "time", icon: "🕑", words: "time now clock", text: function () { var n = new Date(); return pad(n.getHours()) + ":" + pad(n.getMinutes()) + "|"; } },
    { id: "dictate", icon: "🎙", words: "dictate voice speak speech microphone mic talk", when: function () { return !!Speech; }, run: function (ta) { dictate(ta); } },
  ];
  function notes(ta) { return ta.matches(".wn-body, textarea[data-note]"); }      // a note (the page, or opened on the board)
  var NAMES = { h1: "Heading 1", h2: "Heading 2", h3: "Heading 3", todo: "To-do", bullet: "Bulleted list", numbered: "Numbered list", quote: "Quote",
                callout: "Callout", code: "Code block", python: "Python code", js: "JavaScript code", sql: "SQL", bash: "Shell command", json: "JSON",
                mermaid: "Diagram (Mermaid)", table: "Table", details: "Collapsible section", divider: "Divider", math: "Formula",
                link: "Link to a note", embed: "Show another note here", tasks: "List of tasks (live)", dictate: "Dictate (speak to type)", card: "Flashcard (question :: answer)", mark: "Highlight (a blank in reviews)", date: "Today’s date", time: "Time now" };
  var slash = null;          // { ta, at, items, pick, el }

  function caretXY(ta, pos) {          // where the caret is on the page: a copy of the box, measured
    var st = getComputedStyle(ta), m = d.createElement("div"), r = ta.getBoundingClientRect();
    ["boxSizing", "width", "paddingTop", "paddingRight", "paddingBottom", "paddingLeft", "borderTopWidth", "borderLeftWidth", "fontFamily",
     "fontSize", "fontWeight", "lineHeight", "letterSpacing", "tabSize", "wordSpacing"].forEach(function (k) { m.style[k] = st[k]; });
    m.style.position = "absolute"; m.style.visibility = "hidden"; m.style.whiteSpace = "pre-wrap"; m.style.overflowWrap = "break-word"; m.style.top = "0"; m.style.left = "-9999px";
    m.textContent = ta.value.slice(0, pos);
    var mark = d.createElement("span"); mark.textContent = "\u200b"; m.appendChild(mark);
    d.body.appendChild(m);
    var x = r.left + mark.offsetLeft - ta.scrollLeft, y = r.top + mark.offsetTop - ta.scrollTop + mark.offsetHeight;
    m.remove();
    return { x: Math.min(x, r.right - 8), y: Math.min(Math.max(y, r.top + 16), r.bottom) };
  }
  function slashItems(ta, q) {
    q = q.toLowerCase();
    return BLOCKS.filter(function (b) {
      if (b.when && !b.when(ta)) return false;
      var name = label(b.id, NAMES[b.id]);
      return !q || (name + " " + NAMES[b.id] + " " + b.words + " " + b.id).toLowerCase().indexOf(q) >= 0;
    });
  }
  function closeSlash() { if (slash) { slash.el.remove(); slash = null; } }
  function drawSlash() {
    var el = slash.el;
    el.innerHTML = "";
    slash.items.forEach(function (b, i) {
      var row = d.createElement("button");
      row.type = "button"; row.className = "md-slash-item" + (i === slash.pick ? " is-on" : "");
      row.setAttribute("role", "option"); row.setAttribute("aria-selected", String(i === slash.pick));
      var ico = d.createElement("span"); ico.className = "md-slash-ico"; ico.textContent = b.icon;
      var name = d.createElement("span"); name.textContent = label(b.id, NAMES[b.id]);
      row.appendChild(ico); row.appendChild(name);
      row.addEventListener("mousedown", function (e) { e.preventDefault(); useSlash(b); });
      el.appendChild(row);
    });
    var on = el.children[slash.pick]; if (on && on.scrollIntoView) on.scrollIntoView({ block: "nearest" });
  }
  function openSlash(ta, at) {
    closeSlash();
    var el = d.createElement("div");
    el.className = "md-slash"; el.setAttribute("role", "listbox");
    d.body.appendChild(el);
    slash = { ta: ta, at: at, items: slashItems(ta, ""), pick: 0, el: el };
    drawSlash();
    var p = caretXY(ta, at), w = el.offsetWidth, h = el.offsetHeight;
    var left = Math.max(8, Math.min(p.x, window.innerWidth - w - 8)), top = p.y + 4;
    if (top + h > window.innerHeight - 8) top = Math.max(8, p.y - h - 24);       // no room below: above the line
    el.style.left = left + "px"; el.style.top = top + "px";
  }
  function useSlash(b) {
    var ta = slash.ta, at = slash.at, end = ta.selectionStart, v = ta.value;
    closeSlash();
    if (b.run) { put(ta, at, end, ""); b.run(ta); return; }          // (the "/word" typed goes)
    var ls = lineStart(v, at), before = v.slice(ls, at), text, caret;
    if (b.line) {                       // marks the line: "/h2" on "Plan" → "## Plan"
      var rest = v.slice(end, lineEnd(v, end));
      put(ta, ls, lineEnd(v, end), b.line + (before + rest).replace(/^([-*+] \[[ xX]\] |[-*+] |\d+[.)] |> |#{1,6} )/, "").trimStart(), ls + b.line.length + before.trimStart().length);
      return;
    }
    text = typeof b.text === "function" ? b.text() : (b.text || b.block);
    if (b.block) {
      if (before.trim()) text = "\n" + text;
      if (v.slice(end, lineEnd(v, end)).trim()) text += "\n";
    }
    caret = text.indexOf("|");
    if (b.caretAt != null) { caret = b.caretAt + (text.charAt(0) === "\n" ? 1 : 0); text = text.replace("|", ""); }
    else text = text.replace("|", "");
    put(ta, at, end, text, at + (caret < 0 ? text.length : caret));
  }
  d.addEventListener("input", function (e) {
    if (box(e) !== "md") return;
    var ta = e.target, at = ta.selectionStart, v = ta.value;
    if (slash && slash.ta === ta) {
      var q = v.slice(slash.at + 1, at);
      if (at <= slash.at || v.charAt(slash.at) !== "/" || /\s/.test(q) || q.length > 24) { closeSlash(); return; }
      slash.items = slashItems(ta, q); slash.pick = 0;
      if (!slash.items.length) { closeSlash(); return; }
      drawSlash();
      return;
    }
    if (e.inputType !== "insertText" || e.data !== "/" || ta.selectionStart !== ta.selectionEnd) return;
    var prev = v.charAt(at - 2);
    if (at > 1 && prev && !/\s/.test(prev)) return;          // a/b, http://… — not a command
    if (inFence(v, at)) return;
    openSlash(ta, at - 1);
  });
  // while the menu is open its keys come first (before the box's own: Enter, Esc closing a dialog…)
  d.addEventListener("keydown", function (e) {
    if (!slash || e.target !== slash.ta) return;
    var n = slash.items.length;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault(); e.stopPropagation();
      slash.pick = (slash.pick + (e.key === "ArrowDown" ? 1 : -1) + n) % n; drawSlash();
    } else if ((e.key === "Enter" || e.key === "Tab") && !e.shiftKey && !e.ctrlKey && !e.metaKey) {
      e.preventDefault(); e.stopPropagation(); useSlash(slash.items[slash.pick]);
    } else if (e.key === "Escape") {
      e.preventDefault(); e.stopPropagation(); closeSlash();
    }
  }, true);
  d.addEventListener("mousedown", function (e) { if (slash && !slash.el.contains(e.target)) closeSlash(); });
  d.addEventListener("focusout", function (e) { if (slash && e.target === slash.ta) setTimeout(function () { if (slash && d.activeElement !== slash.ta) closeSlash(); }, 0); });
  var slashW = window.innerWidth;      // a new width closes it — not a phone's keyboard coming up (the page resizes too)
  window.addEventListener("resize", function () { if (window.innerWidth !== slashW) { slashW = window.innerWidth; closeSlash(); } });
  d.addEventListener("scroll", function (e) { if (slash && e.target !== slash.el) closeSlash(); }, true);

  /* ── Speaking instead of typing: a microphone button ([data-dictate="selector"] — the box it types
     into, near the button) or "/dictate". The browser turns speech into text (Chrome and Edge send
     the sound to their speech service; Firefox has none, so there's no microphone there). The words
     go in where the caret is, as typed (Ctrl+Z takes them back), in the page's language (Bangla or
     English); pressing the button again, Esc, or leaving the box stops it. ── */
  var Speech = window.SpeechRecognition || window.webkitSpeechRecognition, hearing = null;
  function tell(key, fallback, tone) { if (window.Work && Work.toast) Work.toast(((Work.cfg && Work.cfg.text) || {})[key] || fallback, tone); }
  function listenFor() {
    var lang = (d.documentElement.lang || "en").toLowerCase();
    if (lang.indexOf("bn") === 0) return "bn-BD";
    return navigator.language && navigator.language.toLowerCase().indexOf(lang) === 0 ? navigator.language : "en-US";
  }
  function listening(on) {
    if (!hearing) return;
    hearing.field.classList.toggle("is-listening", on);
    d.querySelectorAll("[data-dictate]").forEach(function (b) {
      var mine = on && target(b) === hearing.field;
      b.classList.toggle("is-on", mine); b.setAttribute("aria-pressed", String(mine));
    });
  }
  function stopDictating() { if (hearing) hearing.rec.stop(); }
  function dictate(field) {
    if (hearing) { var same = hearing.field === field; hearing.rec.abort(); listening(false); hearing = null; if (same) return; }
    var rec = new Speech();
    rec.lang = listenFor(); rec.continuous = true; rec.interimResults = false;
    hearing = { rec: rec, field: field };
    rec.onresult = function (e) {
      for (var i = e.resultIndex; i < e.results.length; i++) {
        if (!e.results[i].isFinal) continue;
        var words = e.results[i][0].transcript.trim(); if (!words) continue;
        var s = field.selectionStart, end = field.selectionEnd, prev = field.value.charAt(s - 1);
        put(field, s, end, (s && prev && !/\s/.test(prev) ? " " : "") + words);
      }
    };
    rec.onerror = function (e) {
      if (e.error === "not-allowed" || e.error === "service-not-allowed") tell("micBlocked", "The microphone is blocked for this site.", "warn");
      else if (e.error !== "no-speech" && e.error !== "aborted") tell("dictateFailed", "Couldn't hear that — try again.", "warn");
    };
    rec.onend = function () { if (hearing && hearing.rec === rec) { listening(false); hearing = null; } };
    try { rec.start(); } catch (err) { hearing = null; return; }
    listening(true);
    field.focus();
    tell("listening", "Listening…");
  }
  function target(btn) {
    var sel = btn.getAttribute("data-dictate"), scope = btn.closest("[data-dictate-scope]") || d;
    return Array.prototype.find.call(scope.querySelectorAll(sel), function (el) { return el.offsetParent !== null || el.getClientRects().length; }) || null;
  }
  if (Speech) d.documentElement.classList.add("can-dictate");
  d.addEventListener("click", function (e) {
    var b = e.target.closest && e.target.closest("[data-dictate]"); if (!b || !Speech) return;
    e.preventDefault();
    var field = target(b); if (field) dictate(field);
  });
  d.addEventListener("mousedown", function (e) { if (e.target.closest && e.target.closest("[data-dictate]")) e.preventDefault(); });   // the box keeps the caret
  d.addEventListener("keydown", function (e) { if (hearing && e.key === "Escape" && e.target === hearing.field) stopDictating(); }, true);
  d.addEventListener("focusout", function (e) {
    if (hearing && e.target === hearing.field) setTimeout(function () { if (hearing && d.activeElement !== hearing.field && !(d.activeElement && d.activeElement.closest("[data-dictate]"))) stopDictating(); }, 200);
  });

  /* ── Pasting ── */
  var turndown = null, loading = null;
  function loadTurndown() {
    if (window.TurndownService) return Promise.resolve();
    if (!loading) loading = TURNDOWN.reduce(function (p, src) {
      return p.then(function () {
        return new Promise(function (resolve, reject) {
          var s = d.createElement("script"); s.src = src; s.onload = resolve;
          s.onerror = function () { loading = null; reject(new Error("turndown")); };
          d.head.appendChild(s);
        });
      });
    }, Promise.resolve());
    return loading;
  }
  function toMarkdown(html) {
    if (!turndown) {
      turndown = new TurndownService({ headingStyle: "atx", codeBlockStyle: "fenced", bulletListMarker: "-", emDelimiter: "*", hr: "---" });
      if (window.turndownPluginGfm) turndown.use(turndownPluginGfm.gfm);
      turndown.remove(["button", "style", "script", "svg"]);           // "Copy code" buttons and icons
      turndown.addRule("math", {                                        // KaTeX keeps the formula it drew
        filter: function (n) { return n.classList && (n.classList.contains("katex-display") || n.classList.contains("katex")); },
        replacement: function (content, n) {
          var a = n.querySelector('annotation[encoding="application/x-tex"]');
          if (!a) return content;
          var tex = a.textContent.trim();
          return n.classList.contains("katex-display") ? "\n\n$$" + tex + "$$\n\n" : "$" + tex + "$";
        },
      });
      turndown.addRule("code", {                                        // a code box: its language and its code, not its toolbar
        filter: function (n) { return n.nodeName === "PRE"; },
        replacement: function (content, n) {
          var c = n.querySelector("code") || n, lang = ((c.className || "").match(/language-([\w+#.-]+)/) || [])[1] || n.getAttribute("data-lang") || "";
          return "\n\n```" + lang + "\n" + c.textContent.replace(/\n+$/, "") + "\n```\n\n";
        },
      });
    }
    // "-   item" → "- item" (turndown lines items up to four columns), outside code blocks
    return turndown.turndown(html).split(/(```[\s\S]*?```)/).map(function (part, i) {
      return i % 2 ? part : part.replace(/^([ \t]*)([-*+]|\d+\.) {2,}/gm, "$1$2 ");
    }).join("").replace(/\n{3,}/g, "\n\n").trim();
  }
  function looksLikeMarkdown(text) {
    return /(^|\n)\s{0,3}(#{1,6}\s|```|[-*+]\s|\d+[.)]\s|>\s|\|.*\|)|\*\*[^*\n]+\*\*|`[^`\n]+`|\$[^$\n]+\$/.test(text || "");
  }
  /* ── Phones: the keyboard never hides the line being written ──
     The keyboard covers the bottom of the screen, and the browser only makes sure the box is on
     screen — not the line inside it (a long note is taller than what's left). So after every caret
     move, keystroke and keyboard change, the caret's line is measured, and if it's under the
     keyboard, under the bar on top of it or under a header stuck at the top, the pop-up it's in (or
     the page) scrolls just enough to show it, with a line to spare. Touch screens only: a mouse and
     a desktop browser do this well already. */
  var TOUCH = !!(window.matchMedia && matchMedia("(pointer: coarse)").matches);
  var VV = window.visualViewport, root = d.documentElement, kbar = null, keepQueued = false;
  function t2(group, key, fallback) { var x = ((window.Work && Work.cfg && Work.cfg.text) || {})[group] || {}; return x[key] || fallback; }
  function barOn() { return !!(kbar && kbar.classList.contains("is-on")); }
  function view() {        // the part of the page that can be seen, in getBoundingClientRect's terms
    var top = VV ? VV.offsetTop : 0, h = VV ? VV.height : window.innerHeight;
    return { top: top, bottom: top + h - (barOn() ? kbar.offsetHeight : 0) };
  }
  function coverTop(ta, x, y) {     // a header stuck at the top over the box: where it ends
    var el = d.elementFromPoint(x, y + 2);
    for (; el && el !== d.body && el !== root; el = el.parentElement) {
      if (el.contains(ta)) return y;                  // the pop-up the box is in, not a header over it
      var p = getComputedStyle(el).position;
      if (p === "fixed" || p === "sticky") {
        var b = el.getBoundingClientRect().bottom;
        // a header is a strip; something covering most of the screen (a pop-up's backdrop) isn't one
        return b - y < (window.innerHeight - y) * 0.4 ? Math.max(y, b) : y;
      }
    }
    return y;
  }
  // the boxes it's in that scroll (a pop-up) first, then the page — at once: following the caret
  // with the page's smooth scrolling would land each step where the last one was still going
  function scrollBy(ta, dy) {
    for (var el = ta.parentElement; el && el !== d.body && el !== root && Math.abs(dy) > 0.5; el = el.parentElement) {
      var oy = getComputedStyle(el).overflowY;
      if ((oy === "auto" || oy === "scroll") && el.scrollHeight > el.clientHeight + 1) {
        var was = el.scrollTop; el.scrollTo({ top: was + dy, behavior: "instant" }); dy -= el.scrollTop - was;
      }
    }
    if (Math.abs(dy) > 0.5) window.scrollTo({ top: window.scrollY + dy, behavior: "instant" });
  }
  function lineHeight(ta) { var cs = getComputedStyle(ta); return parseFloat(cs.lineHeight) || (parseFloat(cs.fontSize) || 16) * 1.5; }
  // show the text at [y - lh, y] (y: the bottom of a line, as caretXY gives it) between the header and the keyboard
  function showY(ta, y, minTop) {
    var lh = lineHeight(ta), v = view(), r = ta.getBoundingClientRect();
    var top = Math.max(coverTop(ta, Math.max(r.left + 8, 1), v.top), minTop || 0) + 8, bottom = v.bottom - 8;
    if (bottom - top < lh * 2.5) return;               // hardly any room (a phone on its side): the browser's own way
    if (y > bottom) scrollBy(ta, y - bottom + lh);
    else if (y - lh < top) scrollBy(ta, y - lh - top - lh);
  }
  function keepCaret() {
    keepQueued = false;
    var ta = d.activeElement;
    if (!box({ target: ta }) || ta.selectionStart !== ta.selectionEnd) return;      // choosing words: the handles are the person's
    showY(ta, caretXY(ta, ta.selectionEnd).y);
  }
  function queueKeep() { if (TOUCH && !keepQueued) { keepQueued = true; requestAnimationFrame(keepCaret); } }

  /* ── A row of buttons riding on the keyboard (Bear, Apple Notes, Notion): undo, the "/" blocks,
     heading, bold, italic, to-do, lists, indent, link, move the line, find — and Done to put the
     keyboard away. Each press keeps the caret in the box (the keyboard stays up) and types the way
     the keys do, so Undo takes it back. Every Markdown box on a touch screen has it. ── */
  var HEAD = /^(#{1,6} )/, MARKS = /^(#{1,6} |[-*+] \[[ xX]\] |[-*+] |\d+[.)] |> )/;
  function lineMark(ta, mark) {             // mark the start of each chosen line, or take it off when they all have it
    var v = ta.value, s = ta.selectionStart, e = ta.selectionEnd, ls = lineStart(v, s), le = lineEnd(v, e > s && v.charAt(e - 1) === "\n" ? e - 1 : e);
    var lines = v.slice(ls, le).split("\n");
    var all = lines.every(function (l) { return !l.trim() || l.replace(/^[ \t]*/, "").indexOf(mark) === 0; });
    var out = lines.map(function (l) {
      if (!l.trim() && lines.length > 1) return l;
      var ind = /^[ \t]*/.exec(l)[0], rest = l.slice(ind.length);
      return ind + (all ? rest.slice(mark.length) : mark + rest.replace(MARKS, ""));
    }).join("\n");
    if (lines.length > 1) put(ta, ls, le, out, ls, ls + out.length);
    else put(ta, ls, le, out, Math.max(ls, s + out.length - (le - ls)));
  }
  function heading(ta) {                     // none → # → ## → ### → none
    var v = ta.value, s = ta.selectionStart, ls = lineStart(v, s), le = lineEnd(v, s), line = v.slice(ls, le);
    var m = HEAD.exec(line), n = m ? m[1].length - 1 : 0, rest = line.replace(MARKS, "");
    var next = n >= 3 ? rest : new Array(n + 2).join("#") + " " + rest;
    put(ta, ls, le, next, Math.max(ls, s + next.length - line.length));
  }
  function link(ta) {
    var v = ta.value, s = ta.selectionStart, e = ta.selectionEnd, sel = v.slice(s, e);
    if (/^https?:\/\/\S+$/.test(sel)) put(ta, s, e, "[](" + sel + ")", s + 1);
    else put(ta, s, e, "[" + sel + "]()", s + sel.length + 3);
  }
  function slashHere(ta) {
    var v = ta.value, s = ta.selectionStart, prev = v.charAt(s - 1);
    if (s > 0 && prev && !/\s/.test(prev)) { put(ta, s, ta.selectionEnd, " "); s += 1; }
    put(ta, s, ta.selectionEnd, "/");
  }
  var KEYS = [
    ["undo", '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/></svg>', "Undo"],
    ["redo", '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m15 14 5-5-5-5"/><path d="M20 9H9.5a5.5 5.5 0 0 0 0 11H13"/></svg>', "Redo"],
    ["slash", "<b>/</b>", "Insert a block"], ["h", "<b>H</b>", "Heading"], ["b", "<b>B</b>", "Bold"], ["i", "<i>I</i>", "Italic"],
    ["todo", '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3.5" y="3.5" width="17" height="17" rx="4"/><path d="m8 12 3 3 5-6"/></svg>', "To-do"],
    ["ul", '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M9 6h11M9 12h11M9 18h11"/><circle cx="4.5" cy="6" r="1" fill="currentColor"/><circle cx="4.5" cy="12" r="1" fill="currentColor"/><circle cx="4.5" cy="18" r="1" fill="currentColor"/></svg>', "Bulleted list"],
    ["ol", "<b>1.</b>", "Numbered list"],
    ["out", '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 6H11M21 12h-8M21 18H11M7 8l-4 4 4 4"/></svg>', "Outdent"],
    ["in", '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 6H11M21 12h-8M21 18H11M3 8l4 4-4 4"/></svg>', "Indent"],
    ["link", '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7"/><path d="M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7"/></svg>', "Link"],
    ["quote", "<b>❝</b>", "Quote"], ["code", "<b>&lt;/&gt;</b>", "Code"], ["mark", '<span class="md-k-mark">H</span>', "Highlight"], ["s", "<s>S</s>", "Strikethrough"],
    ["up", '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5M6 11l6-6 6 6"/></svg>', "Move line up"],
    ["down", '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14M6 13l6 6 6-6"/></svg>', "Move line down"],
    ["find", '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="6.5"/><path d="m20 20-4.2-4.2"/></svg>', "Find and replace"],
  ];
  function press(ta, k) {
    if (k === "undo" || k === "redo") { ta.focus(); try { d.execCommand(k); } catch (err) { /* not offered here */ } }
    else if (k === "slash") slashHere(ta);
    else if (k === "h") heading(ta);
    else if (k === "b") wrap(ta, "**");
    else if (k === "i") wrap(ta, "*");
    else if (k === "s") wrap(ta, "~~");
    else if (k === "code") wrap(ta, "`");
    else if (k === "mark") highlight(ta, "toggle");
    else if (k === "todo") lineMark(ta, "- [ ] ");
    else if (k === "ul") lineMark(ta, "- ");
    else if (k === "ol") lineMark(ta, "1. ");
    else if (k === "quote") lineMark(ta, "> ");
    else if (k === "in" || k === "out") tab(ta, "md", k === "out");
    else if (k === "up" || k === "down") moveLines(ta, k === "up");
    else if (k === "link") link(ta);
    else if (k === "find") openFind(ta, false);
    else if (k === "done") { closeSlash(); ta.blur(); }
    queueKeep();
  }
  function makeBar() {
    kbar = d.createElement("div");
    kbar.className = "md-kbar"; kbar.setAttribute("role", "toolbar"); kbar.setAttribute("aria-label", t2("kbar", "bar", "Formatting"));
    var row = d.createElement("div"); row.className = "md-kbar-row";
    KEYS.forEach(function (k) {
      var b = d.createElement("button"); b.type = "button"; b.className = "md-kbar-btn"; b.setAttribute("data-k", k[0]); b.tabIndex = -1;
      var name = t2("kbar", k[0], k[2]); b.setAttribute("aria-label", name); b.title = name; b.innerHTML = k[1];
      row.appendChild(b);
    });
    var done = d.createElement("button"); done.type = "button"; done.className = "md-kbar-done"; done.setAttribute("data-k", "done"); done.tabIndex = -1;
    done.textContent = t2("kbar", "done", "Done");
    kbar.appendChild(row); kbar.appendChild(done);
    // the box keeps the caret (and the keyboard stays up): no button takes the focus
    kbar.addEventListener("mousedown", function (e) { e.preventDefault(); });
    kbar.addEventListener("pointerdown", function (e) { if (e.pointerType === "mouse") e.preventDefault(); });
    kbar.addEventListener("click", function (e) {
      var b = e.target.closest("[data-k]"), ta = kbar._ta;
      if (!b || !ta || !d.contains(ta)) return;
      press(ta, b.getAttribute("data-k"));
    });
    d.body.appendChild(kbar);
  }
  function placeBar() {
    if (VV) {      // what's above the keyboard, for the sheets being written in (work.css)
      root.style.setProperty("--vvh", Math.round(VV.height) + "px");
      root.style.setProperty("--vvt", Math.round(VV.offsetTop) + "px");
      root.style.setProperty("--kb", Math.max(0, Math.round(window.innerHeight - VV.height - VV.offsetTop)) + "px");
    }
    if (!barOn()) return;
    var bottom = VV ? VV.offsetTop + VV.height : window.innerHeight;
    kbar.style.top = Math.round(bottom - kbar.offsetHeight) + "px";
    root.style.setProperty("--kbar-h", kbar.offsetHeight + "px");
  }
  function showBar(ta) {
    if (!kbar) makeBar();
    kbar._ta = ta; kbar.classList.add("is-on"); root.setAttribute("data-md-typing", "");
    placeBar();
  }
  function hideBar() {
    if (!kbar) return;
    kbar.classList.remove("is-on"); kbar._ta = null; root.removeAttribute("data-md-typing"); root.style.removeProperty("--kbar-h");
  }
  if (TOUCH) {
    d.addEventListener("focusin", function (e) {
      var mode = box(e);
      if (mode === "md") showBar(e.target); else hideBar();
      if (mode) { queueKeep(); setTimeout(queueKeep, 400); }      // and again once the keyboard is up
    });
    d.addEventListener("focusout", function (e) {
      if (!box(e)) return;
      setTimeout(function () { if (box({ target: d.activeElement }) !== "md") hideBar(); }, 0);
    });
    d.addEventListener("input", function (e) { if (box(e)) queueKeep(); });
    d.addEventListener("selectionchange", function () { if (box({ target: d.activeElement })) queueKeep(); });
    if (VV) {
      // the keyboard slides up in steps: the caret is checked as it goes and once it has settled
      var settle = null;
      VV.addEventListener("resize", function () {
        placeBar(); queueKeep(); if (find) drawFind();
        clearTimeout(settle); settle = setTimeout(function () { placeBar(); queueKeep(); }, 250);
      });
      VV.addEventListener("scroll", function () { placeBar(); if (find) drawFind(); });
    }
  }

  /* ── Words chosen with a mouse: a small bar over them (Notion, OneNote, Medium) — bold, italic,
     strikethrough, code, highlight, link, heading. The same buttons as the row on a phone's keyboard
     (which has them already), so Ctrl+Z takes any of them back. ── */
  var bub = null;
  var BUB = ["b", "i", "s", "code", "mark", "link", "h"];
  function bubbleHide() { if (bub) { bub.classList.remove("is-on"); bub._ta = null; } }
  function bubbleShow(ta) {
    if (TOUCH || d.activeElement !== ta || box({ target: ta }) !== "md") return bubbleHide();
    var s = ta.selectionStart, e = ta.selectionEnd;
    if (s === e || !ta.value.slice(s, e).trim() || (slash && slash.ta === ta)) return bubbleHide();
    var rs = rangeRects(ta, s, e);
    if (!rs.length) return bubbleHide();
    if (!bub) {
      bub = d.createElement("div"); bub.className = "md-bubble"; bub.setAttribute("role", "toolbar"); bub.setAttribute("aria-label", t2("kbar", "bar", "Formatting"));
      bub.innerHTML = BUB.map(function (k) {
        if (k === "mark") return hlDots();
        var key = KEYS.filter(function (x) { return x[0] === k; })[0], name = t2("kbar", k, key[2]);
        return '<button type="button" class="md-bubble-btn" data-k="' + k + '" tabindex="-1" title="' + name.replace(/"/g, "&quot;") + '" aria-label="' + name.replace(/"/g, "&quot;") + '">' + key[1] + "</button>";
      }).join("");
      bub.addEventListener("mousedown", function (ev) { ev.preventDefault(); });           // the words stay chosen
      bub.addEventListener("click", function (ev) {
        var dot = ev.target.closest("[data-hl-c]"), on0 = bub._ta;
        if (dot && on0) { highlight(on0, dot.getAttribute("data-hl-c") || null); setTimeout(function () { bubbleShow(on0); }, 0); return; }
        var b = ev.target.closest("[data-k]"), on = bub._ta; if (!b || !on) return;
        press(on, b.getAttribute("data-k"));
        setTimeout(function () { bubbleShow(on); }, 0);
      });
      d.body.appendChild(bub);
    }
    bub._ta = ta; bub.classList.add("is-on");
    var H = window.Work && Work.hl, last = H ? H.last() : "yellow";
    bub.classList.toggle("has-marks", !!(H && H.spans(ta.value).some(function (h) { return h.s < e && h.e > s; })));
    bub.querySelectorAll("[data-hl-c]").forEach(function (b) { b.classList.toggle("is-last", b.getAttribute("data-hl-c") === last); });
    var first = rs[0], last = rs[rs.length - 1], w = bub.offsetWidth, h = bub.offsetHeight;
    var top = first.top - h - 8;
    if (top < 8) top = last.top + last.height + 8;                // no room above: under the words
    var left = Math.max(8, Math.min(first.left + (rs.length === 1 ? first.width / 2 : 0) - (rs.length === 1 ? w / 2 : 0), innerWidth - w - 8));
    bub.style.top = Math.round(top) + "px"; bub.style.left = Math.round(left) + "px";
  }
  // the highlight colours in the bubble (and "take it off", shown when the words touch a highlight)
  function hlDots() {
    var cols = (window.Work && Work.hl && Work.hl.colors) || ["yellow"], T = (window.Work && Work.cfg && Work.cfg.text) || {};
    var names = { yellow: T.hlYellow || "Yellow", green: T.hlGreen || "Green", blue: T.hlBlue || "Blue", pink: T.hlPink || "Pink", purple: T.hlPurple || "Purple" };
    var q = function (v) { return String(v).replace(/"/g, "&quot;"); };
    return '<span class="md-bubble-sep" aria-hidden="true"></span>' + cols.map(function (c) {
      var name = (T.hlIn || "Highlight: %(colour)s").replace("%(colour)s", names[c]);
      return '<button type="button" class="hl-dot" data-hl-c="' + c + '" tabindex="-1" title="' + q(name) + '" aria-label="' + q(name) + '"></button>';
    }).join("") + '<button type="button" class="hl-dot hl-off" data-hl-c="" tabindex="-1" title="' + q(T.hlRemove || "Take the highlight off") + '" aria-label="' + q(T.hlRemove || "Take the highlight off") +
      '"><svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M6 6l12 12M18 6 6 18"/></svg></button><span class="md-bubble-sep" aria-hidden="true"></span>';
  }
  if (!TOUCH) {
    d.addEventListener("mouseup", function (e) { if (box(e) === "md") { var ta = e.target; setTimeout(function () { bubbleShow(ta); }, 0); } });
    d.addEventListener("keyup", function (e) { if (box(e) === "md" && (e.shiftKey || ((e.ctrlKey || e.metaKey) && e.key === "a"))) bubbleShow(e.target); });
    d.addEventListener("selectionchange", function () { if (bub && bub._ta && (d.activeElement !== bub._ta || bub._ta.selectionStart === bub._ta.selectionEnd)) bubbleHide(); });
    d.addEventListener("input", function (e) { if (bub && e.target === bub._ta) bubbleHide(); });
    d.addEventListener("focusout", function (e) { if (bub && e.target === bub._ta) bubbleHide(); });
    d.addEventListener("keydown", function (e) { if (bub && bub._ta && e.key === "Escape" && bub.classList.contains("is-on")) { e.preventDefault(); e.stopPropagation(); bubbleHide(); } }, true);
    d.addEventListener("scroll", function () { if (bub && bub._ta) bubbleShow(bub._ta); }, true);
  }

  /* ── Find and replace in a Markdown box (Ctrl+F or Ctrl+H in it, the 🔍 over the keyboard, or a
     note's ⋯ menu): the matches are counted and the one you're on is marked in the text and scrolled
     into view; Enter goes to the next, Shift+Enter back; Replace changes that one, All every one
     (Ctrl+Z takes either back). Esc closes it. ── */
  var find = null;      // { ta, el, q, rep, cs, at, hits, marks }
  function esc(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); }
  function hitsOf(ta, q, cs) {
    var out = []; if (!q) return out;
    var re = new RegExp(esc(q), cs ? "g" : "gi"), v = ta.value, m;
    while ((m = re.exec(v)) && out.length < 5000) { out.push(m.index); if (!m[0].length) re.lastIndex++; }
    return out;
  }
  function rangeRects(ta, s, e) {           // where [s, e) of the box's text is on the screen: a copy of the box, measured
    var st = getComputedStyle(ta), m = d.createElement("div"), r = ta.getBoundingClientRect();
    ["boxSizing", "width", "paddingTop", "paddingRight", "paddingBottom", "paddingLeft", "borderTopWidth", "borderRightWidth", "borderBottomWidth",
     "borderLeftWidth", "borderStyle", "fontFamily", "fontSize", "fontWeight", "lineHeight", "letterSpacing", "tabSize", "wordSpacing"].forEach(function (k) { m.style[k] = st[k]; });
    m.style.borderColor = "transparent";
    m.style.position = "absolute"; m.style.visibility = "hidden"; m.style.whiteSpace = "pre-wrap"; m.style.overflowWrap = "break-word"; m.style.top = "0"; m.style.left = "0";
    m.textContent = ta.value.slice(0, s);
    var mark = d.createElement("span"); mark.textContent = ta.value.slice(s, e) || "​"; m.appendChild(mark);
    m.appendChild(d.createTextNode(ta.value.slice(e)));
    d.body.appendChild(m);
    var base = m.getBoundingClientRect(), out = [].map.call(mark.getClientRects(), function (q) {
      return { left: r.left + q.left - base.left - ta.scrollLeft, top: r.top + q.top - base.top - ta.scrollTop, width: q.width, height: q.height };
    });
    m.remove();
    return out.filter(function (q) { return q.top + q.height > r.top && q.top < r.bottom; });
  }
  function drawFind() {
    if (!find) return;
    var f = find, n = f.hits.length;
    if (TOUCH && VV) f.el.style.top = Math.round(VV.offsetTop + 8) + "px";
    f.count.textContent = f.q ? (n ? (f.at + 1) + " / " + n : t2("find", "none", "No matches")) : "";
    f.el.classList.toggle("is-none", !!f.q && !n);
    f.marks.forEach(function (x) { x.remove(); }); f.marks = [];
    if (!n || !d.contains(f.ta) || !f.ta.getClientRects().length) return;
    var s = f.hits[f.at];
    rangeRects(f.ta, s, s + f.q.length).forEach(function (q) {
      var x = d.createElement("div"); x.className = "md-find-hit";
      x.style.left = (q.left + window.scrollX) + "px"; x.style.top = (q.top + window.scrollY) + "px";
      x.style.width = Math.max(q.width, 3) + "px"; x.style.height = q.height + "px";
      d.body.appendChild(x); f.marks.push(x);
    });
  }
  function goFind(step) {
    if (!find) return;
    var f = find; f.hits = hitsOf(f.ta, f.q, f.cs);
    if (!f.hits.length) { f.at = 0; drawFind(); return; }
    if (step == null) {                           // the first match from the caret on
      var from = f.ta.selectionStart, i = 0;
      while (i < f.hits.length && f.hits[i] < from) i++;
      f.at = i % f.hits.length;
    } else f.at = (f.at + step + f.hits.length) % f.hits.length;
    var s = f.hits[f.at], rs = rangeRects(f.ta, s, s + f.q.length);
    if (!rs.length) {                                 // inside a box that scrolls itself: bring it there first
      var lh = lineHeight(f.ta); f.ta.scrollTop = Math.max(0, caretXY(f.ta, s).y - f.ta.getBoundingClientRect().top + f.ta.scrollTop - lh * 3);
      rs = rangeRects(f.ta, s, s + f.q.length);
    }
    if (rs.length) showY(f.ta, rs[0].top + rs[0].height, f.el.getBoundingClientRect().bottom);
    drawFind();
  }
  function replaceOne() {
    var f = find; if (!f || !f.hits.length) return;
    var s = f.hits[f.at], keep = d.activeElement;
    put(f.ta, s, s + f.q.length, f.rep.value, s + f.rep.value.length);
    if (keep && f.el.contains(keep)) keep.focus({ preventScroll: true });
    // on to the next one after what was put in (which may match too: "note" → "Note")
    var after = s + f.rep.value.length, i = 0;
    f.hits = hitsOf(f.ta, f.q, f.cs);
    while (i < f.hits.length && f.hits[i] < after) i++;
    f.at = f.hits.length ? i % f.hits.length : 0;
    goFind(0);
  }
  function replaceAll() {
    var f = find; if (!f || !f.hits.length) return;
    var n = f.hits.length, keep = d.activeElement;
    var next = f.ta.value.replace(new RegExp(esc(f.q), f.cs ? "g" : "gi"), function () { return f.rep.value; });
    put(f.ta, 0, f.ta.value.length, next, 0);
    if (keep && f.el.contains(keep)) keep.focus({ preventScroll: true });
    goFind(null);
    if (window.Work && Work.toast) Work.toast(t2("find", "replaced", "Replaced %(n)s").replace("%(n)s", n));
  }
  function closeFind(back) {
    if (!find) return;
    var f = find; find = null;
    f.marks.forEach(function (x) { x.remove(); }); f.el.remove();
    if (back && d.contains(f.ta)) {
      f.ta.focus({ preventScroll: true });
      if (f.hits.length) { var s = f.hits[f.at] || 0; f.ta.setSelectionRange(s, s + f.q.length); }
    }
  }
  function openFind(ta, replacing) {
    if (find && find.ta === ta) { find.el.classList.toggle("is-replacing", !!replacing || find.el.classList.contains("is-replacing")); find.input.focus(); find.input.select(); return; }
    closeFind(false);
    var el = d.createElement("div");
    el.className = "md-find" + (replacing ? " is-replacing" : ""); el.setAttribute("role", "search");
    el.innerHTML =
      '<div class="md-find-row"><input type="search" class="md-find-q" enterkeyhint="search" autocomplete="off" spellcheck="false">' +
      '<span class="md-find-n num" aria-live="polite"></span>' +
      '<button type="button" class="md-find-btn" data-f="case"><span aria-hidden="true">Aa</span></button>' +
      '<button type="button" class="md-find-btn" data-f="prev"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m6 15 6-6 6 6"/></svg></button>' +
      '<button type="button" class="md-find-btn" data-f="next"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"/></svg></button>' +
      '<button type="button" class="md-find-btn" data-f="more"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 7h11M4 12h7M4 17h11M17 10l3 3-3 3"/></svg></button>' +
      '<button type="button" class="md-find-btn" data-f="close"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 6l12 12M18 6 6 18"/></svg></button></div>' +
      '<div class="md-find-row md-find-rep"><input type="text" class="md-find-r" enterkeyhint="done" autocomplete="off" spellcheck="false">' +
      '<button type="button" class="md-find-act" data-f="one"></button><button type="button" class="md-find-act" data-f="all"></button></div>';
    var names = { "case": ["case", "Match case"], prev: ["prev", "Previous"], next: ["next", "Next"], more: ["showReplace", "Replace…"], close: ["close", "Close"] };
    Object.keys(names).forEach(function (k) { var b = el.querySelector('[data-f="' + k + '"]'); b.setAttribute("aria-label", t2("find", names[k][0], names[k][1])); b.title = b.getAttribute("aria-label"); });
    el.querySelector('[data-f="case"]').setAttribute("aria-pressed", "false");
    el.querySelector('[data-f="one"]').textContent = t2("find", "one", "Replace");
    el.querySelector('[data-f="all"]').textContent = t2("find", "all", "All");
    var input = el.querySelector(".md-find-q"), rep = el.querySelector(".md-find-r");
    input.placeholder = t2("find", "find", "Find"); input.setAttribute("aria-label", input.placeholder);
    rep.placeholder = t2("find", "replace", "Replace with"); rep.setAttribute("aria-label", rep.placeholder);
    d.body.appendChild(el);
    find = { ta: ta, el: el, input: input, rep: rep, count: el.querySelector(".md-find-n"), q: "", cs: false, at: 0, hits: [], marks: [] };
    var chosen = ta.value.slice(ta.selectionStart, ta.selectionEnd);
    if (chosen && chosen.indexOf("\n") < 0 && chosen.length < 80) { input.value = chosen; find.q = chosen; }
    input.addEventListener("input", function () { if (find) { find.q = input.value; goFind(null); } });
    el.addEventListener("keydown", function (e) {
      if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); closeFind(true); }
      else if (e.key === "Enter" && e.target === input) { e.preventDefault(); goFind(e.shiftKey ? -1 : 1); }
      else if (e.key === "Enter" && e.target === rep) { e.preventDefault(); if (e.ctrlKey || e.metaKey || e.altKey) replaceAll(); else replaceOne(); }
    });
    el.addEventListener("mousedown", function (e) { if (e.target.closest("button")) e.preventDefault(); });     // the field keeps the keyboard
    el.addEventListener("click", function (e) {
      var b = e.target.closest("[data-f]"); if (!b || !find) return;
      var k = b.getAttribute("data-f");
      if (k === "close") closeFind(true);
      else if (k === "prev" || k === "next") goFind(k === "prev" ? -1 : 1);
      else if (k === "case") { find.cs = !find.cs; b.setAttribute("aria-pressed", String(find.cs)); goFind(null); }
      else if (k === "more") { el.classList.toggle("is-replacing"); if (el.classList.contains("is-replacing")) rep.focus(); }
      else if (k === "one") replaceOne();
      else if (k === "all") replaceAll();
    });
    input.focus(); input.select();
    goFind(null);
  }
  d.addEventListener("keydown", function (e) {
    if (box(e) !== "md" || e.altKey || !(e.ctrlKey || e.metaKey) || e.shiftKey) return;
    if (e.key === "f" || e.key === "h") { e.preventDefault(); openFind(e.target, e.key === "h"); }
  });
  d.addEventListener("input", function (e) { if (find && e.target === find.ta) { find.hits = hitsOf(find.ta, find.q, find.cs); if (find.at >= find.hits.length) find.at = 0; drawFind(); } });
  window.addEventListener("resize", function () { if (find) drawFind(); });
  d.addEventListener("scroll", function () { if (find) drawFind(); }, true);
  d.addEventListener("mousedown", function (e) {           // a click in the text leaves the bar open, anywhere else closes it
    if (find && !find.el.contains(e.target) && e.target !== find.ta && !(kbar && kbar.contains(e.target))) closeFind(false);
  });

  /* ── To-do lists (Google Keep): ticked items sink to the bottom of their list, all of them get
     unticked (the same shopping list next week) or the ticked ones go. Lines inside ``` blocks are
     left alone, and an item's own indented lines go with it. ── */
  var TODO = /^([ \t]*)[-*+] \[([ xX])\] /;
  function indentOf(l) { return /^[ \t]*/.exec(l)[0].length; }
  function todos(text, how) {
    var n = 0;
    function run(lines) {
      var out = [], code = false, i = 0;
      while (i < lines.length) {
        var line = lines[i], m = !code && TODO.exec(line);
        if (/^[ \t]*(```|~~~)/.test(line)) code = !code;
        if (!m) { out.push(line); i++; continue; }
        // a list: to-dos one after another at the same indent, each with the lines indented under it
        var open = [], done = [], j = i, ind = m[1];
        while (j < lines.length && (m = TODO.exec(lines[j])) && m[1] === ind) {
          var k = j + 1;
          while (k < lines.length && lines[k].trim() && indentOf(lines[k]) > ind.length) k++;
          var head = lines[j], kids = run(lines.slice(j + 1, k)), ticked = m[2] !== " ";
          if (how === "untick" && ticked) { head = head.replace(/\[[xX]\]/, "[ ]"); n++; ticked = false; }
          // a ticked item with something still to do under it stays (nothing unfinished is lost)
          if (how === "drop" && ticked && kids.some(function (l) { var k = TODO.exec(l); return k && k[2] === " "; })) ticked = false;
          (ticked ? done : open).push([head].concat(kids));
          j = k;
        }
        if (how === "drop") { n += done.length; done = []; }
        if (how === "sink" && done.length && open.length) {
          // only counted when something actually moves: a ticked item above an unticked one
          var order = []; for (var q = i; q < j; q++) { var mm = TODO.exec(lines[q]); if (mm && mm[1] === ind) order.push(mm[2] !== " "); }
          if (order.indexOf(true) >= 0 && order.lastIndexOf(false) > order.indexOf(true)) n += done.length;
        }
        open.concat(done).forEach(function (c) { out.push.apply(out, c); });
        i = j;
      }
      return out;
    }
    var text2 = run(String(text || "").split("\n")).join("\n");
    return { text: text2, changed: n };
  }

  // where the "/" menu fits: above the keyboard (and the bar on it), not under it
  var placeSlash = openSlash;
  openSlash = function (ta, at) {
    placeSlash(ta, at);
    if (!slash || !TOUCH) return;
    var p = caretXY(ta, at), h = slash.el.offsetHeight, v = view(), top = p.y + 4;
    if (top + h > v.bottom - 8) top = Math.max(v.top + 8, p.y - h - 24);
    slash.el.style.top = top + "px";
  };

  window.FTWriting = { toMarkdown: function (html) { return loadTurndown().then(function () { return toMarkdown(html); }); }, caretXY: caretXY,
                       find: function (ta, replacing) { if (ta) openFind(ta, replacing); }, todos: todos, keep: queueKeep,
                       highlight: function (ta, color) { if (ta) { ta.focus(); highlight(ta, color === undefined ? "toggle" : color); } } };

  d.addEventListener("paste", function (e) {
    if (box(e) !== "md" || e.defaultPrevented || !e.clipboardData) return;
    var ta = e.target, s = ta.selectionStart, end = ta.selectionEnd;
    var html = e.clipboardData.getData("text/html"), text = e.clipboardData.getData("text/plain");
    var chosen = ta.value.slice(s, end);
    if (chosen && chosen.indexOf("\n") < 0 && /^https?:\/\/\S+$/.test(text.trim())) {      // a link over chosen words
      e.preventDefault();
      put(ta, s, end, "[" + chosen + "](" + text.trim() + ")");
      return;
    }
    if (!html || !/<(h[1-6]|li|pre|strong|b|em|table|code|blockquote|span class="katex)[\s>"]/i.test(html) || looksLikeMarkdown(text)) return;
    e.preventDefault();
    loadTurndown().then(function () { return toMarkdown(html); }, function () { return text; }).then(function (md) {
      md = md || text;
      if (md.indexOf("\n") >= 0) {         // blocks (a list, a code box…) go on lines of their own
        var v = ta.value;
        if (v.slice(lineStart(v, s), s).trim()) md = "\n\n" + md;
        if (v.slice(end, lineEnd(v, end)).trim()) md += "\n\n";
      }
      put(ta, s, end, md);
    }, function () { put(ta, s, end, text); });
  });
})();
