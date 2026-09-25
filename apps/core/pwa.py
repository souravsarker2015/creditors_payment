"""Installable-app (PWA) plumbing: manifest, service worker, offline page.

The service worker is served from the site root (/sw.js) so its scope
covers every page. It never stores pages with your data in them: pages
always come from the network, and only when that fails is the offline page
shown. Static files (CSS/JS/icons, and the CDN libraries) are cached so the
app opens quickly.
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
        "start_url": reverse("networth") + "?source=app",
        "scope": "/",
        "display": "standalone",
        "background_color": "#f7f6f1",
        "theme_color": "#16241f",
        "icons": icons,
        "shortcuts": [
            {"name": _("New Expense"), "url": reverse("expense_create"), "icons": icons[:1]},
            {"name": _("Household (Bazar)"), "url": reverse("household_dashboard"), "icons": icons[:1]},
            {"name": _("Budgets"), "url": reverse("budget_list"), "icons": icons[:1]},
        ],
    }
    return JsonResponse(data, content_type="application/manifest+json", json_dumps_params={"ensure_ascii": False})


def _version():
    """Changes whenever a precached file changes, so phones pick up updates."""
    stamps = [os.path.getmtime(f) for f in (finders.find("css/app.css"), finders.find("js/charts.js"), __file__) if f]
    return str(int(max(stamps)))


@cache_control(no_cache=True, max_age=0)
def service_worker_view(request):
    config = {
        "version": _version(),
        "offline": reverse("offline"),
        "precache": [reverse("offline"), asset("css/app.css"), static("img/icons/icon-192.png")],
    }
    script = "const CONFIG = " + json.dumps(config) + ";\n" + SW_BODY
    response = HttpResponse(script, content_type="application/javascript")
    response["Service-Worker-Allowed"] = "/"
    return response


def offline_view(request):
    return render(request, "offline.html")


SW_BODY = r"""
const CACHE = "fintrack-" + CONFIG.version;
const CDN = ["cdn.jsdelivr.net", "cdn.tailwindcss.com", "fonts.googleapis.com", "fonts.gstatic.com"];

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

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);

  // Pages: always the network (they hold your data); offline page if that fails.
  if (req.mode === "navigate") {
    event.respondWith(fetch(req).catch(() => caches.match(CONFIG.offline)));
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
"""
