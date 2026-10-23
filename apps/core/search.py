"""Search everything: one box for people, ponds, entries and pages across the
personal ledgers, the farm business and Productivity.

Each source only runs for someone who may open it: the personal ledgers need
personal access, farm records need business access, and farm money (partners,
workers, transactions…) needs the "view_finance" capability — so a data-entry
worker never sees money they couldn't see on the page itself.
"""
from dataclasses import dataclass, field

from django.apps import apps
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import render
from django.urls import NoReverseMatch, reverse
from django.utils.translation import gettext as _, gettext_noop

PER_GROUP = 6
MIN_LENGTH = 2
BN_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")


@dataclass
class Hit:
    title: str
    meta: str
    url: str
    icon: str = "list"


@dataclass
class Group:
    title: str
    hits: list = field(default_factory=list)


def _q(text, *fields):
    cond = Q()
    for f in fields:
        cond |= Q(**{f"{f}__icontains": text})
    return cond


def _url(name, *args, query=""):
    try:
        return reverse(name, args=args) + query
    except NoReverseMatch:
        return ""


# Pages anyone could be looking for by name ("feed plan", "বাকি"…):
# (title, url name, area, capability or "").
PAGES = [
    (gettext_noop("Home"), "home", "personal", ""),
    (gettext_noop("Upcoming money"), "upcoming", "personal", ""),
    (gettext_noop("Money report"), "money_report", "personal", ""),
    (gettext_noop("Net Worth"), "networth", "personal", ""),
    (gettext_noop("How this app works"), "help", "personal", ""),
    (gettext_noop("Use without internet"), "offline_settings", "personal", ""),
    (gettext_noop("My data & backup"), "my_data_page", "personal", ""),
    (gettext_noop("Creditors"), "dashboard", "personal", ""),
    (gettext_noop("Debtors"), "debtor_dashboard", "personal", ""),
    (gettext_noop("Shop Dues"), "shop_dashboard", "personal", ""),
    (gettext_noop("Income"), "income_dashboard", "personal", ""),
    (gettext_noop("Expense"), "expense_dashboard", "personal", ""),
    (gettext_noop("Budgets"), "budget_list", "personal", ""),
    (gettext_noop("Savings Goals"), "goal_list", "personal", ""),
    (gettext_noop("Contributors"), "contributor_dashboard", "personal", ""),
    (gettext_noop("Household (Bazar)"), "household_dashboard", "personal", ""),
    (gettext_noop("All bazar purchases"), "household_purchase_all", "personal", ""),
    (gettext_noop("Wallets"), "wallet_list", "personal", ""),
    (gettext_noop("Recently deleted"), "trash_list", "personal", ""),
    (gettext_noop("Account & security"), "account_settings", "personal", ""),
    (gettext_noop("Where you're signed in"), "account_settings", "personal", ""),
    (gettext_noop("Morning reminder email"), "upcoming", "personal", ""),
    (gettext_noop("Zakat helper"), "zakat", "personal", ""),
    (gettext_noop("Ponds"), "business:ponds", "business", ""),
    (gettext_noop("When to harvest"), "business:harvest_forecast", "business", ""),
    (gettext_noop("Pond supplies"), "business:supplies", "business", ""),
    (gettext_noop("Fish health"), "business:fish_health", "business", ""),
    (gettext_noop("Feed"), "business:feed_stock", "business", ""),
    (gettext_noop("Feed plan"), "business:feed_plan", "business", ""),
    (gettext_noop("Count the store"), "business:feed_count", "business", ""),
    (gettext_noop("Evening summary"), "business:day_summary", "business", ""),
    (gettext_noop("Advance (dadon) from a buyer"), "business:advance_add", "business", ""),
    (gettext_noop("Fish sales"), "business:sales", "business", ""),
    (gettext_noop("Equipment"), "business:equipment", "business", ""),
    (gettext_noop("Calendar"), "business:calendar", "business", ""),
    (gettext_noop("Suppliers"), "business:suppliers", "business", ""),
    (gettext_noop("Buyers"), "business:buyers", "business", ""),
    (gettext_noop("Markets & aarots"), "business:markets", "business", ""),
    (gettext_noop("Fish prices"), "business:prices", "business", ""),
    (gettext_noop("How it works"), "business:guide", "business", ""),
    (gettext_noop("Farm papers"), "business:papers", "business", "manage_settings"),
    (gettext_noop("Baki (dues)"), "business:dues", "business", "view_finance"),
    (gettext_noop("Staff & wages"), "business:staff", "business", "view_finance"),
    (gettext_noop("Partners"), "business:partners", "business", "view_finance"),
    (gettext_noop("Profit sharing"), "business:partner_sharing", "business", "view_finance"),
    (gettext_noop("Loans"), "business:loans", "business", "view_finance"),
    (gettext_noop("Money in & out"), "business:transactions", "business", "view_finance"),
    (gettext_noop("Family income"), "business:family_income", "business", "view_finance"),
    (gettext_noop("Upcoming money"), "business:upcoming", "business", "view_finance"),
    (gettext_noop("Family members"), "business:family_members", "business", "view_finance"),
    (gettext_noop("Accounts"), "business:accounts", "business", "view_finance"),
    (gettext_noop("Income & expenses"), "business:statement", "business", "view_reports"),
    (gettext_noop("All reports"), "business:reports", "business", "view_reports"),
    (gettext_noop("What the farm is worth"), "business:worth", "business", "view_finance"),
    (gettext_noop("Productivity"), "work:today", "work", ""),
    (gettext_noop("Tasks"), "work:tasks", "work", ""),
    (gettext_noop("Calendar"), "work:calendar", "work", ""),
    (gettext_noop("Goals"), "work:goals", "work", ""),
    (gettext_noop("Learning"), "work:learning", "work", ""),
    (gettext_noop("Focus timer"), "work:focus", "work", ""),
    (gettext_noop("Time"), "work:time", "work", ""),
    (gettext_noop("Journal & standup"), "work:journal", "work", ""),
    (gettext_noop("Review & brag document"), "work:review", "work", ""),
    (gettext_noop("Reports"), "work:reports", "work", ""),
    (gettext_noop("Notes"), "work:notes", "work", ""),
    (gettext_noop("Snippets"), "work:snippets", "work", ""),
    (gettext_noop("Diagrams"), "work:diagrams", "work", ""),
    (gettext_noop("Mind map"), "work:diagrams", "work", ""),
    (gettext_noop("System design"), "work:diagrams", "work", ""),
    (gettext_noop("Flashcards"), "work:cards", "work", ""),
    (gettext_noop("Interview prep"), "work:prep", "work", ""),
    (gettext_noop("Exam notes"), "work:exam", "work", ""),
    (gettext_noop("Habits"), "work:habits", "work", ""),
]


def _money(value):
    from apps.core.templatetags.ui import money

    return money(value)


# ── Personal ledgers ────────────────────────────────────────────────────────

def _personal(user, text):
    from apps.contributors.models import Contributor
    from apps.creditors.models import Creditor
    from apps.debtors.models import Debtor
    from apps.expense.models import Expense
    from apps.goals.models import SavingsGoal
    from apps.household.models import HouseholdMember
    from apps.income.models import IncomeSource
    from apps.shops.models import Shop

    people = Group(_("People & shops"))
    for model, kind, url_name, icon in ((Creditor, _("Creditor — you owe them"), "creditor_detail", "arrow-down"),
                                        (Debtor, _("Debtor — they owe you"), "debtor_detail", "arrow-up"),
                                        (Shop, _("Shop"), "shop_detail", "cart"),
                                        (Contributor, _("Contributor"), "contributor_detail", "users"),
                                        (HouseholdMember, _("Household member"), "household_member_detail", "users")):
        for o in model.objects.filter(_q(text, "name", "phone", "note"), user=user).order_by("name")[:PER_GROUP]:
            people.hits.append(Hit(o.name, " · ".join(x for x in (kind, o.phone or "") if x), _url(url_name, o.pk), icon))

    from apps.wallets.models import Wallet

    other = Group(_("Income, spending & goals"))
    for w in Wallet.objects.filter(_q(text, "name", "number"), user=user)[:PER_GROUP]:
        other.hits.append(Hit(w.name, " · ".join(x for x in (_("Wallet"), w.number) if x), _url("wallet_detail", w.pk), "wallet"))
    for s in IncomeSource.objects.filter(_q(text, "name", "description"), user=user)[:PER_GROUP]:
        other.hits.append(Hit(s.name, _("Income source"), _url("income_source_detail", s.pk), "arrow-down"))
    for g in SavingsGoal.objects.filter(_q(text, "name", "note"), user=user)[:PER_GROUP]:
        other.hits.append(Hit(g.name, _("Savings goal"), _url("goal_detail", g.pk), "flag"))
    for e in Expense.objects.filter(_q(text, "note", "category__name"), user=user).select_related("category").order_by("-date")[:PER_GROUP]:
        other.hits.append(Hit(f"{e.category} · {_money(e.amount)}", " · ".join(x for x in (_("Expense"), f"{e.date:%d %b %Y}", (e.note or "")[:60]) if x),
                              _url("expense_edit", e.pk), "arrow-up"))
    return [people, other]


# ── Farm business ───────────────────────────────────────────────────────────

def _business(request, text):
    from apps.business.core.access import active_membership, can

    m = active_membership(request)
    if m is None:
        return []
    b, money = m.business, can(m, "view_finance")
    farm = Group(_("Farm: %(name)s") % {"name": b.name})

    def add(title, meta, url, icon):
        if url:
            farm.hits.append(Hit(title, meta, url, icon))

    from apps.business.parties.models import Party
    from apps.business.ponds.models import Pond

    for p in Pond.objects.filter(_q(text, "name", "code", "location", "lease_from"), business=b)[:PER_GROUP]:
        add(p.name, _("Pond"), _url("business:pond_detail", p.pk), "fish")
    for p in Party.objects.filter(_q(text, "name", "phone", "contact_person", "address"), business=b)[:PER_GROUP]:
        role = ", ".join(str(x) for x in (_("Supplier") if p.is_supplier else "", _("Buyer") if p.is_buyer else "") if x)
        url = _url("business:party_statement", p.pk) if money else _url("business:suppliers" if p.is_supplier else "business:buyers", query=f"?q={p.name}")
        add(p.name, " · ".join(x for x in (role, p.phone) if x), url, "truck" if p.is_supplier else "users")
    if apps.is_installed("apps.business.sales"):
        from apps.business.sales.models import FishSale

        for s in (FishSale.objects.filter(_q(text, "memo_no", "buyer__name", "notes"), business=b)
                  .select_related("buyer", "market").order_by("-date")[:PER_GROUP]):
            who = s.buyer or s.market or _("Cash sale")
            add(f"{who}" + (f" · #{s.memo_no}" if s.memo_no else ""), " · ".join(x for x in (_("Fish sale"), f"{s.date:%d %b %Y}", _money(s.net) if money else "") if x),
                _url("business:sale_detail", s.pk), "cart")
    if apps.is_installed("apps.business.assets"):
        from apps.business.assets.models import Equipment

        for e in Equipment.objects.filter(_q(text, "name", "notes"), business=b)[:PER_GROUP]:
            add(e.name, _("Equipment"), _url("business:equipment_detail", e.pk), "cog")
    if apps.is_installed("apps.business.supplies"):
        from apps.business.supplies.models import SupplyItem

        for i in SupplyItem.objects.filter(_q(text, "name", "notes"), business=b)[:PER_GROUP]:
            add(i.name, _("Pond supply"), _url("business:supply_detail", i.pk), "dropper")
    if apps.is_installed("apps.business.calendar"):
        from apps.business.calendar.models import CalendarEvent

        for ev in CalendarEvent.objects.filter(_q(text, "title", "notes"), business=b).order_by("-date")[:PER_GROUP]:
            add(ev.title, " · ".join((_("Calendar"), f"{ev.date:%d %b %Y}")), _url("business:calendar", query=f"?day={ev.date.isoformat()}"), "calendar")
    if apps.is_installed("apps.business.papers") and can(m, "manage_settings"):
        from apps.business.papers.models import FarmPaper

        for p in FarmPaper.objects.filter(_q(text, "title", "number", "issued_by"), business=b)[:PER_GROUP]:
            add(p.title, " · ".join(x for x in (_("Farm paper"), p.number) if x), _url("business:papers_edit", p.pk), "note")
    if money:
        if apps.is_installed("apps.business.staff"):
            from apps.business.staff.models import Worker

            for w in Worker.objects.filter(_q(text, "name", "phone", "job"), business=b)[:PER_GROUP]:
                add(w.name, " · ".join(x for x in (_("Worker"), w.job, w.phone) if x), _url("business:staff_worker", w.pk), "users")
        if apps.is_installed("apps.business.partners"):
            from apps.business.partners.models import Partner

            for p in Partner.objects.filter(_q(text, "name", "phone"), business=b)[:PER_GROUP]:
                add(p.name, _("Partner"), _url("business:partner_detail", p.pk), "group")
        from apps.business.loans.models import Lender

        for l in Lender.objects.filter(_q(text, "name"), business=b)[:PER_GROUP]:
            add(l.name, _("Lender"), _url("business:loans", query=f"?q={l.name}"), "banknotes")
        from apps.business.finance.models import Transaction

        for t in (Transaction.objects.filter(_q(text, "description", "notes", "party__name"), business=b)
                  .select_related("category").order_by("-date")[:PER_GROUP]):
            add(f"{t.category} · {_money(t.amount)}", " · ".join(x for x in (_("Money in & out"), f"{t.date:%d %b %Y}", t.description) if x),
                _url("business:transaction_edit", t.pk), "wallet")
    return [farm]


def _work(user, text):
    """Productivity: the person's own tasks, notes, diagrams, flashcards, exam notes, goals and learning."""
    from apps.productivity.models import Card, Diagram, ExamNote, Goal, LearningItem, Note, Task

    group = Group(_("Productivity"))
    for t in Task.objects.filter(_q(text, "title", "link"), owner=user).order_by("status", "-updated_at")[:PER_GROUP]:
        group.hits.append(Hit(t.title, " · ".join((_("Task"), t.get_status_display())), _url("work:task", t.pk), "check"))
    for n in Note.objects.filter(_q(text, "title", "body"), owner=user, is_archived=False)[:4]:
        group.hits.append(Hit(n.display_title, _("Note"), _url("work:note", n.pk), "note"))
    for dg in Diagram.objects.filter(_q(text, "title", "notes"), owner=user, is_archived=False).only("pk", "title", "kind")[:3]:
        group.hits.append(Hit(dg.title, " · ".join((_("Diagram"), dg.get_kind_display())), _url("work:diagram", dg.pk), "diagram"))
    for c in Card.objects.filter(_q(text, "front", "back"), owner=user).select_related("deck")[:3]:
        group.hits.append(Hit(" ".join(c.front.split())[:120], " · ".join((_("Flashcard"), c.deck.name)), _url("work:deck", c.deck_id), "cards"))
    for x in ExamNote.objects.filter(_q(text, "question", "answer"), owner=user).select_related("subject")[:3]:
        group.hits.append(Hit(" ".join(x.question.split())[:120], " · ".join((_("Exam notes"), x.subject.name)), _url("work:exam_subject", x.subject_id, query=f"#q{x.pk}"), "exam"))
    for g in Goal.objects.filter(_q(text, "title"), owner=user)[:3]:
        group.hits.append(Hit(g.title, _("Goal"), _url("work:goal", g.pk), "flag"))
    for item in LearningItem.objects.filter(_q(text, "title", "author"), owner=user)[:3]:
        group.hits.append(Hit(item.title, " · ".join(x for x in (_("Learning"), item.author) if x), _url("work:learning_edit", item.pk), "book"))
    return [group]


def _pages(request, text, personal, business, work=False):
    from apps.business.core.access import active_membership, can

    m = active_membership(request) if business else None
    group = Group(_("Pages"))
    low = text.lower()
    for title, name, area, cap in PAGES:
        if (area == "personal" and not personal) or (area == "business" and m is None) or (area == "work" and not work) \
                or (cap and not can(m, cap)):
            continue
        shown = _(title)
        if low in title.lower() or low in shown.lower():       # English or the page's name in Bangla
            url = _url(name)
            if url:
                where = {"business": _("Farm"), "work": _("Productivity")}.get(area, _("Personal"))
                group.hits.append(Hit(shown, where, url, "arrow-right"))
    return group


def search(request, text):
    from apps.business.core.access import BUSINESS, PERSONAL, has_dashboard

    text = (text or "").strip().translate(BN_DIGITS)
    if len(text) < MIN_LENGTH:
        return text, []
    from apps.productivity.access import can_use as can_use_work

    personal, business = has_dashboard(request.user, PERSONAL), has_dashboard(request.user, BUSINESS)
    work = can_use_work(request.user)
    groups = [_pages(request, text, personal, business, work)]
    if personal:
        groups += _personal(request.user, text)
    if business:
        groups += _business(request, text)
    if work:
        groups += _work(request.user, text)
    return text, [g for g in groups if g.hits]


@login_required
def search_view(request):
    text, groups = search(request, request.GET.get("q", ""))
    template = "core/search_results.html" if request.headers.get("HX-Request") else "core/search.html"
    return render(request, template, {"q": text, "groups": groups, "too_short": 0 < len(text) < MIN_LENGTH,
                                      "count": sum(len(g.hits) for g in groups)})
