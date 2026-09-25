import math
from decimal import Decimal

from django.contrib import messages
from django.db.models import Sum
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.core.stats import month_start
from .forms import BudgetForm
from .models import Budget, BudgetScope
from .services import month_from_param, statuses


@login_required
def budget_list_view(request):
    today = timezone.localdate()
    month = month_from_param(request.GET.get("month"), today)
    rows = statuses(request.user, month, today)
    context = {
        "rows": rows,
        "month": month,
        "prev_month": month_start(month, -1),
        "next_month": month_start(month, 1) if month < today.replace(day=1) else None,
        "is_current": month == today.replace(day=1),
        "counts": {s: sum(1 for r in rows if r["state"] == s) for s in ("ok", "warn", "over")},
        "suggestions": _suggestions(request.user, today) if month == today.replace(day=1) else [],
    }
    return render(request, "budgets/budget_list.html", context)


def _suggestions(user, today, limit=3):
    """Budget ideas for the biggest categories that don't have one yet: the
    average of the last three full months, rounded up to a tidy ৳500 step."""
    start = month_start(today, -3)
    end = today.replace(day=1)
    budgeted = Budget.objects.filter(user=user, scope="category").values_list("category_id", flat=True)
    rows = (
        user.expenses.filter(date__gte=start, date__lt=end, category__isnull=False, category__is_active=True)
        .exclude(category_id__in=budgeted)
        .values("category_id", "category__name")
        .annotate(t=Sum("amount"))
        .order_by("-t")[:limit]
    )
    step = Decimal("500")
    return [
        {"category_id": r["category_id"], "name": r["category__name"], "average": r["t"] / 3,
         "amount": Decimal(math.ceil(r["t"] / 3 / step)) * step}
        for r in rows
    ]


def _form_view(request, budget=None):
    form = BudgetForm(request.POST or None, instance=budget, user=request.user)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.user = request.user
        obj.save()
        messages.success(request, _("Budget saved: %(name)s.") % {"name": obj.label})
        return redirect("budget_list")
    return render(request, "budgets/budget_form.html", {
        "form": form,
        "title": _("Edit Budget") if budget else _("New Budget"),
        "back": reverse("budget_list"),
    })


@login_required
def budget_create_view(request):
    if request.method == "GET":
        # Links can pre-fill the form: ?scope=bazar, or ?category=<id>&amount=<n>
        # from the "Suggested budgets" list.
        initial = {}
        if request.GET.get("scope") in BudgetScope.values:
            initial["scope"] = request.GET["scope"]
        if request.GET.get("category", "").isdigit():
            initial.update(scope=BudgetScope.CATEGORY, category=int(request.GET["category"]))
        if request.GET.get("amount", "").isdigit():
            initial["amount"] = int(request.GET["amount"])
        form = BudgetForm(initial=initial, user=request.user)
        return render(request, "budgets/budget_form.html", {"form": form, "title": _("New Budget"), "back": reverse("budget_list")})
    return _form_view(request)


@login_required
def budget_edit_view(request, pk):
    return _form_view(request, get_object_or_404(Budget, pk=pk, user=request.user))


@login_required
@require_POST
def budget_delete_view(request, pk):
    budget = get_object_or_404(Budget, pk=pk, user=request.user)
    name = budget.label
    budget.delete()
    messages.success(request, _("Budget removed: %(name)s.") % {"name": name})
    return redirect("budget_list")
