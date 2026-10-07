/* Phone-friendly pickers.
 *
 * On a phone or tablet every dropdown, multi-select, date and date range opens
 * as a bottom sheet: big rows, a search box for long lists, a tick on what's
 * chosen, quick dates ("Today", "Yesterday") and ranges ("This month"…).
 * On a computer single dropdowns stay the browser's own (fast, keyboard
 * friendly); multi-selects open as a panel under the box, and the calendars
 * keep their pop-up with the same shortcuts.
 *
 * The real <select>/<input> stays in the form and keeps its value, so forms,
 * Alpine, htmx and onchange="…" work exactly as before. Opt out with
 * data-native on the element.
 */
(function () {
    "use strict";
    var d = document, root = d.documentElement;
    var touchMQ = matchMedia("(max-width: 1023.98px), (pointer: coarse)");
    var T = window.FT_PICK_TEXT || {};
    function t(key, fallback) { return T[key] || fallback; }
    function isTouch() { return touchMQ.matches; }
    function sync() { root.classList.toggle("ft-touch", isTouch()); }
    sync();
    if (touchMQ.addEventListener) touchMQ.addEventListener("change", function () { sync(); refreshPickers(); });

    var CHEVRON = '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M6 8l4 4 4-4" stroke-linecap="round" stroke-linejoin="round"/></svg>';
    var TICK = '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true"><path d="M4.5 10.5l3.5 3.5 7.5-8" stroke-linecap="round" stroke-linejoin="round"/></svg>';
    var CLOSE = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M6 18L18 6M6 6l12 12" stroke-linecap="round" stroke-linejoin="round"/></svg>';
    var SEARCH = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M21 21l-5.2-5.2M10.5 18a7.5 7.5 0 100-15 7.5 7.5 0 000 15z" stroke-linecap="round"/></svg>';

    function el(tag, cls, html) {
        var e = d.createElement(tag);
        if (cls) e.className = cls;
        if (html != null) e.innerHTML = html;
        return e;
    }
    function fire(target, type) { target.dispatchEvent(new Event(type, { bubbles: true })); }
    function labelFor(field) {
        var lab = field.id && d.querySelector('label[for="' + (window.CSS && CSS.escape ? CSS.escape(field.id) : field.id) + '"]');
        var text = lab ? lab.cloneNode(true) : null;
        if (text) text.querySelectorAll(".req, .opt, .info-tip, button, svg").forEach(function (n) { n.remove(); });
        return (text && text.textContent.trim()) || field.getAttribute("aria-label") || field.getAttribute("placeholder") || "";
    }
    function norm(s) { return (s || "").toLocaleLowerCase().normalize("NFKD").replace(/[̀-ͯ]/g, "").trim(); }

    /* ── The sheet (phones) or panel (computers) ─────────────────────────── */
    var openSheet = null;

    function closeSheet(keepFocus) {
        var s = openSheet;
        if (!s) return;
        openSheet = null;
        d.removeEventListener("keydown", s.onKey, true);
        d.removeEventListener("mousedown", s.onOutside, true);
        window.removeEventListener("app-sheet-close", s.onSwipe);
        window.removeEventListener("resize", s.onResize);
        if (s.mode === "sheet") {
            s.panel.classList.add("is-leaving");
            s.root.classList.add("is-leaving");
            setTimeout(function () { s.root.remove(); }, 200);
            d.body.style.overflow = s.prevOverflow;
        } else {
            s.root.remove();
        }
        if (s.returnTo) s.returnTo.setAttribute("aria-expanded", "false");
        if (s.onClose) s.onClose();
        if (keepFocus !== false && s.returnTo && s.returnTo.focus) s.returnTo.focus({ preventScroll: true });
    }

    /* opts: title, anchor (element the panel sits under on a computer),
       returnTo, build(body, foot, close), onClose, wide */
    function showSheet(opts) {
        closeSheet(false);
        var mode = isTouch() ? "sheet" : "panel";
        var s = { mode: mode, onClose: opts.onClose, returnTo: opts.returnTo };
        if (opts.returnTo) opts.returnTo.setAttribute("aria-expanded", "true");
        var titleId = "ftp-title-" + Math.random().toString(36).slice(2, 8);
        if (mode === "sheet") {
            s.root = el("div", "ftp-root");
            var backdrop = el("div", "ftp-backdrop");
            backdrop.addEventListener("click", function () { closeSheet(); });
            s.panel = el("section", "ftp-sheet app-sheet");
            s.panel.setAttribute("role", "dialog");
            s.panel.setAttribute("aria-modal", "true");
            s.panel.setAttribute("aria-labelledby", titleId);
            s.panel.appendChild(el("div", "app-sheet-grab", null)).setAttribute("data-sheet-grab", "");
            var head = el("header", "ftp-head app-sheet-head");
            var h = el("h2", "app-sheet-title");
            h.id = titleId; h.textContent = opts.title || "";
            var x = el("button", "icon-btn", CLOSE);
            x.type = "button"; x.setAttribute("aria-label", t("close", "Close")); x.setAttribute("data-no-tip", "");
            x.addEventListener("click", function () { closeSheet(); });
            head.appendChild(h); head.appendChild(x);
            s.panel.appendChild(head);
            s.root.appendChild(backdrop); s.root.appendChild(s.panel);
            s.prevOverflow = d.body.style.overflow;
            d.body.style.overflow = "hidden";
            s.onSwipe = function () { closeSheet(); };
            window.addEventListener("app-sheet-close", s.onSwipe);
        } else {
            s.root = s.panel = el("section", "ftp-panel" + (opts.wide ? " is-wide" : ""));
            s.panel.setAttribute("role", "dialog");
            s.panel.setAttribute("aria-label", opts.title || "");
            s.onOutside = function (e) {
                if (!s.panel.contains(e.target) && !(opts.anchor && opts.anchor.contains(e.target))) closeSheet(false);
            };
            d.addEventListener("mousedown", s.onOutside, true);
            s.onResize = function () { place(s.panel, opts.anchor); };
            window.addEventListener("resize", s.onResize);
        }
        var body = el("div", "ftp-body"), foot = el("footer", "ftp-foot");
        s.panel.appendChild(body); s.panel.appendChild(foot);
        opts.build(body, foot, closeSheet);
        if (!foot.children.length) foot.remove();
        // Inside a pop-up that keeps focus to itself, open within it so the
        // search box and buttons can take focus.
        var host = (opts.anchor && opts.anchor.closest(".modal, .app-sheet, .search-panel")) || d.body;
        host.appendChild(s.root);
        if (mode === "panel") place(s.panel, opts.anchor);
        s.onKey = function (e) {
            if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); closeSheet(); }
            else if (e.key === "Tab" && mode === "sheet") trapTab(e, s.panel);
        };
        d.addEventListener("keydown", s.onKey, true);
        openSheet = s;
        return s;
    }

    function place(panel, anchor) {
        if (!anchor) return;
        var r = anchor.getBoundingClientRect(), vh = window.innerHeight, vw = window.innerWidth;
        panel.style.minWidth = Math.max(r.width, 256) + "px";
        var w = panel.offsetWidth, h = panel.offsetHeight;
        var below = vh - r.bottom - 8, above = r.top - 8;
        var top = (below >= Math.min(h, 320) || below >= above) ? r.bottom + 6 : Math.max(8, r.top - 6 - h);
        panel.style.top = top + "px";
        panel.style.left = Math.max(8, Math.min(r.left, vw - w - 8)) + "px";
        panel.style.maxHeight = Math.max(200, (top > r.top ? vh - top : r.top - 6) - 8) + "px";
    }

    function trapTab(e, box) {
        var f = Array.prototype.filter.call(box.querySelectorAll("button, input, [tabindex]:not([tabindex='-1'])"), function (n) { return !n.disabled && n.offsetParent !== null; });
        if (!f.length) return;
        var first = f[0], last = f[f.length - 1];
        if (e.shiftKey && d.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && d.activeElement === last) { e.preventDefault(); first.focus(); }
    }

    /* A list of choices with an optional search box: used by both selects. */
    function choiceList(body, select, multi, onPick) {
        var items = [], groups = [];
        var count = 0;
        Array.prototype.forEach.call(select.options, function (o) { if (!o.hidden) count++; });
        var search = null;
        if (count > 7) {
            var wrap = el("label", "ftp-search", SEARCH);
            search = el("input");
            search.type = "search"; search.placeholder = t("search", "Search…"); search.setAttribute("autocomplete", "off");
            search.setAttribute("aria-label", t("search", "Search…"));
            wrap.appendChild(search);
            body.appendChild(wrap);
        }
        var list = el("div", "ftp-list");
        list.setAttribute("role", "listbox");
        if (multi) list.setAttribute("aria-multiselectable", "true");
        body.appendChild(list);
        var empty = el("p", "ftp-empty");
        empty.textContent = t("noMatch", "Nothing matches.");
        empty.hidden = true;
        body.appendChild(empty);

        function addOption(o, parent) {
            if (o.hidden) return;
            var b = el("button", "ftp-opt");
            b.type = "button";
            b.setAttribute("role", "option");
            var text = o.text.trim();
            var blank = !o.value && (/^-+$/.test(text) || !text);
            b.innerHTML = '<span class="ftp-opt-text"></span><span class="ftp-tick">' + TICK + "</span>";
            b.firstChild.textContent = blank ? t("none", "None") : text;
            if (!o.value) b.classList.add("is-blank");
            if (o.disabled) b.disabled = true;
            b._opt = o;
            b._key = norm(text);
            b.addEventListener("click", function () { onPick(o, b); });
            parent.appendChild(b);
            items.push(b);
        }
        Array.prototype.forEach.call(select.children, function (c) {
            if (c.tagName === "OPTGROUP") {
                var g = el("div", "ftp-group");
                g.setAttribute("role", "group");
                var gh = el("p", "ftp-group-label");
                gh.textContent = c.label;
                g.setAttribute("aria-label", c.label);
                g.appendChild(gh);
                Array.prototype.forEach.call(c.children, function (o) { addOption(o, g); });
                list.appendChild(g);
                groups.push(g);
            } else if (c.tagName === "OPTION") {
                addOption(c, list);
            }
        });
        function paint() {
            items.forEach(function (b) {
                var on = b._opt.selected && (multi || b._opt.value || select.value === "");
                b.classList.toggle("is-on", on);
                b.setAttribute("aria-selected", on ? "true" : "false");
            });
        }
        paint();
        if (search) {
            search.addEventListener("input", function () {
                var q = norm(search.value), shown = 0;
                items.forEach(function (b) {
                    var hit = !q || b._key.indexOf(q) !== -1;
                    b.hidden = !hit || (q && b.classList.contains("is-blank"));
                    if (!b.hidden) shown++;
                });
                groups.forEach(function (g) { g.hidden = !g.querySelector(".ftp-opt:not([hidden])"); });
                empty.hidden = shown > 0;
            });
            search.addEventListener("keydown", function (e) {
                if (e.key === "Enter") {
                    e.preventDefault();
                    var first = items.filter(function (b) { return !b.hidden && !b.disabled; })[0];
                    if (first) first.click();
                } else if (e.key === "ArrowDown") {
                    e.preventDefault();
                    var f = items.filter(function (b) { return !b.hidden; })[0];
                    if (f) f.focus();
                }
            });
        }
        list.addEventListener("keydown", function (e) {
            if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
            e.preventDefault();
            var vis = items.filter(function (b) { return !b.hidden && !b.disabled; });
            var i = vis.indexOf(d.activeElement);
            var next = vis[e.key === "ArrowDown" ? Math.min(vis.length - 1, i + 1) : Math.max(0, i - 1)];
            if (next) next.focus();
            else if (search && e.key === "ArrowUp") search.focus();
        });
        return { paint: paint, search: search, items: items };
    }

    /* ── Single dropdown ─────────────────────────────────────────────────── */
    function enhanceSelect(select) {
        if (select._ftp || select.multiple || select.hasAttribute("data-native") || select.closest("template, [data-native], .flatpickr-calendar, .ftp-root, .ftp-panel")) return;
        if (select.size > 1) return;
        select._ftp = true;
        var trigger = el("button", "", '<span class="ftp-trigger-text"></span>' + CHEVRON);
        trigger.type = "button";
        trigger.setAttribute("aria-haspopup", "listbox");
        trigger.setAttribute("data-ftp-for", select.id || "");
        var text = trigger.firstChild;
        select.classList.add("ftp-native");
        select.insertAdjacentElement("afterend", trigger);
        select._ftpTrigger = trigger;

        function refresh() {
            var o = select.options[select.selectedIndex];
            var label = o ? o.text.trim() : "";
            var blank = !o || !o.value;
            text.textContent = blank && /^-+$/.test(label) ? t("choose", "Choose…") : label;
            trigger.className = (select.className.replace(/\bftp-native\b/, "") + " ftp-trigger").trim();
            trigger.classList.toggle("is-placeholder", blank);
            trigger.disabled = select.disabled;
            trigger.hidden = select.hidden || select.style.display === "none";
            var lab = labelFor(select);
            trigger.setAttribute("aria-label", lab ? lab + ": " + text.textContent : text.textContent);
        }
        select._ftpRefresh = refresh;
        refresh();
        watchValue(select, refresh);

        function open() {
            if (select.disabled) return;
            refresh();
            showSheet({
                title: labelFor(select) || t("choose", "Choose…"),
                anchor: trigger, returnTo: trigger,
                build: function (body, foot, close) {
                    var list = choiceList(body, select, false, function (o) {
                        if (select.value !== o.value || !o.selected) {
                            select.value = o.value;
                            fire(select, "input");
                            fire(select, "change");
                        }
                        refresh();
                        close();
                    });
                    setTimeout(function () {
                        var on = list.items.filter(function (b) { return b.classList.contains("is-on"); })[0];
                        if (on) on.scrollIntoView({ block: "center" });
                        if (list.search && !isTouch()) list.search.focus();
                        else if (on) on.focus({ preventScroll: true });
                    }, 30);
                },
            });
        }
        trigger.addEventListener("click", open);
        trigger.addEventListener("keydown", function (e) {
            if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); open(); }
        });
    }

    /* Keep the box in step with the real field, however its value changes:
       typed by a person, set by Alpine (x-model), by another script, or a reset. */
    function watchValue(select, refresh) {
        ["value", "selectedIndex"].forEach(function (k) {
            var desc = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, k);
            if (!desc) return;
            Object.defineProperty(select, k, {
                configurable: true,
                get: function () { return desc.get.call(this); },
                set: function (v) { desc.set.call(this, v); refresh(); },
            });
        });
        select.addEventListener("change", refresh);
        select.addEventListener("input", refresh);
        if (select.form) select.form.addEventListener("reset", function () { setTimeout(refresh, 0); });
        new MutationObserver(function () { refresh(); }).observe(select, { childList: true, subtree: true, attributes: true, attributeFilter: ["disabled", "style", "class", "hidden", "selected"] });
    }

    /* ── Multi-select ────────────────────────────────────────────────────── */
    function enhanceMulti(select, placeholder) {
        if (!select || select.hasAttribute("data-native")) return;
        if (placeholder) select.setAttribute("data-placeholder", placeholder);
        if (select._ftp) { if (select._ftpRefresh) select._ftpRefresh(); return; }
        select._ftp = true;
        var trigger = el("button", "", '<span class="ftp-chips"></span>' + CHEVRON);
        trigger.type = "button";
        trigger.setAttribute("aria-haspopup", "listbox");
        var chips = trigger.firstChild;
        select.classList.add("ftp-native", "is-multi");
        select.insertAdjacentElement("afterend", trigger);
        select._ftpTrigger = trigger;

        function refresh() {
            var picked = Array.prototype.filter.call(select.options, function (o) { return o.selected && o.value; });
            chips.innerHTML = "";
            if (!picked.length) {
                var ph = el("span", "ftp-ph");
                ph.textContent = select.getAttribute("data-placeholder") || t("choose", "Choose…");
                chips.appendChild(ph);
            } else {
                picked.slice(0, 2).forEach(function (o) {
                    var c = el("span", "ftp-chip");
                    c.textContent = o.text.trim();
                    chips.appendChild(c);
                });
                if (picked.length > 2) {
                    var more = el("span", "ftp-chip is-more");
                    more.textContent = "+" + (picked.length - 2);
                    chips.appendChild(more);
                }
            }
            trigger.className = (select.className.replace(/\bftp-native\b|\bis-multi\b/g, "") + " ftp-trigger ftp-multi").trim();
            trigger.disabled = select.disabled;
            var lab = labelFor(select);
            trigger.setAttribute("aria-label", (lab ? lab + ": " : "") + (picked.length ? picked.map(function (o) { return o.text.trim(); }).join(", ") : t("noneChosen", "none chosen")));
        }
        select._ftpRefresh = refresh;
        refresh();
        watchValue(select, refresh);

        trigger.addEventListener("click", function () {
            var before = Array.prototype.map.call(select.options, function (o) { return o.selected; }).join();
            showSheet({
                title: labelFor(select) || select.getAttribute("data-placeholder") || t("choose", "Choose…"),
                anchor: trigger, returnTo: trigger,
                onClose: function () {
                    refresh();
                    var after = Array.prototype.map.call(select.options, function (o) { return o.selected; }).join();
                    if (after !== before) { fire(select, "input"); fire(select, "change"); }
                },
                build: function (body, foot, close) {
                    var list = choiceList(body, select, true, function (o) {
                        o.selected = !o.selected;
                        list.paint(); counter();
                    });
                    var clear = el("button", "btn btn-ghost");
                    clear.type = "button"; clear.textContent = t("clear", "Clear");
                    clear.addEventListener("click", function () {
                        Array.prototype.forEach.call(select.options, function (o) { o.selected = false; });
                        list.paint(); counter();
                    });
                    var done = el("button", "btn btn-primary");
                    done.type = "button";
                    done.addEventListener("click", function () { close(); });
                    function counter() {
                        var n = Array.prototype.filter.call(select.options, function (o) { return o.selected && o.value; }).length;
                        done.textContent = n ? t("doneN", "Done ({n})").replace("{n}", n) : t("done", "Done");
                        clear.disabled = !n;
                    }
                    counter();
                    foot.appendChild(clear); foot.appendChild(done);
                    if (list.search && !isTouch()) setTimeout(function () { list.search.focus(); }, 30);
                },
            });
        });
    }

    /* ── Dates ───────────────────────────────────────────────────────────── */
    var LOCALE = root.getAttribute("lang") === "bn" && window.flatpickr && flatpickr.l10ns && flatpickr.l10ns.bn ? "bn" : "default";
    var pickers = [];

    function ymd(dt) { return window.flatpickr ? flatpickr.formatDate(dt, "Y-m-d") : ""; }
    function addDays(dt, n) { var x = new Date(dt); x.setDate(x.getDate() + n); return x; }
    function today() { var n = new Date(); return new Date(n.getFullYear(), n.getMonth(), n.getDate()); }
    function inLimits(fp, dt) {
        var mn = fp.config.minDate, mx = fp.config.maxDate;
        return !(mn && dt < new Date(mn.getFullYear(), mn.getMonth(), mn.getDate())) && !(mx && dt > mx);
    }
    function chipRow(chips) {
        var row = el("div", "ftp-chiprow");
        chips.forEach(function (c) {
            var b = el("button", "ftp-quick");
            b.type = "button"; b.textContent = c.label;
            if (c.off) b.disabled = true;
            b.addEventListener("click", c.go);
            row.appendChild(b);
        });
        return row;
    }
    function nice(dt) { return dt ? flatpickr.formatDate(dt, "j M Y", flatpickr.l10ns[LOCALE] || undefined) : ""; }

    function datePicker(input) {
        if (!window.flatpickr || input._flatpickr || input.hasAttribute("data-native")) return input._flatpickr;
        if (input.type === "date") input.type = "text";
        var fp = flatpickr(input, {
            dateFormat: "Y-m-d", altInput: true, altFormat: "j M Y", allowInput: false,
            altInputClass: input.className.replace("datepicker", "").trim() || "form-input",
            disableMobile: true, monthSelectorType: "static", locale: LOCALE,
            minDate: input.getAttribute("min") || null, maxDate: input.getAttribute("max") || null,
            clickOpens: !isTouch(),
            onChange: function () { fire(input, "input"); },
            onReady: function (sel, str, inst) { addToday(inst); },
        });
        if (!fp || !fp.altInput) return fp;
        labelAlt(input, fp.altInput);
        fp.altInput.setAttribute("inputmode", "none");
        fp.altInput.addEventListener("click", function (e) {
            if (!isTouch()) return;
            e.preventDefault();
            dateSheet(input, fp);
        });
        fp.altInput.addEventListener("keydown", function (e) {
            if (isTouch() && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); dateSheet(input, fp); }
        });
        pickers.push(fp);
        return fp;
    }

    /* Computer pop-up calendar: a "Today" button under the month. */
    function addToday(fp) {
        if (!fp.calendarContainer || fp.config.mode === "range" || fp.calendarContainer.querySelector(".ftp-fp-today")) return;
        var b = el("button", "ftp-fp-today");
        b.type = "button"; b.textContent = t("today", "Today");
        b.addEventListener("click", function () { fp.setDate(today(), true); fp.close(); });
        fp.calendarContainer.appendChild(b);
    }

    /* The calendar puts focus on its first day; keep it on the chosen day (or today). */
    function focusDay(box) {
        setTimeout(function () {
            var day = box.querySelector(".flatpickr-day.selected, .flatpickr-day.startRange") || box.querySelector(".flatpickr-day.today");
            if (day) day.focus({ preventScroll: true });
            else if (box.contains(d.activeElement)) d.activeElement.blur();
        }, 40);
    }

    function dateSheet(input, fp) {
        var required = input.hasAttribute("required");
        showSheet({
            title: labelFor(input) || labelFor(fp.altInput) || t("pickDate", "Pick a date"),
            anchor: fp.altInput, returnTo: fp.altInput,
            build: function (body, foot, close) {
                var now = today();
                function pick(dt) { fp.setDate(dt, true); close(); }
                body.appendChild(chipRow([
                    { label: t("today", "Today"), go: function () { pick(now); }, off: !inLimits(fp, now) },
                    { label: t("yesterday", "Yesterday"), go: function () { pick(addDays(now, -1)); }, off: !inLimits(fp, addDays(now, -1)) },
                    { label: t("tomorrow", "Tomorrow"), go: function () { pick(addDays(now, 1)); }, off: !inLimits(fp, addDays(now, 1)) },
                ]));
                var box = el("div", "ftp-cal", "<input type='hidden'>");
                body.appendChild(box);
                flatpickr(box.firstChild, {
                    inline: true, disableMobile: true, locale: LOCALE, monthSelectorType: "static",
                    defaultDate: fp.selectedDates[0] || null,
                    minDate: fp.config.minDate, maxDate: fp.config.maxDate,
                    onChange: function (sel) { if (sel[0]) pick(sel[0]); },
                });
                focusDay(box);
                if (!required && fp.selectedDates.length) {
                    var clear = el("button", "btn btn-ghost btn-block");
                    clear.type = "button"; clear.textContent = t("clearDate", "No date");
                    clear.addEventListener("click", function () { fp.clear(); fire(input, "change"); close(); });
                    foot.appendChild(clear);
                }
            },
        });
    }

    /* Date range: quick ranges, then the calendar for anything else. */
    function rangePresets() {
        var n = today(), y = n.getFullYear(), m = n.getMonth();
        return [
            { label: t("last7", "Last 7 days"), range: [addDays(n, -6), n] },
            { label: t("last30", "Last 30 days"), range: [addDays(n, -29), n] },
            { label: t("thisMonth", "This month"), range: [new Date(y, m, 1), n] },
            { label: t("lastMonth", "Last month"), range: [new Date(y, m - 1, 1), new Date(y, m, 0)] },
            { label: t("last3Months", "Last 3 months"), range: [new Date(y, m - 2, 1), n] },
            { label: t("thisYear", "This year"), range: [new Date(y, 0, 1), n] },
            { label: t("lastYear", "Last year"), range: [new Date(y - 1, 0, 1), new Date(y - 1, 11, 31)] },
        ];
    }

    function rangePicker(inputId, fromId, toId) {
        var input = d.getElementById(inputId), from = d.getElementById(fromId), to = d.getElementById(toId);
        if (!input || !from || !to || !window.flatpickr) return;
        var initial = [from.value, to.value].filter(Boolean);
        var fp = flatpickr(input, {
            mode: "range", dateFormat: "Y-m-d", altInput: true, altFormat: "j M Y", disableMobile: true, locale: LOCALE, monthSelectorType: "static",
            altInputClass: input.className || "form-input",
            defaultDate: initial.length ? initial : null,
            clickOpens: !isTouch(),
            onReady: function (dates, str, inst) {
                labelAlt(input, inst.altInput);
                var row = chipRow(rangePresets().map(function (p) {
                    return { label: p.label, go: function () { inst.setDate(p.range, true); inst.close(); } };
                }));
                row.classList.add("ftp-fp-presets");
                inst.calendarContainer.appendChild(row);
            },
            onChange: function (dates) {
                from.value = dates[0] ? ymd(dates[0]) : "";
                to.value = dates[1] ? ymd(dates[1]) : (dates[0] ? from.value : "");
            },
        });
        if (!fp || !fp.altInput) return;
        fp.altInput.setAttribute("inputmode", "none");
        fp.altInput.addEventListener("click", function (e) {
            if (!isTouch()) return;
            e.preventDefault();
            rangeSheet(input, fp);
        });
        pickers.push(fp);
    }

    function rangeSheet(input, fp) {
        showSheet({
            title: labelFor(input) || t("pickRange", "Pick dates"),
            anchor: fp.altInput, returnTo: fp.altInput,
            build: function (body, foot, close) {
                var chosen = fp.selectedDates.slice();
                var summary = el("p", "ftp-range-sum");
                function show() {
                    summary.textContent = chosen.length
                        ? nice(chosen[0]) + " – " + (chosen[1] ? nice(chosen[1]) : t("pickEnd", "pick the last day"))
                        : t("pickStart", "Tap the first day, then the last day.");
                    apply.disabled = !chosen.length;
                }
                var presets = rangePresets();
                var row = chipRow(presets.map(function (p) {
                    return { label: p.label, go: function () { fp.setDate(p.range, true); close(); } };
                }));
                body.appendChild(row);
                body.appendChild(summary);
                var box = el("div", "ftp-cal", "<input type='hidden'>");
                body.appendChild(box);
                var cal = flatpickr(box.firstChild, {
                    inline: true, disableMobile: true, mode: "range", locale: LOCALE, monthSelectorType: "static",
                    defaultDate: chosen.length ? chosen : null,
                    onChange: function (sel) { chosen = sel.slice(); show(); },
                });
                var clear = el("button", "btn btn-ghost");
                clear.type = "button"; clear.textContent = t("clear", "Clear");
                clear.addEventListener("click", function () { fp.clear(); from.value = ""; to.value = ""; close(); });
                var apply = el("button", "btn btn-primary");
                apply.type = "button"; apply.textContent = t("apply", "Apply");
                apply.addEventListener("click", function () {
                    if (!chosen.length) return;
                    fp.setDate(chosen.length === 1 ? [chosen[0], chosen[0]] : chosen, true);
                    close();
                });
                foot.appendChild(clear); foot.appendChild(apply);
                show();
                if (cal && cal.selectedDates[0]) cal.jumpToDate(cal.selectedDates[0]);
                focusDay(box);
            },
        });
    }

    /* flatpickr hides the real input and shows a copy; the copy has to carry
       the same label, or a screen reader announces an unnamed box. */
    function labelAlt(el0, alt) {
        if (!alt) return;
        var label = el0.id && d.querySelector('label[for="' + (window.CSS && CSS.escape ? CSS.escape(el0.id) : el0.id) + '"]');
        if (label) {
            if (!label.id) label.id = (el0.id || "fp") + "-label";
            alt.setAttribute("aria-labelledby", label.id);
        } else if (el0.getAttribute("aria-label")) {
            alt.setAttribute("aria-label", el0.getAttribute("aria-label"));
        }
        if (el0.hasAttribute("required")) alt.setAttribute("aria-required", "true");
    }

    function refreshPickers() {
        pickers.forEach(function (fp) { fp.set("clickOpens", !isTouch()); });
        if (openSheet) closeSheet(false);
    }

    /* A label tapped for a dropdown opens it, like the real one. */
    d.addEventListener("click", function (e) {
        var lab = e.target.closest && e.target.closest("label[for]");
        if (!lab || !isTouch()) return;
        var field = d.getElementById(lab.getAttribute("for"));
        if (field && field._ftpTrigger && !field._ftpTrigger.hidden) { e.preventDefault(); field._ftpTrigger.click(); }
    });

    /* ── Wire up the page, and anything added later (htmx, new rows…) ───── */
    function scan(scope) {
        if (!scope.querySelectorAll) return;
        scope.querySelectorAll("select").forEach(function (s) {
            if (s.multiple) { if (s.hasAttribute("data-multi") || s.classList.contains("form-input") || s.classList.contains("form-control")) enhanceMulti(s, s.getAttribute("data-placeholder")); }
            else enhanceSelect(s);
        });
        // A date box another field writes into (x-model) keeps the phone's own picker.
        scope.querySelectorAll("input.datepicker, input[type=date].form-input:not([x-model])").forEach(function (i) {
            if (!i.closest("template")) datePicker(i);
        });
    }

    window.FT = Object.assign(window.FT || {}, {
        datePicker: datePicker,
        rangePicker: rangePicker,
        labelAlt: labelAlt,
        multiSelect: function (id, placeholder) { enhanceMulti(d.getElementById(id), placeholder); },
        enhancePickers: scan,
        closePicker: closeSheet,
        sheet: showSheet,
    });

    function start() {
        scan(d);
        new MutationObserver(function (records) {
            records.forEach(function (r) {
                r.addedNodes.forEach(function (n) {
                    if (n.nodeType !== 1 || n.classList.contains("ftp-root") || n.classList.contains("ftp-panel") || n.closest(".ftp-root, .ftp-panel, .flatpickr-calendar")) return;
                    if (n.tagName === "SELECT" || n.tagName === "INPUT") scan(n.parentNode || d);
                    else scan(n);
                });
            });
        }).observe(d.body, { childList: true, subtree: true });
    }
    if (d.readyState === "loading") d.addEventListener("DOMContentLoaded", start);
    else start();
})();
