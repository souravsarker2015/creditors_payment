/* FinTrack — every ⋯ menu fits the screen (loaded by templates/base.html). */
/* A ⋯ menu always fits the screen. It used to open wherever its button sat: a long one (a note's 17 actions) ran off
   the bottom and behind the tab bar, and next to a panel's edge (a note in full screen) half of it was cut away.
   Now it slides back inside the panel that would cut it, opens upwards when there is more room above, and
   otherwise stops at the bottom of the screen and scrolls. */
(function () {
    var GAP = 8;
    function screenBox() {
        var vv = window.visualViewport, box = { left: 0, top: 0, right: window.innerWidth, bottom: vv ? vv.height + vv.offsetTop : window.innerHeight };
        var bar = document.querySelector(".app-tabbar");
        if (bar && bar.getClientRects().length && getComputedStyle(bar).display !== "none") {   // (a fixed bar has no offsetParent)
            var b = bar.getBoundingClientRect();
            if (b.top < box.bottom && b.height) box.bottom = Math.min(box.bottom, b.top);
            var fab = bar.querySelector(".app-tab-fab");                // the raised "+" stands above the bar
            if (fab && fab.getClientRects().length) box.bottom = Math.min(box.bottom, fab.getBoundingClientRect().top);
        }
        var top = document.querySelector(".topbar");                 // …and never under the sticky bar at the top
        if (top && top.getClientRects().length && /sticky|fixed/.test(getComputedStyle(top).position)) {
            var t = top.getBoundingClientRect();
            if (t.bottom > 0 && t.top <= 0) box.top = Math.max(box.top, t.bottom);
        }
        return box;
    }
    // the box a fixed element is placed in: the screen, unless an ancestor has a transform / filter / blur
    function fixedBlock(menu) {
        for (var a = menu.parentElement; a && a !== document.documentElement; a = a.parentElement) {
            var cs = getComputedStyle(a);
            if (cs.transform !== "none" || cs.filter !== "none" || (cs.backdropFilter || cs.webkitBackdropFilter || "none") !== "none" ||
                cs.perspective !== "none" || /paint|layout|strict|content/.test(cs.contain) || /transform|filter|perspective/.test(cs.willChange)) return a;
        }
        return null;
    }
    // a narrow strip that scrolls (a note's formatting toolbar): whatever opens from it was cut to the strip's height
    function trapped(menu, block) {
        for (var a = menu.parentElement; a && a !== block && a !== document.body; a = a.parentElement) {
            var cs = getComputedStyle(a);
            if (cs.overflowX === "visible" && cs.overflowY === "visible") continue;
            if (a.getBoundingClientRect().height < menu.offsetHeight + 24) return true;
        }
        return false;
    }
    function room(from) {
        var box = screenBox();
        for (var a = from; a && a !== document.body; a = a.parentElement) {
            var cs = getComputedStyle(a);
            if (cs.overflowX === "visible" && cs.overflowY === "visible") continue;
            var r = a.getBoundingClientRect();
            if (cs.overflowX !== "visible") { box.left = Math.max(box.left, r.left); box.right = Math.min(box.right, r.right); }
            if (cs.overflowY !== "visible" && r.height < window.innerHeight) { box.top = Math.max(box.top, r.top); box.bottom = Math.min(box.bottom, r.bottom); }
        }
        return box;
    }
    function reset(menu) {
        if (menu.dataset.fitUp) { menu.classList.remove("menu-up"); delete menu.dataset.fitUp; }
        delete menu.dataset.fitFixed;
        ["position", "top", "bottom", "left", "right", "maxHeight"].forEach(function (k) { menu.style[k] = ""; });
        menu.classList.remove("is-scrolling");
    }
    function fit(menu) {
        if (!menu.getClientRects().length || menu.closest("[data-no-fit]")) return;
        reset(menu);
        var anchor = menu.parentElement.getBoundingClientRect(), block = fixedBlock(menu), r, shift, space;
        if (trapped(menu, block)) {
            // lifted out of the strip: placed on its own, right under its button (and kept there while it is open)
            var o = block ? block.getBoundingClientRect() : { left: 0, top: 0 }, box = room(block);
            menu.dataset.fitFixed = "1";
            menu.style.position = "fixed"; menu.style.right = "auto"; menu.style.bottom = "auto";
            menu.style.top = (anchor.bottom + 4 - o.top) + "px";
            menu.style.left = (anchor.right - menu.offsetWidth - o.left) + "px";
            r = menu.getBoundingClientRect();
            shift = r.left < box.left + GAP ? box.left + GAP - r.left : (r.right > box.right - GAP ? box.right - GAP - r.right : 0);
            if (shift) menu.style.left = (parseFloat(menu.style.left) + shift) + "px";
            var below = box.bottom - GAP - anchor.bottom, above = anchor.top - GAP - box.top;
            if (r.height > below && above > below) {
                space = Math.max(above, 160);
                menu.style.top = (anchor.top - 4 - Math.min(r.height, space) - o.top) + "px";
            } else space = Math.max(below, 160);
            if (r.height > space) { menu.style.maxHeight = space + "px"; menu.classList.add("is-scrolling"); }
            return;
        }
        var box2 = room(menu.parentElement);
        r = menu.getBoundingClientRect();
        // sideways: back inside the panel / screen
        shift = r.left < box2.left + GAP ? box2.left + GAP - r.left : (r.right > box2.right - GAP ? box2.right - GAP - r.right : 0);
        if (shift) { menu.style.right = "auto"; menu.style.left = (r.left - anchor.left + shift) + "px"; }
        // up and down
        var up = menu.classList.contains("menu-up");
        var below2 = box2.bottom - GAP - anchor.bottom, above2 = anchor.top - GAP - box2.top;
        if (!up && r.height > below2 && above2 > below2) { menu.classList.add("menu-up"); menu.dataset.fitUp = "1"; up = true; }
        space = Math.max(up ? above2 : below2, 160);
        if (r.height > space) { menu.style.maxHeight = space + "px"; menu.classList.add("is-scrolling"); }
    }
    // a menu that fills in after it opens (a note's list of diagrams): fitted again once its content has grown
    var grown = window.ResizeObserver && new ResizeObserver(function (entries) {
        entries.forEach(function (en) {
            var m = en.target;
            if (m.getClientRects().length && Math.abs(m.scrollHeight - (+m.dataset.fitH || 0)) > 4) { fit(m); m.dataset.fitH = m.scrollHeight; }
        });
    });
    function fitAndWatch(m) {
        fit(m);
        m.dataset.fitH = m.scrollHeight;
        if (grown && !m.dataset.fitWatched) { m.dataset.fitWatched = "1"; grown.observe(m); }
    }
    function fitOpen(onlyLifted) {
        document.querySelectorAll(".menu").forEach(function (m) {
            if (m.getClientRects().length && (!onlyLifted || m.dataset.fitFixed)) fitAndWatch(m);
        });
    }
    // an open menu is above floating things (the floating clock covered a note's Archive / Delete): the layers that
    // hold it are lifted while it is open, and dropped back once it closes
    function raiseOpen() {
        document.querySelectorAll(".menu-raised").forEach(function (el) { el.classList.remove("menu-raised"); });
        document.querySelectorAll(".menu").forEach(function (m) {
            if (!m.getClientRects().length) return;
            for (var a = m.parentElement; a && a !== document.body; a = a.parentElement) {
                var cs = getComputedStyle(a);
                if (cs.position !== "static" && cs.zIndex !== "auto" && +cs.zIndex < 56) a.classList.add("menu-raised");   // (never lowers a window that is higher)
            }
        });
    }
    // a menu opens on a click (or Enter / Space, which click too): fit it once it is drawn
    document.addEventListener("click", function () { requestAnimationFrame(function () { requestAnimationFrame(function () { fitOpen(); raiseOpen(); }); }); });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") requestAnimationFrame(function () { requestAnimationFrame(raiseOpen); }); });
    window.addEventListener("resize", function () { requestAnimationFrame(function () { fitOpen(); }); });
    if (window.visualViewport) visualViewport.addEventListener("resize", function () { requestAnimationFrame(function () { fitOpen(); }); });
    var moving = false;
    window.addEventListener("scroll", function (e) {       // a lifted menu stays with its button while the page (or the strip) scrolls
        if (moving || (e.target.closest && e.target.closest(".menu"))) return;   // (not while scrolling inside the menu itself)
        moving = true;
        requestAnimationFrame(function () { moving = false; fitOpen(true); });   // only lifted ones: re-fitting the others made the page creep upwards
    }, { passive: true, capture: true });
    window.FT = window.FT || {};
    FT.fitMenus = fitOpen;
})();
