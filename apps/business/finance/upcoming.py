"""Upcoming money on the farm: loan instalments, regular bills and income,
baki people promised to pay (or that you promised), and wages — against the
money in the accounts."""
import calendar
from datetime import date, timedelta
from decimal import Decimal

from django.apps import apps
from django.urls import reverse
from django.utils.translation import gettext as _

from apps.core.forecast import Item, build, repeat

from . import services
from .models import CategoryType, RecurringTransaction

ZERO = Decimal(0)


def _installed(label):
    return apps.is_installed(f"apps.business.{label}")


def loan_items(business, today, until):
    if not _installed("loans"):
        return []
    from apps.business.loans.services import loans_for

    items = []
    for loan in loans_for(business, closed=False):
        url = reverse("business:loan_detail", args=[loan.pk])
        for p in loan.schedule(today).periods:
            if p.due > until:
                break
            if p.remaining > 0:
                detail = _("Loan instalment") + (f" · {loan.lender}" if loan.name else "")   # the title is the lender's name otherwise
                items.append(Item(p.due, -p.remaining, loan.title, detail, url, "loan"))
    return items


def bill_items(business, today, until):
    """Regular bills and regular income ("Regular bills" page), every time they come round."""
    items = []
    for r in RecurringTransaction.objects.filter(business=business, next_due__isnull=False).select_related("category"):
        sign = 1 if r.category.type == CategoryType.INCOME else -1
        detail = _("Regular income") if sign > 0 else _("Regular bill")
        for d in repeat(r.next_due, lambda x, rep=r.repeat: services.next_date(x, rep), until, r.end_date):
            items.append(Item(d, sign * r.amount, r.name, detail, reverse("business:recurring"), "bill"))
    return items


def baki_items(business, today, until):
    """Baki with a follow-up date: a buyer who promised to pay, or a supplier you promised."""
    if not _installed("credit"):
        return []
    from apps.business.credit.services import build as ledgers

    items = []
    for led in ledgers(business).values():
        when = led.party.follow_up_on
        if not when or not led.balance or when > until:
            continue
        url = reverse("business:party_statement", args=[led.party.pk])
        note = led.party.follow_up_note or (_("Promised to pay") if led.owes_me else _("You said you'd pay"))
        items.append(Item(when, led.balance, led.party.name, _("Baki") + f" · {note}", url, "baki"))
    return items


def wage_items(business, today, until):
    """Wages already owed, and monthly salaries at each month's end (unless written down already)."""
    if not _installed("staff"):
        return []
    from apps.business.staff.models import Earning, EarningKind, Worker
    from apps.business.staff.services import balances

    items = []
    owed = sum((v for v in balances(business).values() if v > 0), ZERO)
    if owed:
        items.append(Item(today, -owed, _("Wages still owed"), _("Staff & wages"), reverse("business:staff"), "wages"))
    workers = [w for w in Worker.objects.filter(business=business) if w.is_monthly]
    month = today.replace(day=1)
    while workers:
        last = month.replace(day=calendar.monthrange(month.year, month.month)[1])
        if last > until:
            break
        if last >= today:
            written = set(Earning.objects.filter(business=business, kind=EarningKind.SALARY, month=month).values_list("worker_id", flat=True))
            total = sum((w.salary_for(month) for w in workers if w.pk not in written), ZERO)
            if total:
                items.append(Item(last, -total, _("Monthly salaries"), _("Usually paid at the month's end"), reverse("business:staff"), "wages"))
        month = last + timedelta(days=1)
    return items


def forecast(business, today, days):
    until = today + timedelta(days=days)
    now = sum(services.balances(business).values(), ZERO)
    items = loan_items(business, today, until) + bill_items(business, today, until) + baki_items(business, today, until) + wage_items(business, today, until)
    return build(now, items, today, days)
