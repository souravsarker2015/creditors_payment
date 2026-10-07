/* Farm calendar: the month grid's chips, the selected day's list, filters,
   to-do ticks, swipe and arrow keys — and the English ⇄ Bangla date converter.
   The Bangla calendar here matches apps/business/calendar/bangla.py. */
document.addEventListener("alpine:init", function () {
  var BN_DIGITS = "০১২৩৪৫৬৭৮৯";
  var isBn = (document.documentElement.lang || "").indexOf("bn") === 0;
  var DAY = 864e5;
  function num(v) { v = String(v); return isBn ? v.replace(/\d/g, function (d) { return BN_DIGITS[d]; }) : v; }
  function read(id) { var el = document.getElementById(id); try { return el ? JSON.parse(el.textContent) : {}; } catch (e) { return {}; } }

  var KINDS = ["mine", "pond", "sale", "feed", "due", "holiday"];
  var BY_CAT = { work: "var(--cal-work)", task: "var(--cal-task)", money: "var(--cal-money)", festival: "var(--cal-festival)", personal: "var(--cal-personal)" };
  var BY_KIND = { mine: "var(--cal-work)", pond: "var(--cal-pond)", sale: "var(--cal-sale)", feed: "var(--cal-feed)", due: "var(--cal-due)", holiday: "var(--cal-holiday)" };

  Alpine.data("farmCalendar", function (o) {
    return {
      sel: o.selected, items: read("cal-items"), days: read("cal-days"), kindLabels: read("cal-kinds"),
      on: {}, adding: false, form: { date: o.selected }, icons: {}, tx: 0, ty: 0,
      init() {
        var saved = {};
        try { saved = JSON.parse(localStorage.getItem("calFilters") || "{}"); } catch (e) { saved = {}; }
        var on = {};
        KINDS.forEach(function (k) { on[k] = saved[k] !== false; });
        this.on = on;
        var icons = {};
        this.$root.querySelectorAll("template[data-icon]").forEach(function (t) { icons[t.dataset.icon] = t.innerHTML; });
        this.icons = icons;
      },
      num: num,
      toggle(k) {
        this.on[k] = !this.on[k];
        try { localStorage.setItem("calFilters", JSON.stringify(this.on)); } catch (e) { /* private mode: fine */ }
      },
      visible(iso) { var on = this.on; return (this.items[iso] || []).filter(function (i) { return on[i.kind]; }); },
      kindsOn(iso) {
        var seen = [];
        this.visible(iso).forEach(function (i) { if (seen.indexOf(i.kind) < 0) seen.push(i.kind); });
        return seen.slice(0, 4);
      },
      color(i) {
        if (i.kind === "mine") return BY_CAT[i.cat] || BY_CAT.work;
        if (i.tone === "critical") return "var(--status-critical)";
        return BY_KIND[i.kind] || "var(--text-muted)";
      },
      icon(name) { return this.icons[name] || ""; },
      day() { return this.days[this.sel] || { head: "", sub: "" }; },
      pick(iso) {
        this.sel = iso; this.form.date = iso;
        try { var u = new URL(location.href); u.searchParams.set("day", iso); history.replaceState(null, "", u); } catch (e) { /* old browser */ }
        if (window.innerWidth < 1024 && this.$refs.day) {     // phones: bring the day's list into view
          var r = this.$refs.day.getBoundingClientRect();
          if (r.top > window.innerHeight - 96) this.$refs.day.scrollIntoView({ behavior: "smooth", block: "start" });
        }
      },
      openAdd() {
        this.form.date = this.sel; this.adding = true;
        this.$nextTick(function () { var t = document.getElementById("add-title"); if (t) t.focus(); });
      },
      go(url, iso) { var u = new URL(url, location.href); if (iso) u.searchParams.set("day", iso); location.href = u.toString(); },
      keys(e) {
        if (e.key === "PageUp") { e.preventDefault(); this.go(o.prev); return; }
        if (e.key === "PageDown") { e.preventDefault(); this.go(o.next); return; }
        var step = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 }[e.key];
        if (!step) return;
        e.preventDefault();
        var d = new Date(this.sel + "T00:00:00Z"); d.setUTCDate(d.getUTCDate() + step);
        var iso = d.toISOString().slice(0, 10);
        if (!this.days[iso]) { this.go(step > 0 ? o.next : o.prev, iso); return; }
        this.pick(iso);
        var root = this.$root;
        this.$nextTick(function () { var c = root.querySelector('[data-iso="' + iso + '"]'); if (c) c.focus(); });
      },
      touchStart(e) { var t = e.touches[0]; this.tx = t.clientX; this.ty = t.clientY; },
      touchEnd(e) {
        var t = e.changedTouches[0], dx = t.clientX - this.tx, dy = t.clientY - this.ty;
        if (Math.abs(dx) > 70 && Math.abs(dx) > Math.abs(dy) * 1.5) this.go(dx < 0 ? o.next : o.prev);
      },
      tick(i) {
        var items = this.items;
        fetch(o.doneUrl.replace("/0/", "/" + i.pk + "/"), { method: "POST", headers: { "X-CSRFToken": o.csrf, "X-Requested-With": "fetch" } })
          .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
          .then(function (d) {
            Object.keys(items).forEach(function (k) { items[k].forEach(function (x) { if (x.kind === "mine" && x.pk === i.pk) x.done = d.done; }); });
          })
          .catch(function () {
            // No signal: keep the tick on the phone and send it later.
            if (navigator.onLine || !(window.FT && FT.offlineQueue)) return;
            var done = !i.done;
            FT.offlineQueue(o.doneUrl.replace("/0/", "/" + i.pk + "/"), {}, (done ? "✓ " : "↺ ") + (i.title || ""));
            Object.keys(items).forEach(function (k) { items[k].forEach(function (x) { if (x.kind === "mine" && x.pk === i.pk) x.done = done; }); });
          });
      },
    };
  });

  /* The Bangla calendar (Bangladesh, 2019 revision): the same English date for every Bangla date, every year. */
  var STARTS = [[4, 14], [5, 15], [6, 15], [7, 16], [8, 16], [9, 16], [10, 17], [11, 16], [12, 16], [1, 15], [2, 14], [3, 15]];
  function starts(y) { var g = y + 593; return STARTS.map(function (md, i) { return Date.UTC(i < 9 ? g : g + 1, md[0] - 1, md[1]); }); }
  function toBangla(ms) {
    var d = new Date(ms), y = d.getUTCFullYear(), m = d.getUTCMonth() + 1, dd = d.getUTCDate();
    var by = (m > 4 || (m === 4 && dd >= 14)) ? y - 593 : y - 594;
    var s = starts(by), i = 11;
    while (s[i] > ms) i--;
    return { y: by, m: i + 1, d: Math.round((ms - s[i]) / DAY) + 1 };
  }
  function monthLength(y, m) { var s = starts(y), end = m < 12 ? s[m] : starts(y + 1)[0]; return Math.round((end - s[m - 1]) / DAY); }
  function englishText(ms) {
    return new Date(ms).toLocaleDateString(isBn ? "bn-BD" : "en-GB", { weekday: "long", day: "numeric", month: "long", year: "numeric", timeZone: "UTC" });
  }

  Alpine.data("dateConverter", function (months, tooShort) {
    return {
      months: months, en: "", by: 1433, bm: 1, bd: 1, bnText: "", enText: "", num: num,
      init() {
        var t = new Date();
        this.en = t.getFullYear() + "-" + String(t.getMonth() + 1).padStart(2, "0") + "-" + String(t.getDate()).padStart(2, "0");
        this.fromEn();
      },
      bnFormat(b) { return num(b.d) + " " + this.months[b.m - 1] + " " + num(b.y); },
      fromEn() {
        if (!/^\d{4}-\d{2}-\d{2}$/.test(this.en)) return;
        var p = this.en.split("-").map(Number), ms = Date.UTC(p[0], p[1] - 1, p[2]), b = toBangla(ms);
        this.by = b.y; this.bm = b.m; this.bd = b.d;
        this.bnText = this.bnFormat(b); this.enText = englishText(ms);
      },
      fromBn() {
        var y = Number(this.by), m = Number(this.bm), d = Number(this.bd);
        if (!(y >= 1300 && y <= 1600)) { this.enText = ""; return; }
        var len = monthLength(y, m);
        if (d > len) { this.enText = (tooShort || "").replace("{month}", this.months[m - 1]).replace("{n}", num(len)); return; }
        var ms = starts(y)[m - 1] + (d - 1) * DAY;
        this.en = new Date(ms).toISOString().slice(0, 10);
        this.enText = englishText(ms); this.bnText = this.bnFormat({ y: y, m: m, d: d });
      },
    };
  });
});
