from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.formats import date_format
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.core.templatetags.ui import money
from apps.trash.undo import delete_with_undo

from . import services
from .forms import PlanForm
from .models import InstallmentPlan


def _party(request, kind, pk):
    from apps.creditors.models import Creditor
    from apps.debtors.models import Debtor
    from apps.shops.models import Shop

    model, detail = {"creditor": (Creditor, "creditor_detail"), "debtor": (Debtor, "debtor_detail"), "shop": (Shop, "shop_detail")}.get(kind, (None, None))
    if model is None:
        raise Http404
    return get_object_or_404(model, pk=pk, user=request.user), reverse(detail, args=[pk])


@login_required
def plan_form_view(request, kind, pk):
    party, back = _party(request, kind, pk)
    plan = getattr(party, "plan", None)
    remaining = services._ledger(plan)[1] if plan else _remaining(kind, party)
    initial = {}
    if plan is None:
        initial = {"start_date": services.add_months(date.today(), 1)}
    form = PlanForm(request.POST or None, instance=plan, initial=initial, remaining=remaining)
    if request.method == "POST" and form.is_valid():
        p = form.save(commit=False)
        p.user = request.user
        setattr(p, kind, party)
        p.save()
        st = services.sync_due_date(p)
        messages.success(request, _("Plan saved: %(amount)s %(how)s, %(n)s installments, the last on %(date)s.") % {
            "amount": money(p.amount), "how": p.get_frequency_display().lower(), "n": st.count, "date": date_format(st.last_date, "j M Y")})
        return redirect(back)
    return render(request, "plans/form.html", {"form": form, "party": party, "kind": kind, "plan": plan, "back": back, "remaining": remaining})


def _remaining(kind, party):
    from django.db.models import Sum

    out_type, back_type = {"creditor": ("BORROW", "REPAY"), "debtor": ("LEND", "RECEIVE"), "shop": ("PURCHASE", "PAYMENT")}[kind]
    tx = party.transactions
    total = lambda t: tx.filter(transaction_type=t).aggregate(s=Sum("amount"))["s"] or 0
    return total(out_type) - total(back_type)


@login_required
@require_POST
def plan_delete_view(request, kind, pk):
    party, back = _party(request, kind, pk)
    plan = getattr(party, "plan", None)
    if plan is None:
        raise Http404
    delete_with_undo(request, plan, _("Installment plan removed. The due date stays as it was."),
                     label=f"{party.name} · {money(plan.amount)} {plan.get_frequency_display()}", back_url=back)
    return redirect(back)
