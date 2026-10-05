from datetime import date, timedelta
from decimal import Decimal

from django.contrib import messages
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.formats import date_format
from django.utils.translation import gettext as _g, gettext_lazy as _
from django.views.decorators.http import require_POST

from apps.business.core.crud import Master
from apps.business.core.decorators import business_access_required
from apps.business.core.templatetags.business import bdt

from . import services
from .forms import EarningForm, PaymentForm, WorkerForm, WorkSheetDayForm
from .models import Earning, EarningKind, PayType, Worker, WorkerPayment

ZERO = Decimal(0)


def _decorate(objects, business):
    bal = services.balances(business)
    for w in objects:
        w.balance = bal.get(w.pk, w.opening_balance)


staff = Master(
    name="staff", model=Worker, form_class=WorkerForm,
    title=_("Staff & wages"), subtitle=_("The people who work on the farm: what each one earns, what you've paid, and who holds an advance."),
    add_label=_("Add worker"), row_template="business/staff/row.html", icon="users",
    view_cap="view_finance", edit_cap="view_finance", search_fields=("name", "job", "phone"),
    decorate=_decorate, nav_template="business/staff/tabs.html",
    filters=[("monthly", _("Monthly"), Q(pay_type=PayType.MONTHLY)), ("daily", _("Daily"), Q(pay_type=PayType.DAILY)),
             ("left", _("Left"), Q(left_on__lt=date.today()))],
    empty_title=_("No workers yet"), empty_text=_("Add the guard, feeders and others you pay. Each gets a khata: what they earned, what you paid, and any advance."),
    note=(_("How staff pay works"),
          _("Each worker has a khata: what they earned minus what you paid them. The balance shows whether you still owe them, or they hold an advance."),
          _("Daily workers: mark who worked on the Work sheet. Monthly staff: write the month's salary from the Salary sheet, usually at the end of the month."),
          _("Wages count as the farm's labour cost in reports — and in a pond's cost when you pick the pond. Don't also add them in Money in & out."),
          _("An advance is simply a payment made before the work is done: it's taken off what they earn later.")),
)


def _worker(request, pk):
    return get_object_or_404(Worker.all_objects, pk=pk, business=request.business)


@business_access_required(capability="view_finance")
def worker_detail_view(request, pk):
    worker = _worker(request, pk)
    lines = services.khata(worker)
    bal = lines[-1].balance if lines else worker.opening_balance
    year_ago = date.today() - timedelta(days=365)
    return render(request, "business/staff/worker_detail.html", {
        "worker": worker, "lines": list(reversed(lines)), "balance": bal,
        "earned_year": sum((l.earned for l in lines if l.date >= year_ago), ZERO),
        "paid_year": sum((l.paid for l in lines if l.date >= year_ago), ZERO),
        "salary_missing": worker.is_monthly and not worker.is_deleted and _salary_missing(worker),
    })


def _salary_missing(worker):
    """The latest finished month they worked, if its salary isn't written yet."""
    last_month = (date.today().replace(day=1) - timedelta(days=1)).replace(day=1)
    if not worker.works_on(last_month) and not worker.works_on(last_month.replace(day=28)):
        return None
    if Earning.objects.filter(worker=worker, kind=EarningKind.SALARY, month=last_month).exists():
        return None
    return last_month


def _back(worker):
    return redirect("business:staff_worker", worker.pk)


@business_access_required(capability="view_finance")
def earning_form_view(request, pk=None, worker_pk=None):
    obj = get_object_or_404(Earning, pk=pk, business=request.business) if pk else None
    worker = obj.worker if obj else _worker(request, worker_pk)
    initial = {}
    if not obj and request.GET.get("kind") in EarningKind.values:
        initial["kind"] = request.GET["kind"]
    if not obj and request.GET.get("month"):
        try:
            month = date.fromisoformat(request.GET["month"] + "-01")
            initial.update(kind=EarningKind.SALARY, date=_month_end(month), amount=format(worker.salary_for(month).normalize(), "f"))
        except ValueError:
            pass
    form = EarningForm(request.POST or None, instance=obj, business=request.business, worker=worker, initial=initial or None)
    if request.method == "POST" and form.is_valid():
        e = form.save(commit=False)
        e.business, e.worker = request.business, worker
        e.save()
        messages.success(request, _g("Saved. %(name)s's balance is now %(balance)s.") % {"name": worker, "balance": bdt(services.balance(worker))})
        return _back(worker)
    return render(request, "business/staff/form.html", {"form": form, "worker": worker, "obj": obj,
                                                        "title": _g("Edit earning") if obj else _g("Add to %(name)s's pay") % {"name": worker}})


@business_access_required(capability="view_finance")
def payment_form_view(request, pk=None, worker_pk=None):
    obj = get_object_or_404(WorkerPayment, pk=pk, business=request.business) if pk else None
    worker = obj.worker if obj else _worker(request, worker_pk)
    owed = services.balance(worker)
    initial = {"kind": request.GET["kind"]} if not obj and request.GET.get("kind") in ("wage", "advance") else None
    form = PaymentForm(request.POST or None, instance=obj, business=request.business, worker=worker, owed=owed, initial=initial)
    if request.method == "POST" and form.is_valid():
        p = form.save(commit=False)
        p.business, p.worker = request.business, worker
        p.save()
        now = services.balance(worker)
        if now < 0:
            messages.success(request, _g("Paid %(amount)s to %(name)s. They now hold an advance of %(adv)s.") % {"amount": bdt(p.amount), "name": worker, "adv": bdt(-now)})
        else:
            messages.success(request, _g("Paid %(amount)s to %(name)s. Still owed: %(owed)s.") % {"amount": bdt(p.amount), "name": worker, "owed": bdt(now)})
        return _back(worker)
    return render(request, "business/staff/form.html", {"form": form, "worker": worker, "obj": obj, "owed": owed, "is_payment": True,
                                                        "title": _g("Edit payment") if obj else _g("Pay %(name)s") % {"name": worker}})


@business_access_required(capability="delete")
@require_POST
def entry_delete_view(request, kind, pk):
    model = Earning if kind == "earning" else WorkerPayment
    obj = get_object_or_404(model, pk=pk, business=request.business)
    obj.soft_delete()
    messages.success(request, _g("Deleted."))
    return _back(obj.worker)


# ── Work sheet: who worked today ────────────────────────────────────────────

@business_access_required(capability="enter_data")
def work_sheet_view(request):
    """Tick who worked on a day (full or half day) — for daily-wage workers. Writes their wages."""
    from apps.business.core.access import can

    b = request.business
    raw = request.POST.get("date") or request.GET.get("date") or date.today().isoformat()
    day_form = WorkSheetDayForm({"date": raw})
    day = day_form.cleaned_data["date"] if day_form.is_valid() else date.today()
    workers = [w for w in Worker.objects.filter(business=b, pay_type=PayType.DAILY) if w.works_on(day)]
    done = {e.worker_id: e for e in Earning.objects.filter(business=b, kind=EarningKind.WORK, date=day, worker__in=workers)}
    from apps.business.ponds.models import CultureCycle, CycleStatus

    cycles = list(CultureCycle.objects.filter(business=b, status=CycleStatus.RUNNING).select_related("pond"))
    if request.method == "POST" and day_form.is_valid():
        valid_cycles = {str(c.pk): c for c in cycles}
        saved = 0
        with transaction.atomic():
            for w in workers:
                try:
                    days = Decimal(request.POST.get(f"d{w.pk}", "0"))
                except ArithmeticError:
                    days = ZERO
                days = min(max(days, ZERO), Decimal(1))
                cycle = valid_cycles.get(request.POST.get(f"c{w.pk}", ""))
                e = done.get(w.pk)
                if days == 0:
                    if e:
                        e.soft_delete()
                    continue
                if e is None:
                    e = Earning(business=b, worker=w, kind=EarningKind.WORK, date=day, rate=w.rate)
                e.days, e.cycle = days, cycle
                e.save()
                saved += 1
        messages.success(request, _g("Work sheet saved for %(date)s: %(n)s worked.") % {"date": date_format(day, "j M Y"), "n": saved})
        return redirect(reverse("business:staff_work") + f"?date={day.isoformat()}")
    rows = [{"w": w, "e": done.get(w.pk)} for w in workers]
    return render(request, "business/staff/work_sheet.html", {
        "day": day, "day_form": day_form, "rows": rows, "cycles": cycles,
        "prev": day - timedelta(days=1), "next": day + timedelta(days=1) if day < date.today() else None,
        "show_money": can(request.membership, "view_finance"),
        "total": sum((r["e"].amount for r in rows if r["e"]), ZERO),
    })


# ── Salary sheet: write a month's salaries ──────────────────────────────────

def _month_end(month):
    import calendar

    return month.replace(day=calendar.monthrange(month.year, month.month)[1])


def _default_month():
    """Last month, until all of its salaries are written; then this month."""
    return (date.today().replace(day=1) - timedelta(days=1)).replace(day=1)


@business_access_required(capability="view_finance")
def salary_sheet_view(request):
    from apps.business.finance.models import Account

    b = request.business
    try:
        month = date.fromisoformat((request.POST.get("month") or request.GET.get("month") or "") + "-01")
    except ValueError:
        month = _default_month()
    rows = services.salary_sheet(b, month)
    accounts = Account.objects.filter(business=b)
    if request.method == "POST":
        pay_too = request.POST.get("pay") == "1"
        account = accounts.filter(pk=request.POST.get("account") or 0).first()
        if pay_too and account is None:
            messages.error(request, _g("Choose the account the salaries are paid from."))
            return redirect(reverse("business:staff_salaries") + f"?month={month:%Y-%m}")
        written = paid = 0
        with transaction.atomic():
            for r in rows:
                if r.added or request.POST.get(f"w{r.worker.pk}") != "1":
                    continue
                try:
                    amount = Decimal(request.POST.get(f"a{r.worker.pk}") or r.amount)
                except ArithmeticError:
                    amount = r.amount
                if amount <= 0:
                    continue
                Earning.objects.create(business=b, worker=r.worker, kind=EarningKind.SALARY, date=_month_end(month), amount=amount)
                written += 1
                if pay_too:
                    owed = services.balance(r.worker)
                    if owed > 0:
                        WorkerPayment.objects.create(business=b, worker=r.worker, kind="wage", date=date.today(), amount=owed, account=account)
                        paid += 1
        if written:
            msg = _g("%(n)s salaries written for %(month)s.") % {"n": written, "month": date_format(month, "F Y")}
            if paid:
                msg += " " + _g("%(n)s paid from %(account)s.") % {"n": paid, "account": account}
            messages.success(request, msg)
        else:
            messages.info(request, _g("Nothing to write: tick the workers to add."))
        return redirect(reverse("business:staff_salaries") + f"?month={month:%Y-%m}")
    prev = (month - timedelta(days=1)).replace(day=1)
    nxt = (_month_end(month) + timedelta(days=1))
    return render(request, "business/staff/salary_sheet.html", {
        "month": month, "rows": rows, "accounts": accounts,
        "default_account": accounts.filter(is_default=True).first(),
        "prev": prev, "next": nxt if nxt <= date.today() else None,
        "to_write": [r for r in rows if not r.added and r.amount > 0],
        "written_total": sum((r.added.amount for r in rows if r.added), ZERO),
    })
