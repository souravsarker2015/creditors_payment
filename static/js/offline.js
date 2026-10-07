/* Works without internet: the page side (server side: apps/core/offline.py,
 * service worker: apps/core/pwa.py).
 *
 * - Every form you save carries a one-off key, so an entry is never saved
 *   twice even if it's sent again.
 * - When a save can't reach the server, the service worker keeps it in the
 *   phone's outbox and brings you back to the form ("Saved on this phone").
 * - This script sends the outbox as soon as there's signal, shows what's
 *   waiting, and lets you fix or remove an entry the server didn't accept.
 * - A page shown from the phone's copy says so, and its date boxes move to
 *   today.
 * - The everyday forms are kept ready on the phone (a few times a day, on
 *   signal), so they open at the pond.
 */
(function () {
    "use strict";
    var d = document, root = d.documentElement;
    var ME = root.getAttribute("data-user") || "";
    var T = window.FT_OFFLINE_TEXT || {};
    function t(k, f) { return T[k] || f; }
    var CACHED = d.querySelector('meta[name="ft-cached"]');
    var NOT_OFFLINE = /^\/(accounts|admin|backup|i18n|__debug__)\/|^\/core\/my-data|\/import\//;

    /* ── Outbox (IndexedDB, same store the service worker writes) ─────────── */
    function db() {
        return new Promise(function (resolve, reject) {
            if (!window.indexedDB) return reject(new Error("no indexedDB"));
            var open = indexedDB.open("fintrack-offline", 1);
            open.onupgradeneeded = function () { open.result.createObjectStore("outbox", { keyPath: "key" }); };
            open.onsuccess = function () { resolve(open.result); };
            open.onerror = function () { reject(open.error); };
        });
    }
    function tx(mode, fn) {
        return db().then(function (conn) {
            return new Promise(function (resolve, reject) {
                var x = conn.transaction("outbox", mode), store = x.objectStore("outbox"), out;
                var r = fn(store);
                if (r) r.onsuccess = function () { out = r.result; };
                x.oncomplete = function () { conn.close(); resolve(out); };
                x.onerror = function () { conn.close(); reject(x.error); };
            });
        });
    }
    function all() { return tx("readonly", function (s) { return s.getAll(); }).then(function (r) { return r || []; }).catch(function () { return []; }); }
    function put(e) { return tx("readwrite", function (s) { return s.put(e); }); }
    function drop(key) { return tx("readwrite", function (s) { return s.delete(key); }); }
    function mine(list) { return list.filter(function (e) { return !e.user || e.user === ME; }); }

    /* ── Every save carries a key, who made it, and a short label ────────── */
    function uid() {
        if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
        return Date.now().toString(36) + Math.random().toString(36).slice(2, 12);
    }
    function label(form) {
        // "Deaths · 3 · Carp 2026 · P-1" — what it is, the number typed, and where.
        var page = (d.title || "").split(" | ")[0].trim();
        var head = form.querySelector(".modal-title, .card-title");
        var parts = [head && form.closest(".modal, [role=dialog]") ? head.textContent.trim() : page];
        var amount = form.querySelector("[name=amount], [name$=amount]");
        if (amount && amount.value) parts.push("৳" + amount.value);
        else {
            var n = Array.prototype.find.call(form.querySelectorAll("input[type=number], input[inputmode=decimal]"), function (i) { return i.value && i.offsetParent !== null; });
            if (n) parts.push(n.value);
        }
        var sel = Array.prototype.find.call(form.querySelectorAll("select"), function (s) { return s.value && s.options[s.selectedIndex]; });
        if (sel) parts.push(sel.options[sel.selectedIndex].text.split(" — ")[0].trim());
        if (parts[0] !== page && page) parts.push(page);
        return parts.filter(Boolean).join(" · ").slice(0, 140);
    }
    // Only a real submission gets a key — not a script reading the form (a live
    // preview, a quick-add), or the real save would look like a repeat.
    var submitting = null;
    function mark(form) { submitting = form; setTimeout(function () { if (submitting === form) submitting = null; }, 0); }
    d.addEventListener("submit", function (e) { if (!e.defaultPrevented) mark(e.target); });
    var nativeSubmit = HTMLFormElement.prototype.submit;
    HTMLFormElement.prototype.submit = function () { mark(this); return nativeSubmit.apply(this, arguments); };
    d.addEventListener("formdata", function (e) {
        var form = e.target;
        if (form !== submitting) return;
        // Read the attributes: a field named "method" or "action" would hide form.method / form.action.
        if (!ME || !form || !form.getAttribute || (form.getAttribute("method") || "").toLowerCase() !== "post" || form.hasAttribute("data-online-only")) return;
        var action;
        try { action = new URL(form.getAttribute("action") || location.href, location.href); } catch (err) { return; }
        if (action.origin !== location.origin || NOT_OFFLINE.test(action.pathname)) return;
        if (!form._ftKey) form._ftKey = uid();
        e.formData.set("_ft_key", form._ftKey);
        e.formData.set("_ft_user", ME);
        e.formData.set("_ft_page", location.pathname + location.search);
        e.formData.set("_ft_label", label(form));
        if (form._ftFixKey) { drop(form._ftFixKey).then(paint); form._ftFixKey = null; }
    });

    /* ── Sending what's waiting ──────────────────────────────────────────── */
    var syncing = false, timer = null;
    function csrf() { var m = d.cookie.match(/(?:^|; )csrftoken=([^;]+)/); return m ? decodeURIComponent(m[1]) : ""; }

    function send(entry) {
        var fd = new FormData();
        (entry.fields || []).forEach(function (f) {
            if (f[0] === "csrfmiddlewaretoken") return;
            if (f[1] instanceof Blob) {
                if (!f[1].size && !f[1].name) return;   // a photo box left empty
                fd.append(f[0], f[1], f[1].name || "photo");
            } else fd.append(f[0], f[1]);
        });
        return fetch(entry.url, {
            method: "POST", body: fd, credentials: "same-origin",
            headers: { "X-CSRFToken": csrf(), "X-FT-Replay": "1", "X-Requested-With": "XMLHttpRequest" },
        }).then(function (res) {
            var type = res.headers.get("Content-Type") || "";
            if (type.indexOf("application/json") !== -1) return res.json();
            if (/\/accounts\/login\//.test(res.url)) return { ok: false, why: "signin" };
            return { ok: false, why: "error" };
        });
    }

    function sync() {
        if (syncing || !ME || !navigator.onLine) return Promise.resolve();
        syncing = true;
        var sent = 0, stop = false;
        return all().then(function (list) {
            var todo = mine(list).filter(function (e) { return e.status === "waiting" || e.status === "sending" || e.status === "busy"; })
                .sort(function (a, b) { return a.created - b.created; });
            if (!todo.length) return;
            paint(t("sending", "Sending…"));
            return todo.reduce(function (chain, entry) {
                return chain.then(function () {
                    if (stop) return;
                    return send(entry).then(function (r) {
                        if (r.ok) { sent++; return drop(entry.key); }
                        entry.tries = (entry.tries || 0) + 1;
                        if (r.why === "busy") entry.status = "busy";
                        else if (r.why === "signin") { entry.status = "signin"; stop = true; }
                        else if (r.why === "fix") entry.status = "fix";
                        else if (r.why === "other-user") entry.status = "other";
                        else entry.status = entry.tries >= 3 ? "error" : "waiting";
                        return put(entry);
                    }, function () { stop = true; });  // the signal went again
                });
            }, Promise.resolve());
        }).then(function () {
            syncing = false;
            if (sent) done(sent);
            return paint();
        }, function () { syncing = false; paint(); });
    }

    function done(n) {
        var bar = d.createElement("div");
        bar.className = "offline-done";
        bar.setAttribute("role", "status");
        var text = d.createElement("span");
        text.textContent = n === 1 ? t("sentOne", "1 saved entry was sent.") : t("sentMany", "{n} saved entries were sent.").replace("{n}", n);
        var btn = d.createElement("button");
        btn.type = "button"; btn.className = "btn btn-soft btn-sm";
        btn.textContent = t("refresh", "Show the new figures");
        btn.addEventListener("click", function () { location.reload(); });
        bar.appendChild(text); bar.appendChild(btn);
        d.body.appendChild(bar);
        setTimeout(function () { bar.classList.add("is-out"); setTimeout(function () { bar.remove(); }, 300); }, 9000);
    }

    /* ── What's waiting: a small chip, and a sheet with the list ──────────── */
    var chip = null;
    function paint(override) {
        return all().then(function (list) {
            var items = mine(list);
            if (!chip) {
                chip = d.createElement("button");
                chip.type = "button";
                chip.className = "offline-chip";
                chip.addEventListener("click", openList);
                d.body.appendChild(chip);
            }
            var fix = items.filter(function (e) { return e.status === "fix" || e.status === "error"; }).length;
            var signin = items.some(function (e) { return e.status === "signin"; });
            chip.hidden = !items.length;
            chip.setAttribute("data-tone", fix || signin ? "warn" : "info");
            var msg = override || (signin ? t("signin", "Sign in to send what's saved")
                : fix ? (fix === 1 ? t("fixOne", "1 entry needs a look") : t("fixMany", "{n} entries need a look").replace("{n}", fix))
                : items.length === 1 ? t("waitingOne", "1 entry waiting to send") : t("waitingMany", "{n} entries waiting to send").replace("{n}", items.length));
            chip.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" d="M12 16.5V9.75m0 0l3 3m-3-3l-3 3M6.75 19.5a4.5 4.5 0 01-1.41-8.775 5.25 5.25 0 0110.233-2.33 3 3 0 013.758 3.848A3.752 3.752 0 0118 19.5H6.75z"/></svg><span></span>';
            chip.lastChild.textContent = msg;
            var pending = items.some(function (e) { return e.status === "waiting" || e.status === "busy"; });
            clearInterval(timer);
            if (pending) timer = setInterval(sync, 30000);
            return items;
        });
    }

    function when(ts) {
        var dt = new Date(ts);
        return dt.toLocaleString(root.lang === "bn" ? "bn-BD" : "en-GB", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
    }
    var STATUS = {
        waiting: ["info", "waitingStatus", "Waiting for signal"], busy: ["info", "waitingStatus", "Waiting for signal"],
        sending: ["info", "sending", "Sending…"], fix: ["warn", "fixStatus", "Not saved: something in it needs fixing"],
        error: ["warn", "errorStatus", "Couldn't be saved. Open it to check."], signin: ["warn", "signinStatus", "Sign in again to send it"],
        other: ["muted", "otherStatus", "Made by another account on this phone"],
    };

    function openList() {
        if (!window.FT || !FT.sheet) return;
        all().then(function (list) {
            var items = mine(list).sort(function (a, b) { return a.created - b.created; });
            FT.sheet({
                title: t("title", "Saved on this phone"),
                anchor: chip, returnTo: chip, wide: true,
                build: function (body, foot, close) {
                    var intro = d.createElement("p");
                    intro.className = "offline-intro";
                    intro.textContent = t("intro", "These were saved while there was no signal. They are sent by themselves when you're online.");
                    body.appendChild(intro);
                    var ul = d.createElement("ul");
                    ul.className = "offline-list";
                    items.forEach(function (e) {
                        var st = STATUS[e.status] || STATUS.waiting;
                        var li = d.createElement("li");
                        li.innerHTML = '<div class="offline-item-main"><p class="offline-item-title"></p><p class="offline-item-meta"></p><p class="offline-item-status"></p></div><div class="offline-item-actions"></div>';
                        li.querySelector(".offline-item-title").textContent = e.label || e.url;
                        li.querySelector(".offline-item-meta").textContent = t("savedAt", "Saved {when}").replace("{when}", when(e.created));
                        var s = li.querySelector(".offline-item-status");
                        s.textContent = t(st[1], st[2]); s.setAttribute("data-tone", st[0]);
                        var actions = li.querySelector(".offline-item-actions");
                        if (e.status === "fix" || e.status === "error") {
                            var fixBtn = d.createElement("button");
                            fixBtn.type = "button"; fixBtn.className = "btn btn-primary btn-sm";
                            fixBtn.textContent = t("open", "Open");
                            fixBtn.addEventListener("click", function () {
                                try { sessionStorage.setItem("ft-fix", e.key); } catch (err) {}
                                location.href = e.url;
                            });
                            actions.appendChild(fixBtn);
                        }
                        if (e.status === "signin") {
                            var a = d.createElement("a");
                            a.className = "btn btn-primary btn-sm"; a.href = "/accounts/login/?next=" + encodeURIComponent(location.pathname);
                            a.textContent = t("signinBtn", "Sign in");
                            actions.appendChild(a);
                        }
                        var rm = d.createElement("button");
                        rm.type = "button"; rm.className = "btn btn-ghost btn-sm";
                        rm.textContent = t("remove", "Remove");
                        rm.addEventListener("click", function () {
                            if (!confirm(t("removeAsk", "Remove this entry from the phone? It hasn't been saved in the app."))) return;
                            drop(e.key).then(function () { li.remove(); paint(); if (!ul.children.length) close(); });
                        });
                        actions.appendChild(rm);
                        ul.appendChild(li);
                    });
                    body.appendChild(ul);
                    var now = d.createElement("button");
                    now.type = "button"; now.className = "btn btn-primary";
                    now.textContent = navigator.onLine ? t("sendNow", "Send now") : t("noSignal", "No signal yet");
                    now.disabled = !navigator.onLine;
                    now.addEventListener("click", function () {
                        items.forEach(function (e) { if (e.status === "error" || e.status === "signin") e.status = "waiting"; });
                        Promise.all(items.map(put)).then(function () { close(); sync(); });
                    });
                    var more = d.createElement("a");
                    more.className = "btn btn-ghost"; more.href = "/core/offline/";
                    more.textContent = t("settings", "Use without internet");
                    foot.appendChild(more);
                    foot.appendChild(now);
                },
            });
        });
    }

    /* ── Fixing an entry the server didn't accept: fill its form again ───── */
    function refill() {
        var key;
        try { key = sessionStorage.getItem("ft-fix"); sessionStorage.removeItem("ft-fix"); } catch (e) { return; }
        if (!key) return;
        all().then(function (list) {
            var entry = list.filter(function (e) { return e.key === key; })[0];
            if (!entry) return;
            var forms = Array.prototype.filter.call(d.querySelectorAll("form"), function (f) { return (f.getAttribute("method") || "").toLowerCase() === "post"; });
            var form = forms.filter(function (f) { return new URL(f.getAttribute("action") || location.href, location.href).href.split("#")[0] === entry.url.split("#")[0]; })[0] || forms[0];
            if (!form) return;
            (entry.fields || []).forEach(function (f) {
                var name = f[0], value = f[1];
                if (/^(_ft_|csrfmiddlewaretoken$)/.test(name) || value instanceof Blob) return;
                form.querySelectorAll('[name="' + (window.CSS && CSS.escape ? CSS.escape(name) : name) + '"]').forEach(function (el) {
                    if (el.type === "radio" || el.type === "checkbox") el.checked = el.value === value;
                    else if (el._flatpickr) el._flatpickr.setDate(value, true);
                    else { el.value = value; el.dispatchEvent(new Event("input", { bubbles: true })); el.dispatchEvent(new Event("change", { bubbles: true })); }
                });
            });
            form._ftKey = entry.key;
            form._ftFixKey = entry.key;
            if (window.FT && FT.toast) FT.toast(t("refilled", "Your saved entry is filled in. Check it and save again."), "warn");
            form.scrollIntoView({ block: "start" });
        });
    }

    /* ── A page shown from the phone's copy ──────────────────────────────── */
    function today() {
        var n = new Date();
        return n.getFullYear() + "-" + String(n.getMonth() + 1).padStart(2, "0") + "-" + String(n.getDate()).padStart(2, "0");
    }
    function banner(text, tone) {
        var main = d.querySelector("main") || d.body;
        var b = d.createElement("div");
        b.className = "offline-banner";
        b.setAttribute("data-tone", tone || "warn");
        b.setAttribute("role", "status");
        b.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" d="M3 3l18 18M8.288 15.038a5.25 5.25 0 017.424 0M5.106 11.856a9.75 9.75 0 0110.034-2.4m3.754 2.4a9.716 9.716 0 00-1.56-1.267M1.924 8.674a14.25 14.25 0 0115.12-3.07M12 18.75h.008v.008H12v-.008z"/></svg><span></span>';
        b.lastChild.textContent = text;
        main.insertBefore(b, main.firstChild);
        return b;
    }
    function fromCopy() {
        if (!CACHED) return;
        var at = Number(CACHED.getAttribute("content")) || 0;
        banner(t("copy", "No signal. This is the page as it was {when}. You can still add entries: they're kept on this phone and sent later.").replace("{when}", at ? when(at) : ""));
        // A form kept from another day would suggest that day's date.
        var then = root.getAttribute("data-today"), now = today();
        if (then && then !== now) {
            d.querySelectorAll('input[value="' + then + '"]').forEach(function (el) {
                if (el._flatpickr) el._flatpickr.setDate(now, false); else el.value = now;
            });
        }
    }
    var liveBanner = null;
    function connection() {
        if (CACHED) return;
        if (!navigator.onLine && ME && !liveBanner) liveBanner = banner(t("offlineNow", "You're offline. Keep going: what you save is kept on this phone and sent when the signal is back."));
        else if (navigator.onLine && liveBanner) { liveBanner.remove(); liveBanner = null; }
    }

    /* ── Keep pages ready on the phone ────────────────────────────────────
       Everyday forms: every 6 hours on any connection. The rest of the app
       (every page, and the pages of your people, ponds, loans…): once a day
       on Wi-Fi, or when you tap "Save everything now". Pages kept recently
       are skipped, so a refresh costs little data. */
    var HOUR = 3600 * 1000, CORE_EVERY = 6 * HOUR, ALL_EVERY = 24 * HOUR;
    function index() { try { return JSON.parse(localStorage.getItem("ft-offline-index") || "{}"); } catch (e) { return {}; } }
    function saveIndex(info) { try { localStorage.setItem("ft-offline-index", JSON.stringify(info)); } catch (e) {} }
    function autoAll() { try { return localStorage.getItem("ft-offline-auto") !== "off"; } catch (e) { return true; } }
    function goodConnection() {
        var c = navigator.connection;
        if (!c) return true;
        if (c.saveData) return false;
        if (c.type && ["wifi", "ethernet", "wimax"].indexOf(c.type) === -1) return false;   // mobile data
        return !/(^|-)2g$/.test(c.effectiveType || "");
    }
    var warming = null;
    /* opts: all (bool), force (bool), onProgress(done, total) */
    function warm(opts) {
        opts = opts || {};
        // Already keeping pages: a "Save everything" waits for it, then goes on.
        if (warming) return opts.all ? warming.then(function () { return warm(opts); }) : Promise.resolve(null);
        if (!ME || !navigator.onLine || CACHED || !("serviceWorker" in navigator)) return Promise.resolve(null);
        var info = index();
        if (info.user !== ME) info = { user: ME };
        // Language changed: the kept pages speak the old one, so keep them again.
        if (info.lang && info.lang !== root.lang) { info.at = 0; info.allAt = 0; }
        var now = Date.now();
        var needCore = opts.force || now - (info.at || 0) > CORE_EVERY;
        var needAll = opts.all || (autoAll() && goodConnection() && now - (info.allAt || 0) > ALL_EVERY);
        if (!needCore && !needAll) return Promise.resolve(null);
        if (!opts.force && navigator.connection && navigator.connection.saveData) return Promise.resolve(null);
        warming = fetch("/core/offline-pages/", { credentials: "same-origin" }).then(function (r) { return r.ok ? r.json() : null; }).then(function (data) {
            if (!data) return null;
            var urls = data.pages.map(function (p) { return p.url; });
            if (data.fallback) urls.push(data.fallback);
            if (needAll) urls = urls.concat(data.more || []);
            return navigator.serviceWorker.ready.then(function (reg) {
                if (!reg.active) return null;
                return new Promise(function (resolve) {
                    var tag = String(now);
                    var listen = function (ev) {
                        var m = ev.data || {};
                        if (m.tag !== tag) return;
                        if (m.type === "warm-progress") { if (opts.onProgress) opts.onProgress(m.done, m.total); return; }
                        navigator.serviceWorker.removeEventListener("message", listen);
                        if (opts.onProgress) opts.onProgress(m.done, m.total);
                        if (m.type === "warmed") {
                            info.at = Date.now(); info.pages = data.pages; info.count = m.ok; info.lang = root.lang;
                            if (needAll) { info.allAt = Date.now(); info.total = m.ok; }
                            saveIndex(info);
                        }
                        resolve(m);
                    };
                    navigator.serviceWorker.addEventListener("message", listen);
                    reg.active.postMessage({ type: "warm", urls: urls, tag: tag, fresh: opts.all ? HOUR : (needAll ? 20 * HOUR : 0) });
                });
            });
        }).catch(function () { return null; }).then(function (r) { warming = null; return r; });
        return warming;
    }
    function keptCount() {
        if (!window.caches) return Promise.resolve(0);
        return caches.open("ftpages-v1").then(function (c) { return c.keys(); }).then(function (k) {
            return k.filter(function (r) { return r.url.indexOf("__ft_list=1") === -1; }).length;
        }).catch(function () { return 0; });
    }

    /* A background save (a tick, a toggle…) with no signal: keep it like a form. */
    function queue(url, fields, text) {
        var list = [["_ft_key", uid()], ["_ft_user", ME], ["_ft_page", location.pathname + location.search], ["_ft_label", text || ""]];
        Object.keys(fields || {}).forEach(function (k) { list.push([k, String(fields[k])]); });
        var entry = { key: list[0][1], user: ME, label: text || "", url: new URL(url, location.href).href, page: location.pathname + location.search,
                      fields: list, created: Date.now(), status: "waiting", tries: 0 };
        return put(entry).then(function () { paint(); if (window.FT && FT.toast) FT.toast(t("saved", "Saved on this phone. It will be sent when you're online."), "warn"); });
    }

    /* Signed out: nothing with someone's figures stays on the phone. */
    function forget() {
        try { localStorage.removeItem("ft-offline-index"); } catch (e) {}
        if ("serviceWorker" in navigator && navigator.serviceWorker.controller) navigator.serviceWorker.controller.postMessage({ type: "forget" });
        if (window.caches) caches.delete("ftpages-v1");
    }

    window.FT = Object.assign(window.FT || {}, { offlineSync: sync, offlineWarm: warm, offlineOutbox: all, offlineQueue: queue, offlineKept: keptCount, offlineList: openList });

    function start() {
        if (!ME) { if (/^\/accounts\/(login|logout)/.test(location.pathname)) forget(); return; }
        fromCopy();
        connection();
        if (location.hash === "#ft-saved") {
            history.replaceState(null, "", location.pathname + location.search);
            if (window.FT && FT.toast) FT.toast(t("saved", "Saved on this phone. It will be sent when you're online."), "warn");
        }
        refill();
        paint().then(function () { setTimeout(sync, 1200); });
        setTimeout(warm, 4000);
        window.addEventListener("online", function () { connection(); sync(); warm(); });
        // A search or filter with no signal and nothing kept from before.
        d.addEventListener("htmx:sendError", function () { if (window.FT && FT.toast) FT.toast(t("listOffline", "No signal. This list needs the internet the first time you open it."), "warn"); });
        window.addEventListener("offline", connection);
        d.addEventListener("visibilitychange", function () { if (d.visibilityState === "visible") { paint(); sync(); } });
        if ("serviceWorker" in navigator) navigator.serviceWorker.addEventListener("message", function (e) { if (e.data && e.data.type === "queued") paint(); });
    }
    if (d.readyState === "loading") d.addEventListener("DOMContentLoaded", start); else start();
})();
