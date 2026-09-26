import csv
import json
from datetime import date
from decimal import Decimal

from django.contrib import messages
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.business.core.decorators import business_access_required
from apps.business.core.templatetags.business import bdt

from . import services
from .forms import CloseForm, LenderForm, LenderQuickForm, LoanForm, PaymentForm, RateChangeForm, TopUpForm
from .models import Lender, Loan, LoanRateChange, LoanTransaction, LoanTxnKind, frequency_label

FINANCE = "view_finance"


def _loan(request, pk, **extra):
    return get_object_or_404(Loan.objects.select_related("lender"), pk=pk, business=request.business, **extra)


# ── Loans ───────────────────────────────────────────────────────────────────

@business_access_required(capability=FINANCE)
def loan_list_view(request):
    b = request.business
    status = request.GET.get("status", "active")
    lender = Lender.all_objects.filter(business=b, pk=request.GET.get("lender")).first() if request.GET.get("lender", "").isdigit() else None
    summary = services.overview(b)
    if status == "closed":
        rows = [(loan, loan.schedule()) for loan in services.loans_for(b, closed=True, lender=lender)]
    elif status == "deleted":
        rows = [(loan, loan.schedule()) for loan in services.loans_for(b, deleted=True, lender=lender)]
    else:
        status = "active"
        rows = [(loan, s) for loan, s in summary["rows"] if not lender or loan.lender_id == lender.pk]
        # Overdue first, then by the next due date.
        rows.sort(key=lambda r: (not r[1].overdue_periods, r[1].next_due.due if r[1].next_due else date.max))
    return render(request, "business/loans/loan_list.html", {
        "rows": rows, "status": status, "summary": summary, "lender": lender,
        "counts": {
            "active": summary["count"],
            "closed": services.loans_for(b, closed=True).count(),
            "deleted": Loan.all_objects.filter(business=b, is_deleted=True).count(),
        },
    })


@business_access_required(capability=FINANCE)
def loan_form_view(request, pk=None):
    b = request.business
    loan = _loan(request, pk) if pk else None
    initial = {}
    if not loan and request.GET.get("lender", "").isdigit():
        initial["lender"] = request.GET["lender"]
    form = LoanForm(request.POST or None, instance=loan, business=b, initial=initial)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.business = b
        obj.save()
        messages.success(request, _("Loan saved. Its payment schedule is ready below.") if not loan else _("Loan updated — the schedule has been worked out again."))
        return redirect("business:loan_detail", obj.pk)
    return render(request, "business/loans/loan_form.html", {
        "form": form, "loan": loan,
        "lender_qa": {"url": reverse("business:lender_quick_add"), "title": _("New lender"), "noun": _("lender"),
                      "form": LenderQuickForm(prefix="qa_lender", business=b)},
    })


@business_access_required(capability=FINANCE)
@require_POST
def loan_preview_view(request):
    """Live preview for the loan form: the same engine as saved loans."""
    form = LoanForm(request.POST, business=request.business)
    form.fields["lender"].required = False
    if not form.is_valid():
        return JsonResponse({"ok": False, "errors": {k: [str(e) for e in v] for k, v in form.errors.items()}})
    d = form.cleaned_data
    terms = Loan(principal=d["principal"], taken_on=d["taken_on"], rate=d["rate"], rate_period=d["rate_period"],
                 method=d["method"], every=d["every"], every_unit=d["every_unit"], repayment=d["repayment"],
                 first_due=d["first_due"], maturity=d["maturity"]).terms()
    p = services.preview(terms)
    return JsonResponse({
        "ok": True,
        "count": p["count"],
        "frequency": frequency_label(d["every"], d["every_unit"]),
        "instalment": bdt(p["instalment"]),
        "interest": bdt(p["interest"]),
        "total": bdt(p["total"]),
        "open_ended": p["open_ended"],
        "first_due": p["first"].due.strftime("%-d %b %Y") if p["first"] else "",
        "last_due": p["last"].due.strftime("%-d %b %Y") if p["last"] else "",
        "rows": [{"due": r.due.strftime("%-d %b %Y"), "interest": bdt(r.interest), "principal": bdt(r.principal), "total": bdt(r.total)} for r in p["periods"]],
    })


@business_access_required(capability=FINANCE)
def loan_detail_view(request, pk):
    loan = get_object_or_404(Loan.all_objects.select_related("lender"), pk=pk, business=request.business)
    s = loan.schedule()
    txns = list(LoanTransaction.objects.filter(loan=loan).select_related("created_by"))
    nxt = s.next_due
    quick = [
        ("next", _("Next payment"), nxt.remaining if nxt else 0, nxt.interest_left if nxt else 0),
        ("overdue", _("Everything overdue"), s.overdue, sum((p.interest_left for p in s.overdue_periods), Decimal(0))),
        ("interest", _("Interest owed"), s.unpaid_interest, s.unpaid_interest),
        ("payoff", _("Settle the whole loan"), s.payoff, s.unpaid_interest),
    ]
    seen, chips = set(), []
    for key, label, amount, interest in quick:
        if amount and amount >= 1 and amount not in seen and not (key == "overdue" and len(s.overdue_periods) < 2):
            seen.add(amount)
            chips.append({"key": key, "label": label, "amount": str(amount), "interest": str(min(interest, amount)), "text": bdt(amount)})
    # Keep long schedules short: the last two paid rows and the next twelve.
    paid = [p for p in s.periods if p.status == "paid"]
    shown_paid = {p.no for p in paid[-2:]}
    unpaid = [p.no for p in s.periods if p.status != "paid"][:12]
    rows = [(p, p.no in shown_paid or p.no in unpaid) for p in s.periods]
    return render(request, "business/loans/loan_detail.html", {
        "loan": loan, "s": s, "txns": txns, "rows": rows, "hidden_rows": sum(1 for _, v in rows if not v),
        "rate_changes": list(loan.rate_changes.all()),
        "pay_form": PaymentForm(loan=loan, prefix="pay"),
        "topup_form": TopUpForm(loan=loan, prefix="top"),
        "rate_form": RateChangeForm(loan=loan, prefix="rate"),
        "close_form": CloseForm(initial={"closed_on": date.today()}),
        "chips": chips, "chips_json": json.dumps(chips),
        "interest_due_now": str(s.interest_due_now),
        "open_pay": request.GET.get("pay") == "1",
        "tab": request.GET.get("tab", "schedule"),
        "current_rate": s.periods[-1].rate if loan.closed_on and s.periods else next((p.rate for p in s.periods if p.is_current), None),
    })


@business_access_required(capability=FINANCE)
def txn_create_view(request, pk, kind):
    """Record a payment or extra borrowing. The detail page posts here from a
    popup; if something is wrong, this page shows the form with the errors."""
    loan = _loan(request, pk)
    form_class, prefix = (PaymentForm, "pay") if kind == LoanTxnKind.PAYMENT else (TopUpForm, "top")
    form = form_class(request.POST or None, loan=loan, prefix=prefix)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.business, obj.loan, obj.kind = request.business, loan, kind
        obj.save()
        loan.refresh_from_db()
        s = loan.schedule()
        if kind == LoanTxnKind.TOP_UP:
            messages.success(request, _("%(amount)s more borrowed. The schedule now includes it.") % {"amount": bdt(obj.principal)})
        elif s.is_paid_off and not loan.closed_on:
            messages.success(request, _("Payment of %(amount)s saved — the loan is fully paid! You can close it now.") % {"amount": bdt(obj.total)})
        else:
            messages.success(request, _("Payment of %(amount)s saved. Still owed: %(left)s.") % {"amount": bdt(obj.total), "left": bdt(s.outstanding)})
        return redirect(reverse("business:loan_detail", args=[loan.pk]) + "?tab=" + ("history" if kind == LoanTxnKind.TOP_UP else "schedule"))
    return render(request, "business/loans/txn_form.html", {"form": form, "loan": loan, "kind": kind})


@business_access_required(capability=FINANCE)
def txn_edit_view(request, pk):
    txn = get_object_or_404(LoanTransaction.objects.select_related("loan__lender"), pk=pk, business=request.business)
    form_class = PaymentForm if txn.kind == LoanTxnKind.PAYMENT else TopUpForm
    form = form_class(request.POST or None, instance=txn, loan=txn.loan)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("Saved. The schedule has been updated."))
        return redirect(reverse("business:loan_detail", args=[txn.loan_id]) + "?tab=history")
    return render(request, "business/loans/txn_form.html", {"form": form, "loan": txn.loan, "kind": txn.kind, "txn": txn})


@business_access_required(capability="delete")
@require_POST
def txn_delete_view(request, pk):
    txn = get_object_or_404(LoanTransaction, pk=pk, business=request.business)
    txn.soft_delete()
    messages.success(request, _("Entry deleted. The schedule has been updated."))
    return redirect(reverse("business:loan_detail", args=[txn.loan_id]) + "?tab=history")


@business_access_required(capability=FINANCE)
@require_POST
def pay_past_dues_view(request, pk):
    loan = _loan(request, pk)
    n = services.pay_past_dues(loan, paid_via=request.POST.get("paid_via") or "cash")
    messages.success(request, _("%(n)s past payments marked as paid on their due dates.") % {"n": n})
    return redirect("business:loan_detail", loan.pk)


@business_access_required(capability=FINANCE)
@require_POST
def rate_change_view(request, pk):
    loan = _loan(request, pk)
    form = RateChangeForm(request.POST, loan=loan, prefix="rate")
    if form.is_valid():
        obj = form.save(commit=False)
        obj.business, obj.loan = request.business, loan
        obj.save()
        messages.success(request, _("New rate %(rate)s%% from %(date)s. Interest from that day on uses it.") % {
            "rate": f"{obj.rate:g}", "date": obj.effective_from.strftime("%-d %b %Y")})
    else:
        messages.error(request, " ".join(e for errs in form.errors.values() for e in errs))
    return redirect(reverse("business:loan_detail", args=[loan.pk]) + "?tab=terms")


@business_access_required(capability=FINANCE)
@require_POST
def rate_change_delete_view(request, pk):
    change = get_object_or_404(LoanRateChange, pk=pk, business=request.business)
    change.soft_delete()
    messages.success(request, _("Rate change removed."))
    return redirect(reverse("business:loan_detail", args=[change.loan_id]) + "?tab=terms")


@business_access_required(capability=FINANCE)
@require_POST
def loan_close_view(request, pk):
    loan = _loan(request, pk)
    if loan.closed_on:
        loan.closed_on = None
        loan.save(update_fields=["closed_on", "updated_at", "updated_by"])
        messages.success(request, _("Loan reopened."))
    else:
        form = CloseForm(request.POST)
        loan.closed_on = form.cleaned_data["closed_on"] if form.is_valid() else date.today()
        loan.save(update_fields=["closed_on", "updated_at", "updated_by"])
        messages.success(request, _("Loan closed. It's kept under Closed with its full history."))
    return redirect("business:loan_detail", loan.pk)


@business_access_required(capability="delete")
@require_POST
def loan_delete_view(request, pk):
    loan = _loan(request, pk)
    loan.soft_delete()
    messages.success(request, _("“%(name)s” moved to Deleted. You can restore it any time.") % {"name": loan.title})
    return redirect("business:loans")


@business_access_required(capability="delete")
@require_POST
def loan_restore_view(request, pk):
    loan = get_object_or_404(Loan.all_objects, pk=pk, business=request.business, is_deleted=True)
    loan.restore()
    messages.success(request, _("“%(name)s” restored.") % {"name": loan.title})
    return redirect("business:loan_detail", loan.pk)


@business_access_required(capability=FINANCE)
def loan_schedule_csv_view(request, pk):
    loan = _loan(request, pk)
    s = loan.schedule()
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="loan-{loan.pk}-schedule.csv"'
    response.write("﻿")  # so Excel opens Bangla text correctly
    w = csv.writer(response)
    w.writerow([_("No."), _("Due date"), _("Interest"), _("Towards the loan"), _("Total"), _("Paid"), _("Left to pay"), _("Balance after"), _("Status")])
    labels = {"paid": _("Paid"), "overdue": _("Overdue"), "due_soon": _("Due soon"), "upcoming": _("Upcoming")}
    for p in s.periods:
        w.writerow([p.no, p.due.isoformat(), p.interest, p.principal, p.total, p.paid, p.remaining, p.balance_after, labels[p.status]])
    return response


# ── Lenders ─────────────────────────────────────────────────────────────────

@business_access_required(capability=FINANCE)
def lender_list_view(request):
    b = request.business
    show_deleted = request.GET.get("show") == "deleted"
    lenders = list(services.lenders_for(b, deleted=show_deleted))
    totals = services.lender_totals(b)
    for lender in lenders:
        lender.stats = totals.get(lender.pk, {"count": 0, "outstanding": 0})
    return render(request, "business/loans/lender_list.html", {
        "lenders": lenders, "show_deleted": show_deleted,
        "deleted_count": Lender.all_objects.filter(business=b, is_deleted=True).count(),
    })


@business_access_required(capability=FINANCE)
def lender_form_view(request, pk=None):
    b = request.business
    lender = get_object_or_404(Lender, pk=pk, business=b) if pk else None
    form = LenderForm(request.POST or None, instance=lender, business=b)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.business = b
        obj.save()
        messages.success(request, _("Lender saved: %(name)s.") % {"name": obj.name})
        return redirect("business:lenders")
    return render(request, "business/loans/lender_form.html", {"form": form, "lender": lender})


@business_access_required(capability=FINANCE)
@require_POST
def lender_quick_add_view(request):
    """The "+" beside the lender dropdown. Answers like the shared quick-add."""
    form = LenderQuickForm(request.POST, prefix="qa_lender", business=request.business)
    if not form.is_valid():
        return JsonResponse({"ok": False, "errors": {k: [str(e) for e in v] for k, v in form.errors.items()}}, status=400)
    with transaction.atomic():
        obj = form.save(commit=False)
        obj.business = request.business
        obj.save()
    return JsonResponse({"ok": True, "id": obj.pk, "name": obj.name, "message": _("“%(name)s” added and selected.") % {"name": obj.name}}, status=201)


@business_access_required(capability="delete")
@require_POST
def lender_delete_view(request, pk):
    lender = get_object_or_404(Lender, pk=pk, business=request.business)
    if Loan.objects.filter(lender=lender).exists():
        messages.error(request, _("%(name)s still has loans. Delete or move those first.") % {"name": lender.name})
    else:
        lender.soft_delete()
        messages.success(request, _("“%(name)s” moved to Deleted. You can restore it any time.") % {"name": lender.name})
    return redirect("business:lenders")


@business_access_required(capability="delete")
@require_POST
def lender_restore_view(request, pk):
    lender = get_object_or_404(Lender.all_objects, pk=pk, business=request.business, is_deleted=True)
    if Lender.objects.filter(business=request.business, name__iexact=lender.name).exists():
        messages.error(request, _("Another lender is already called “%(name)s”. Rename it first.") % {"name": lender.name})
    else:
        lender.restore()
        messages.success(request, _("“%(name)s” restored.") % {"name": lender.name})
    return redirect("business:lenders")
