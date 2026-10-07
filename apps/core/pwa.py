"""Installable-app (PWA) plumbing: manifest, service worker, offline page.

The service worker is served from the site root (/sw.js) so its scope
covers every page. Pages always come from the network first; only when
that fails (or takes too long) is a kept copy or the offline page shown.
Static files (CSS/JS/icons, and the CDN libraries) are cached so the app
opens quickly.

Works without internet (apps/core/offline.py): pages marked X-FT-Offline are
also kept on the phone. With no signal you see the kept copy (marked, with a
banner), and a form that can't be sent is kept in the phone's outbox and sent
by static/js/offline.js when the signal is back.
"""
import json
import os

from django.contrib.staticfiles import finders
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.templatetags.static import static
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.cache import cache_control

from .templatetags.ui import asset


def manifest_view(request):
    icons = [
        {"src": static("img/icons/icon-192.png"), "sizes": "192x192", "type": "image/png", "purpose": "any"},
        {"src": static("img/icons/icon-512.png"), "sizes": "512x512", "type": "image/png", "purpose": "any"},
        {"src": static("img/icons/icon-maskable-512.png"), "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
    ]
    data = {
        "name": "FinTrack",
        "short_name": "FinTrack",
        "description": _("Loans, dues, income, spending and household bazar in one place."),
        "lang": request.LANGUAGE_CODE,
        "start_url": reverse("home") + "?source=app",
        "scope": "/",
        "display": "standalone",
        "background_color": "#f7f6f1",
        "theme_color": "#16241f",
        "icons": icons,
        "shortcuts": [
            {"name": _("New Expense"), "url": reverse("expense_create"), "icons": icons[:1]},
            {"name": _("Household (Bazar)"), "url": reverse("household_dashboard"), "icons": icons[:1]},
            {"name": _("Budgets"), "url": reverse("budget_list"), "icons": icons[:1]},
            {"name": _("Savings Goals"), "url": reverse("goal_list"), "icons": icons[:1]},
        ],
    }
    return JsonResponse(data, content_type="application/manifest+json", json_dumps_params={"ensure_ascii": False})


def _version():
    """Changes whenever a precached file changes, so phones pick up updates."""
    stamps = [os.path.getmtime(f) for f in (finders.find("css/app.css"), finders.find("js/charts.js"), finders.find("js/offline.js"), finders.find("js/pickers.js"), __file__) if f]
    return str(int(max(stamps)))


@cache_control(no_cache=True, max_age=0)
def service_worker_view(request):
    config = {
        "version": _version(),
        "offline": reverse("offline"),
        "precache": [reverse("offline"), asset("css/app.css"), asset("css/tailwind.css"), asset("js/pickers.js"), asset("js/offline.js"), static("img/icons/icon-192.png")],
    }
    script = "const CONFIG = " + json.dumps(config) + ";\n" + SW_BODY
    response = HttpResponse(script, content_type="application/javascript")
    response["Service-Worker-Allowed"] = "/"
    return response


def offline_view(request):
    return render(request, "offline.html")


SW_BODY = r"""
const CACHE = "fintrack-" + CONFIG.version;        // app files: replaced with each update
const PAGES = "ftpages-v1";                        // pages you opened, kept for when there's no signal
const MAX_PAGES = 500;
const CDN = ["cdn.jsdelivr.net", "fonts.googleapis.com", "fonts.gstatic.com"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(CONFIG.precache)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k.startsWith("fintrack-") && k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

/* ── The phone's outbox (IndexedDB), shared with static/js/offline.js ── */
function db() {
  return new Promise((resolve, reject) => {
    const open = indexedDB.open("fintrack-offline", 1);
    open.onupgradeneeded = () => open.result.createObjectStore("outbox", { keyPath: "key" });
    open.onsuccess = () => resolve(open.result);
    open.onerror = () => reject(open.error);
  });
}
async function keep(entry) {
  const d = await db();
  await new Promise((resolve, reject) => {
    const tx = d.transaction("outbox", "readwrite");
    tx.objectStore("outbox").put(entry);
    tx.oncomplete = resolve; tx.onerror = () => reject(tx.error);
  });
  d.close();
}

/* ── Pages ── */
// A search list (htmx) is kept apart from the full page at the same address.
function keyOf(req) {
  const url = req.url.split("#")[0];
  return req.headers.get("HX-Request") ? url + (url.includes("?") ? "&" : "?") + "__ft_list=1" : url;
}

async function remember(req, res) {
  if (!res || res.status !== 200 || res.headers.get("X-FT-Offline") !== "1") return;
  const headers = new Headers(res.headers);
  headers.set("X-FT-Saved-At", String(Date.now()));
  const copy = new Response(await res.clone().blob(), { status: 200, headers });
  const cache = await caches.open(PAGES);
  const url = keyOf(req);
  await cache.delete(url);           // re-adding moves it to the end: the list stays newest-last
  await cache.put(url, copy);
  const keys = await cache.keys();
  for (const old of keys.slice(0, Math.max(0, keys.length - MAX_PAGES))) await cache.delete(old);
}

async function savedCopy(req) {
  const cache = await caches.open(PAGES);
  const url = req.url.split("#")[0];
  let hit = (await cache.match(url)) || (await cache.match(url.split("?")[0]));
  if (!hit) {
    // Same page with other filters: better than nothing (never a search list).
    const keys = await cache.keys(url, { ignoreSearch: true });
    const other = keys.reverse().find((k) => !k.url.includes("__ft_list=1"));
    if (other) hit = await cache.match(other);
  }
  if (!hit) return null;
  // Tell the page it's a kept copy (banner, no reload loop, today's date in forms).
  const html = await hit.text();
  const meta = '<meta name="ft-cached" content="' + (hit.headers.get("X-FT-Saved-At") || "") + '">';
  const body = html.replace(/<head([^>]*)>/i, (m) => m + meta);
  return new Response(body, { status: 200, headers: { "Content-Type": "text/html; charset=utf-8" } });
}

// "You're offline", in the language last used (kept with the pages), else the one from install.
async function offlineScreen() {
  return (await (await caches.open(PAGES)).match(new URL(CONFIG.offline, self.location.origin).href)) || caches.match(CONFIG.offline);
}

function wait(ms) { return new Promise((resolve) => setTimeout(() => resolve(null), ms)); }

async function page(event) {
  const req = event.request;
  const network = fetch(req);
  event.waitUntil(network.then((res) => remember(req, res.clone())).catch(() => {}));
  // A download (?export=…) is never answered with the page it was asked from.
  const kept = new URL(req.url).searchParams.has("export") ? null : await savedCopy(req);
  if (!kept) return network.catch(offlineScreen);
  // Weak signal: don't keep someone waiting when a copy is on the phone.
  const quick = await Promise.race([network.catch(() => null), wait(7000)]);
  return quick || kept;
}

/* ── Saving with no signal ── */
async function save(event) {
  const req = event.request;
  const copy = req.clone();
  const sent = fetch(req);
  const res = await Promise.race([sent.catch(() => null), wait(25000)]);
  if (res) return res;
  let form;
  try { form = await copy.formData(); } catch (e) { form = null; }
  if (!form || !form.get("_ft_key")) {
    return sent.catch(offlineScreen);
  }
  const fields = [];
  for (const [name, value] of form.entries()) fields.push([name, value]);
  const pageUrl = form.get("_ft_page") || req.referrer || "/";
  await keep({
    key: form.get("_ft_key"), user: form.get("_ft_user") || "", label: form.get("_ft_label") || "",
    url: req.url, page: pageUrl, fields, created: Date.now(), status: "waiting", tries: 0,
  });
  const back = new URL(pageUrl, self.location.origin);
  back.hash = "ft-saved";
  return Response.redirect(back.href, 303);
}

self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);

  if (req.mode === "navigate" && url.origin === self.location.origin) {
    if (req.method === "POST") { event.respondWith(save(event)); return; }
    if (req.method === "GET") { event.respondWith(page(event)); return; }
  }
  if (req.method !== "GET") return;

  // A search or filter list (htmx): the network, or the same list from before when there's no signal.
  if (url.origin === self.location.origin && req.headers.get("HX-Request")) {
    event.respondWith((async () => {
      try {
        const res = await fetch(req);
        event.waitUntil(remember(req, res.clone()));
        return res;
      } catch (e) {
        const hit = await (await caches.open(PAGES)).match(keyOf(req));
        if (hit) return hit;
        throw e;
      }
    })());
    return;
  }

  // Static files and CDN libraries: serve from cache, refresh in the background.
  const isStatic = url.origin === self.location.origin && url.pathname.startsWith("/static/");
  if (isStatic || CDN.includes(url.hostname)) {
    event.respondWith(
      caches.open(CACHE).then(async (cache) => {
        const cached = await cache.match(req);
        const network = fetch(req)
          .then((res) => { if (res && (res.ok || res.type === "opaque")) cache.put(req, res.clone()); return res; })
          .catch(() => cached);
        return cached || network;
      })
    );
  }
});

/* ── Messages from the page ── */
self.addEventListener("message", (event) => {
  const msg = event.data || {};
  if (msg.type === "warm") {
    // Keep pages ready, so they open at the pond with no signal. Pages kept
    // recently (msg.fresh ms) are skipped, so a refresh costs little data.
    event.waitUntil((async () => {
      const urls = msg.urls || [], fresh = msg.fresh || 0, cache = await caches.open(PAGES);
      let ok = 0, done = 0, stopped = false;
      const assets = new Set();
      const tell = (type) => { if (event.source) event.source.postMessage({ type, ok, done, total: urls.length, tag: msg.tag || "" }); };
      for (const u of urls) {
        done++;
        if (fresh) {
          const kept = await cache.match(new URL(u, self.location.origin).href);
          if (kept && Date.now() - Number(kept.headers.get("X-FT-Saved-At") || 0) < fresh) { ok++; continue; }
        }
        try {
          const req = new Request(u, { credentials: "same-origin", headers: { "X-FT-Warm": "1" } });
          const res = await fetch(req);
          if (res.status === 200 && res.headers.get("X-FT-Offline") === "1") {
            const html = await res.clone().text();
            await remember(req, res); ok++;
            // The page's own scripts and styles (a chart, the calendar…) must be on the phone too.
            for (const m of html.matchAll(/<(?:script[^>]+src|link[^>]+href)="([^"]+\.(?:js|css)[^"]*)"/g)) assets.add(new URL(m[1].replace(/&amp;/g, "&"), self.location.origin).href);
          }
        } catch (e) { stopped = true; break; }        // signal gone: stop, try again another time
        if (done % 5 === 0) tell("warm-progress");
        await wait(120);                               // gentle on a weak connection and on the server
      }
      if (!stopped) {
        const files = await caches.open(CACHE);
        for (const href of assets) {
          const u = new URL(href);
          if (u.origin !== self.location.origin && !CDN.includes(u.hostname)) continue;
          if (await files.match(href)) continue;
          try {
            const res = await fetch(href, u.origin === self.location.origin ? {} : { mode: "cors", credentials: "omit" });
            if (res.ok) await files.put(href, res);
          } catch (e) { /* tried again next time */ }
        }
      }
      tell(stopped ? "warm-stopped" : "warmed");
    })());
  } else if (msg.type === "forget") {
    // Signed out: pages with someone's figures don't stay on the phone.
    event.waitUntil(caches.delete(PAGES));
  }
});
"""
