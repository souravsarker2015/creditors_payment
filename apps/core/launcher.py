"""The app's shortcuts.

- "All shortcuts" (/core/shortcuts/): every part of the app a tap away, as tiles — money, Productivity
  and the farm, by what the person may open. It's the first shortcut on the app icon by default.
- What a long press on the installed app's icon offers: the manifest's shortcuts (apps/core/pwa.py),
  chosen on that page (UserProfile.app_shortcuts). Phones show only the first few (Android: 3 or 4,
  by the launcher), so the person picks them, in order; an installed app picks up a change when the
  browser next refreshes it (on Android, within a day)."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import NoReverseMatch, reverse
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

SLOTS = 4
DEFAULT = ("all", "new_expense", "household", "budgets")

GROUPS = (
    ("add", gettext_lazy("Add")),
    ("money", gettext_lazy("Money")),
    ("work", gettext_lazy("Productivity")),
    ("farm", gettext_lazy("Farm")),
)
# key: (name, url name, query, icon, group, who can open it: "personal", "work" or "business")
SHORTCUTS = {
    "all": (gettext_lazy("All shortcuts"), "launcher", "", "grid", "", ""),
    "new_expense": (gettext_lazy("New Expense"), "expense_create", "", "plus", "add", "personal"),
    "new_task": (gettext_lazy("New task"), "work:task_new", "", "check", "add", "work"),
    "new_note": (gettext_lazy("New note"), "work:notes", "?new=1", "edit", "add", "work"),
    "daily_note": (gettext_lazy("Today’s note"), "work:note_today", "", "words", "add", "work"),
    "home": (gettext_lazy("Home"), "home", "", "chart", "money", "personal"),
    "upcoming": (gettext_lazy("Upcoming money"), "upcoming", "", "calendar", "money", "personal"),
    "creditors": (gettext_lazy("Creditors"), "dashboard", "", "users", "money", "personal"),
    "debtors": (gettext_lazy("Debtors"), "debtor_dashboard", "", "bank", "money", "personal"),
    "shops": (gettext_lazy("Shop Dues"), "shop_dashboard", "", "cart", "money", "personal"),
    "expenses": (gettext_lazy("Expense"), "expense_dashboard", "", "banknotes", "money", "personal"),
    "income": (gettext_lazy("Income"), "income_dashboard", "", "trend", "money", "personal"),
    "wallets": (gettext_lazy("Wallets"), "wallet_list", "", "wallet", "money", "personal"),
    "budgets": (gettext_lazy("Budgets"), "budget_list", "", "pie", "money", "personal"),
    "goals": (gettext_lazy("Savings Goals"), "goal_list", "", "trophy", "money", "personal"),
    "household": (gettext_lazy("Household (Bazar)"), "household_dashboard", "", "map", "money", "personal"),
    "report": (gettext_lazy("Money report"), "money_report", "", "percent", "money", "personal"),
    "today": (gettext_lazy("Today"), "work:today", "", "sun", "work", "work"),
    "tasks": (gettext_lazy("Tasks"), "work:tasks", "", "list", "work", "work"),
    "plan": (gettext_lazy("Plan my day"), "work:plan", "", "clock", "work", "work"),
    "calendar": (gettext_lazy("Calendar"), "work:calendar", "", "calendar", "work", "work"),
    "notes": (gettext_lazy("Notes"), "work:notes", "", "note", "work", "work"),
    "exam": (gettext_lazy("Exam notes"), "work:exam", "", "exam", "work", "work"),
    "flashcards": (gettext_lazy("Flashcards"), "work:cards", "", "cards", "work", "work"),
    "jobs": (gettext_lazy("Job search"), "work:jobs", "", "map", "work", "work"),
    "prep": (gettext_lazy("Interview prep"), "work:prep", "", "target", "work", "work"),
    "stories": (gettext_lazy("STAR stories"), "work:stories", "", "star", "work", "work"),
    "focus": (gettext_lazy("Focus timer"), "work:focus", "", "bolt", "work", "work"),
    "time": (gettext_lazy("Time"), "work:time", "", "timer", "work", "work"),
    "journal": (gettext_lazy("Journal & standup"), "work:journal", "", "journal", "work", "work"),
    "snippets": (gettext_lazy("Snippets"), "work:snippets", "", "code", "work", "work"),
    "farm": (gettext_lazy("Farm"), "business:home", "", "flag", "farm", "business"),
}


def _areas(user):
    from apps.business.core.access import BUSINESS, PERSONAL, has_dashboard
    from apps.productivity.access import can_use

    if not user.is_authenticated:
        return set()
    return {a for a, ok in (("personal", has_dashboard(user, PERSONAL)), ("business", has_dashboard(user, BUSINESS)), ("work", can_use(user))) if ok}


def _url(key):
    name, url_name, query = SHORTCUTS[key][:3]
    try:
        return reverse(url_name) + query
    except NoReverseMatch:
        return ""


def available(user):
    """The shortcuts this person can open: [{"key", "name", "url", "icon", "group"}], in the catalogue's order."""
    areas = _areas(user)
    out = []
    for key, (name, _u, _q, icon, group, area) in SHORTCUTS.items():
        url = _url(key)
        if url and (not area or area in areas):
            out.append({"key": key, "name": str(name), "url": url, "icon": icon, "group": group})
    return out


def chosen(user):
    """The keys on the app icon, in order: the person's own, else the usual ones (what they can open)."""
    have = {s["key"] for s in available(user)}
    mine = getattr(getattr(user, "profile", None), "app_shortcuts", None) if user.is_authenticated else None
    keys = [k for k in (mine or DEFAULT) if k in have]
    if not mine and len(keys) < SLOTS:       # the usual ones need the money pages: fill up from what's there
        keys += [s["key"] for s in available(user) if s["key"] not in keys][:SLOTS - len(keys)]
    return list(dict.fromkeys(keys))[:SLOTS]


def manifest_shortcuts(request, icons):
    """The manifest's "shortcuts" (signed out — the browser's first look — the usual ones)."""
    keys = chosen(request.user) if request.user.is_authenticated else DEFAULT
    return [{"name": str(SHORTCUTS[k][0]), "short_name": str(SHORTCUTS[k][0])[:24], "url": _url(k), "icons": icons} for k in keys if _url(k)]


@login_required
def launcher_view(request):
    items = available(request.user)
    if request.method == "POST":
        have = {s["key"] for s in items}
        keys = [request.POST.get(f"slot{i}", "") for i in range(1, SLOTS + 1)]
        request.user.profile.app_shortcuts = list(dict.fromkeys(k for k in keys if k in have))
        request.user.profile.save(update_fields=["app_shortcuts"])
        messages.success(request, _("Saved. The app icon shows them once your phone refreshes the app — usually within a day."))
        return redirect("launcher")
    groups = [(key, label, [s for s in items if s["group"] == key]) for key, label in GROUPS]
    return render(request, "core/launcher.html", {
        "groups": [g for g in groups if g[2]], "items": items, "slots": list(enumerate(chosen(request.user) + [""] * SLOTS, 1))[:SLOTS],
    })
