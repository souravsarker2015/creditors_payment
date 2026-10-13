"""Spending more than usual: the expense categories (and bazar) where this
month is running well ahead of what you normally spend.

"Usual" is the average of the last three whole months up to the same day of
the month, so a bill paid on the 1st every month (rent, school fees) is in
the usual figure too and never looks like a jump. A category needs spending
in at least two of those months to have a usual at all — a one-off isn't a
habit — and must be clearly ahead, by ratio and by amount, to be shown.
"""
import calendar
from dataclasses import dataclass
from decimal import Decimal
from urllib.parse import urlencode

from django.db.models import Q, Sum
from django.urls import reverse
from django.utils.translation import gettext as _

from apps.core.stats import month_start

ZERO = Decimal(0)
MONTHS = 3
MIN_MONTHS = 2          # months (of MONTHS) with spending, to have a usual
RATIO = Decimal("1.4")  # this far ahead of usual…
MIN_EXTRA = Decimal(1000)  # …and at least this much more, in taka
SHOW = 4


@dataclass
class Jump:
    key: str
    name: str
    so_far: Decimal          # this month, up to today
    usual_by_now: Decimal    # the usual by this day of the month
    usual_month: Decimal     # a usual whole month
    url: str
    budget_url: str = ""     # set a budget for it, when it has none

    @property
    def extra(self):
        return self.so_far - self.usual_by_now

    @property
    def pct(self):
        return int((self.so_far / self.usual_by_now - 1) * 100) if self.usual_by_now else 0

    @property
    def change_text(self):
        """+66%, or ×4 once it's several times the usual (as Home shows changes)."""
        if self.usual_by_now and self.so_far >= self.usual_by_now * 3:
            return f"×{int(self.so_far / self.usual_by_now)}"
        return f"+{self.pct}%"

    @property
    def past_month(self):
        """Already more than a whole usual month."""
        return self.so_far > self.usual_month


def _totals(qs, field, spans):
    """{key: {span label: total}} in one query: per category when `field` is
    set, else one "bazar" line."""
    sums = {label: Sum("amount", filter=Q(date__gte=start, date__lte=end)) for label, start, end in spans}
    qs = qs.filter(date__gte=min(s for _l, s, _e in spans))
    if field is None:
        return {"bazar": qs.aggregate(**sums)}
    return {(r[field] if r[field] is not None else "none"): r for r in qs.values(field).annotate(**sums)}


def _month_end(m):
    return m.replace(day=calendar.monthrange(m.year, m.month)[1])


def jumps(user, today):
    from apps.budgets.models import Budget, BudgetScope
    from apps.expense.models import Expense, ExpenseCategory
    from apps.household.models import Purchase

    this_month = today.replace(day=1)
    past = [month_start(today, -i) for i in range(1, MONTHS + 1)]
    spans = [("now", this_month, today)]
    for i, m in enumerate(past):
        spans += [(f"by_now{i}", m, min(_month_end(m), m.replace(day=1) + (today - this_month))), (f"month{i}", m, _month_end(m))]
    series = _totals(Expense.objects.filter(user=user), "category_id", spans)
    series.update(_totals(Purchase.objects.filter(user=user), None, spans))

    budgeted = set(Budget.objects.filter(user=user, scope=BudgetScope.CATEGORY).values_list("category_id", flat=True))
    bazar_budget = Budget.objects.filter(user=user, scope=BudgetScope.BAZAR).exists()
    names = dict(ExpenseCategory.objects.filter(user=user).values_list("pk", "name"))
    out = []
    for key, s in series.items():
        s = {k: v or ZERO for k, v in s.items()}
        months = [s.get(f"month{i}", ZERO) for i in range(MONTHS)]
        if sum(1 for m in months if m > 0) < MIN_MONTHS:
            continue
        so_far = s.get("now", ZERO)
        by_now = sum((s.get(f"by_now{i}", ZERO) for i in range(MONTHS)), ZERO) / MONTHS
        usual = sum(months, ZERO) / MONTHS
        if so_far < by_now * RATIO or so_far - by_now < MIN_EXTRA:
            continue
        if key == "bazar":
            name, url = _("Bazar"), reverse("household_list")
            budget_url = "" if bazar_budget else reverse("budget_create") + "?" + urlencode({"scope": BudgetScope.BAZAR, "amount": int(usual)})
        else:
            name = names.get(key) if key != "none" else _("No category")
            if name is None:
                continue
            query = {"date_from": this_month.isoformat()}
            if key != "none":
                query["category"] = key
            url = reverse("expense_list") + "?" + urlencode(query)
            budget_url = "" if key == "none" or key in budgeted else \
                reverse("budget_create") + "?" + urlencode({"category": key, "amount": int(usual)})
        out.append(Jump(str(key), name, so_far, by_now.quantize(Decimal(1)), usual.quantize(Decimal(1)), url, budget_url))
    out.sort(key=lambda j: -j.extra)
    return out[:SHOW]
