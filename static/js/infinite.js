/* Infinite scrolling for every list with page numbers
   (templates/partials/pagination.html): as the end of the list comes near,
   the next page is fetched and its rows are added below — the page's own view
   doesn't change. Without JavaScript the page numbers work as before; with
   it they become a "Show more" button (for keyboards and screen readers too)
   that also loads by itself on scrolling.

   The rows are found by shape: in the element just before the pager, the
   element with the most children of one kind (<li>s, <tr>s, cards…), unless a
   template marks it with data-infinite-items. The same is looked up in the
   next page, and its children are moved over. Alpine starts the new rows by
   itself; a search swapped in by htmx gets its own pager set up again. */
(function () {
  "use strict";
  var d = document;

  // The element before the pager — or, for a pager wrapped in a box of its own (to be swapped), before that box.
  function before(nav) {
    for (var at = nav; at && at !== d.body; at = at.parentElement) {
      for (var el = at.previousElementSibling; el; el = el.previousElementSibling) {
        if (!/^(SCRIPT|TEMPLATE|STYLE)$/.test(el.tagName)) return el;
      }
      if (at.parentElement && at.parentElement.children.length !== 1) break;      // only a box holding just the pager
    }
    return null;
  }

  function itemsIn(root) {
    if (!root) return null;
    if (root.hasAttribute("data-infinite-items")) return root;
    var marked = root.querySelector("[data-infinite-items]");
    if (marked) return marked;
    var best = null, most = 1;
    [root].concat(Array.prototype.slice.call(root.querySelectorAll("*"))).forEach(function (el) {
      if (/^(SELECT|SVG|svg|TEMPLATE|FORM)$/.test(el.tagName)) return;
      var counts = {};
      Array.prototype.forEach.call(el.children, function (c) {
        if (c.tagName === "TEMPLATE" || c.tagName === "SCRIPT") return;
        counts[c.tagName] = (counts[c.tagName] || 0) + 1;
      });
      for (var tag in counts) if (counts[tag] > most) { most = counts[tag]; best = el; }
    });
    return best;
  }

  function text(nav, key, fallback) { return nav.getAttribute("data-" + key) || fallback; }

  // A list that scrolls inside its own box (the notes list beside the editor) is watched within that box.
  function scroller(el) {
    for (var p = el; p && p !== d.body && p !== d.documentElement; p = p.parentElement) {
      var st = getComputedStyle(p);
      if (/(auto|scroll)/.test(st.overflowY) && p.scrollHeight > p.clientHeight + 1) return p;
    }
    return null;
  }

  function setup(nav) {
    if (nav._infinite) return;
    var next = nav.getAttribute("data-next"), list = itemsIn(before(nav));
    if (!next || !list) return;
    nav._infinite = true;
    var index = Array.prototype.indexOf.call(d.querySelectorAll("nav.pager"), nav);
    var button = d.createElement("button");
    button.type = "button";
    button.className = "btn btn-secondary pager-more";
    button.textContent = text(nav, "more", "Show more");
    nav.appendChild(button);
    nav.classList.add("is-infinite");
    var busy = false, watcher = null;

    function done() {
      if (watcher) watcher.disconnect();
      nav.classList.add("is-done");
      button.remove();
    }

    function load() {
      if (busy || !next) return;
      busy = true;
      nav.classList.add("is-loading");
      button.textContent = text(nav, "loading", "Loading…");
      fetch(next, { credentials: "same-origin", headers: { "X-Requested-With": "fetch", "X-FT-More": "1" } })
        .then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); })
        .then(function (html) {
          var doc = new DOMParser().parseFromString(html, "text/html");
          var navs = doc.querySelectorAll("nav.pager"), there = navs[index] || navs[0];
          var rows = itemsIn(there ? before(there) : null);
          if (!rows) { location.href = next; return; }
          var added = Array.prototype.slice.call(rows.children);
          added.forEach(function (row) { list.appendChild(d.adoptNode(row)); });
          next = there.getAttribute("data-next");
          var info = nav.querySelector(".pager-info"), newInfo = there.querySelector(".pager-info");
          if (info && newInfo) info.textContent = newInfo.textContent;
          d.dispatchEvent(new CustomEvent("ft:more", { detail: { list: list, rows: added } }));
          if (!next) done(); else requestAnimationFrame(watch);
        })
        .catch(function () { button.textContent = text(nav, "retry", "Couldn't load — try again"); })
        .then(function () {
          busy = false;
          nav.classList.remove("is-loading");
          if (next && button.isConnected && button.textContent === text(nav, "loading", "Loading…")) button.textContent = text(nav, "more", "Show more");
        });
    }

    button.addEventListener("click", load);
    // What's watched: the pager below the list, or (in a scrolling box) the list's last row. After each
    // page the watch starts again, and when the end is still in view (a short page) the next one comes.
    function near() {
      var box = scroller(list);
      if (box) {
        var last = list.lastElementChild;
        return !!last && last.getBoundingClientRect().top < box.getBoundingClientRect().bottom + 400;
      }
      return nav.getBoundingClientRect().top < window.innerHeight + 600;
    }
    function watch() {
      if (!next) return;
      if (watcher) watcher.disconnect();
      if ("IntersectionObserver" in window) {
        var box = scroller(list);
        watcher = new IntersectionObserver(function (entries) {
          if (entries.some(function (e) { return e.isIntersecting; })) load();
        }, { root: box, rootMargin: box ? "0px 0px 400px 0px" : "0px 0px 600px 0px" });
        watcher.observe(box && list.lastElementChild ? list.lastElementChild : nav);
      }
      if (near()) load();
    }
    watch();
  }

  function scan(root) { (root || d).querySelectorAll("nav.pager[data-next]").forEach(setup); }

  d.addEventListener("DOMContentLoaded", function () { scan(); });
  d.addEventListener("htmx:afterSwap", function (e) { scan(e.target); });
  window.FTInfinite = { scan: scan, itemsIn: itemsIn, before: before };
})();
