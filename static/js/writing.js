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
    { id: "link", icon: "[[", text: "[[|]]", words: "link note wiki page", when: function (ta) { return ta.matches(".wn-body"); } },
    { id: "card", icon: "::", text: " :: |", words: "flashcard card question answer" },
    { id: "mark", icon: "==", text: "==|==", words: "highlight mark cloze blank hide" },
    { id: "date", icon: "📅", words: "date today now day", text: function () { var n = new Date(); return n.getFullYear() + "-" + pad(n.getMonth() + 1) + "-" + pad(n.getDate()) + "|"; } },
    { id: "time", icon: "🕑", words: "time now clock", text: function () { var n = new Date(); return pad(n.getHours()) + ":" + pad(n.getMinutes()) + "|"; } },
  ];
  var NAMES = { h1: "Heading 1", h2: "Heading 2", h3: "Heading 3", todo: "To-do", bullet: "Bulleted list", numbered: "Numbered list", quote: "Quote",
                callout: "Callout", code: "Code block", python: "Python code", js: "JavaScript code", sql: "SQL", bash: "Shell command", json: "JSON",
                mermaid: "Diagram (Mermaid)", table: "Table", details: "Collapsible section", divider: "Divider", math: "Formula",
                link: "Link to a note", card: "Flashcard (question :: answer)", mark: "Highlight (a blank in reviews)", date: "Today’s date", time: "Time now" };
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
  window.addEventListener("resize", closeSlash);
  d.addEventListener("scroll", function (e) { if (slash && e.target !== slash.el) closeSlash(); }, true);

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
  window.FTWriting = { toMarkdown: function (html) { return loadTurndown().then(function () { return toMarkdown(html); }); }, caretXY: caretXY };

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
