from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from .forms import EntryForm, GoalForm
from .models import GoalEntry, SavingsGoal
from .services import TONES, goal_rows, last_12, monthly_net, progress, totals

STATUSES = ("active", "reached", "archived")


def _next(request, fallback):
    nxt = request.POST.get("next") or request.GET.get("next")
    if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
        return nxt
    return fallback


@login_required
def goal_list_view(request):
    status = request.GET.get("status", "active")
    if status not in STATUSES:
        status = "active"
    counts = {s: len(goal_rows(request.user, s)) for s in STATUSES}
    return render(request, "goals/goal_list.html", {
        "rows": goal_rows(request.user, status),
        "status": status,
        "counts": counts,
        "totals": totals(request.user),
        "entry_form": EntryForm(),
    })


def _goal_form(request, goal=None):
    form = GoalForm(request.POST or None, instance=goal)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.user = request.user
        obj.save()
        messages.success(request, _("Goal saved: %(name)s.") % {"name": obj.name})
        return redirect("goal_detail", pk=obj.pk)
    return render(request, "goals/goal_form.html", {
        "form": form,
        "title": _("Edit Goal") if goal else _("New Savings Goal"),
        "back": reverse("goal_detail", args=[goal.pk]) if goal else reverse("goal_list"),
    })


@login_required
def goal_create_view(request):
    return _goal_form(request)


@login_required
def goal_edit_view(request, pk):
    return _goal_form(request, get_object_or_404(SavingsGoal, pk=pk, user=request.user))


@login_required
def goal_detail_view(request, pk):
    goal = get_object_or_404(SavingsGoal, pk=pk, user=request.user)
    form = EntryForm(goal=goal)
    if request.method == "POST":
        form = EntryForm(request.POST, goal=goal)
        if form.is_valid():
            _save_entry(request, goal, form)
            return redirect(_next(request, reverse("goal_detail", args=[goal.pk])))
    info = progress(goal)
    info["tone"] = TONES[info["state"]]
    months = last_12()
    return render(request, "goals/goal_detail.html", {
        "goal": goal, "p": info, "form": form,
        "entries": goal.entries.all()[:100],
        "months": months, "monthly": monthly_net(goal, months),
    })


def _save_entry(request, goal, form):
    was_reached = goal.reached_at is not None
    entry = form.save(commit=False)
    entry.goal = goal
    entry.save()
    _sync_reached(goal)
    if goal.reached_at and not was_reached:
        messages.success(request, _("🎉 Goal reached: %(name)s! You saved the full %(amount)s.") % {
            "name": goal.name, "amount": f"৳{goal.target_amount:,.0f}"})
    elif entry.kind == GoalEntry.DEPOSIT:
        messages.success(request, _("৳%(amount)s added to %(name)s.") % {"amount": f"{entry.amount:,.0f}", "name": goal.name})
    else:
        messages.success(request, _("৳%(amount)s taken out of %(name)s.") % {"amount": f"{entry.amount:,.0f}", "name": goal.name})


def _sync_reached(goal):
    """Stamp the day a goal is reached; clear it if money is taken back out."""
    reached = progress(goal)["state"] == "reached"
    if reached and not goal.reached_at:
        goal.reached_at = timezone.localdate()
        goal.save(update_fields=["reached_at", "updated_at"])
    elif not reached and goal.reached_at:
        goal.reached_at = None
        goal.save(update_fields=["reached_at", "updated_at"])


@login_required
@require_POST
def entry_create_view(request, pk):
    """Quick "Add money" from the goals list."""
    goal = get_object_or_404(SavingsGoal, pk=pk, user=request.user)
    form = EntryForm(request.POST, goal=goal)
    if form.is_valid():
        _save_entry(request, goal, form)
    else:
        for errors in form.errors.values():
            for e in errors:
                messages.error(request, e)
    return redirect(_next(request, reverse("goal_list")))


@login_required
def entry_edit_view(request, pk):
    entry = get_object_or_404(GoalEntry, pk=pk, goal__user=request.user)
    goal = entry.goal
    form = EntryForm(request.POST or None, instance=entry, goal=goal)
    if request.method == "POST" and form.is_valid():
        form.save()
        _sync_reached(goal)
        messages.success(request, _("Entry updated."))
        return redirect("goal_detail", pk=goal.pk)
    return render(request, "goals/entry_form.html", {
        "form": form, "title": _("Edit Entry"), "back": reverse("goal_detail", args=[goal.pk]),
    })


@login_required
@require_POST
def entry_delete_view(request, pk):
    entry = get_object_or_404(GoalEntry, pk=pk, goal__user=request.user)
    goal = entry.goal
    entry.delete()
    _sync_reached(goal)
    messages.success(request, _("Entry deleted."))
    return redirect("goal_detail", pk=goal.pk)


@login_required
@require_POST
def goal_toggle_active_view(request, pk):
    goal = get_object_or_404(SavingsGoal, pk=pk, user=request.user)
    goal.is_active = not goal.is_active
    goal.save(update_fields=["is_active", "updated_at"])
    messages.success(request, (_("'%(name)s' is active again.") if goal.is_active else _("'%(name)s' archived. Its history is kept.")) % {"name": goal.name})
    return redirect(_next(request, reverse("goal_list")))


@login_required
@require_POST
def goal_delete_view(request, pk):
    goal = get_object_or_404(SavingsGoal, pk=pk, user=request.user)
    name = goal.name
    goal.delete()
    messages.success(request, _("Goal deleted: %(name)s.") % {"name": name})
    return redirect("goal_list")
