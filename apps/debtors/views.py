import csv
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse
import django.utils.timezone
from datetime import date as date_cls
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum, Q, F, DecimalField, Value
from django.db.models.functions import Coalesce
from django.utils.translation import gettext as _

from .models import Debtor, DebtorCategory, Transaction


def _csv_response(filename, header, rows):
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.write("\ufeff")  # UTF-8 BOM so Excel renders Bangla text correctly
    writer = csv.writer(response)
    writer.writerow(header)
    writer.writerows(rows)
    return response
from .forms import DebtorForm, TransactionForm

MONTH_CHOICES = [(i, date_cls(2000, i, 1)) for i in range(1, 13)]


def _parse_year_month(request):
    raw_year = request.GET.get("year", "").strip()
    year = int(raw_year) if raw_year.isdigit() else None
    raw_month = request.GET.get("month", "").strip()
    month = int(raw_month) if raw_month.isdigit() and 1 <= int(raw_month) <= 12 else None
    return year, month


@login_required
def dashboard_view(request):
    valid_filter_types = {"include", "exclude"}
    filter_type = request.GET.get("filter_type", "include").strip().lower()
    if filter_type not in valid_filter_types:
        filter_type = "include"

    selected_categories = [
        category
        for category in request.GET.getlist("category")
        if category in DebtorCategory.values
    ]

    debtors_base_qs = request.user.debtors.all()
    if selected_categories:
        if filter_type == "exclude":
            debtors_base_qs = debtors_base_qs.exclude(category__in=selected_categories)
        else:
            debtors_base_qs = debtors_base_qs.filter(category__in=selected_categories)

    # Global summary stats for the current user
    stats = debtors_base_qs.aggregate(
        total_lent=Coalesce(
            Sum(
                "transactions__amount",
                filter=Q(transactions__transaction_type=Transaction.LEND),
            ),
            Value(0, output_field=DecimalField()),
        ),
        total_received=Coalesce(
            Sum(
                "transactions__amount",
                filter=Q(transactions__transaction_type=Transaction.RECEIVE),
            ),
            Value(0, output_field=DecimalField()),
        ),
    )
    
    total_lent = stats["total_lent"]
    total_received = stats["total_received"]
    remaining = total_lent - total_received
    
    # Debtor-wise breakdown for charts
    debtors_qs = debtors_base_qs.annotate(
        d_lent=Coalesce(Sum("transactions__amount", filter=Q(transactions__transaction_type=Transaction.LEND)), Value(0, output_field=DecimalField())),
        d_received=Coalesce(Sum("transactions__amount", filter=Q(transactions__transaction_type=Transaction.RECEIVE)), Value(0, output_field=DecimalField())),
    )
    
    debtor_labels = []
    debtor_remaining = []
    debtor_received = []
    
    for d in debtors_qs:
        rem = d.d_lent - d.d_received
        if d.d_lent > 0 or d.d_received > 0:
            debtor_labels.append(d.name)
            debtor_remaining.append(float(rem) if rem > 0 else 0)
            debtor_received.append(float(d.d_received))

    # Recent activity
    recent_transactions = Transaction.objects.filter(debtor__user=request.user)
    if selected_categories:
        if filter_type == "exclude":
            recent_transactions = recent_transactions.exclude(
                debtor__category__in=selected_categories
            )
        else:
            recent_transactions = recent_transactions.filter(
                debtor__category__in=selected_categories
            )
    recent_transactions = recent_transactions.select_related("debtor").order_by(
        "-date", "-created_at"
    )[:10]
    
    context = {
        "total_lent": total_lent,
        "total_received": total_received,
        "remaining": remaining,
        "debtor_labels": debtor_labels,
        "debtor_remaining": debtor_remaining,
        "debtor_received": debtor_received,
        "recent_transactions": recent_transactions,
        "selected_categories": selected_categories,
        "category_choices": DebtorCategory.choices,
        "filter_type": filter_type,
    }
    return render(request, "debtors/dashboard.html", context)


@login_required
def debtor_create_view(request):
    if request.method == "POST":
        form = DebtorForm(request.POST)
        if form.is_valid():
            debtor = form.save(commit=False)
            debtor.user = request.user
            debtor.save()
            messages.success(request, _("Debtor '%(name)s' added successfully.") % {"name": debtor.name})
            return redirect("debtor_list")
    else:
        form = DebtorForm()
    return render(request, "debtors/debtor_form.html", {"form": form, "title": _("Add New Debtor")})


@login_required
def debtor_edit_view(request, pk):
    debtor = get_object_or_404(Debtor, pk=pk, user=request.user)
    if request.method == "POST":
        form = DebtorForm(request.POST, instance=debtor)
        if form.is_valid():
            form.save()
            messages.success(request, _("Debtor '%(name)s' updated successfully.") % {"name": debtor.name})
            return redirect("debtor_list")
    else:
        form = DebtorForm(instance=debtor)
    return render(request, "debtors/debtor_form.html", {"form": form, "title": _("Edit %(name)s") % {"name": debtor.name}})


@login_required
def debtor_detail_view(request, pk):
    debtor = get_object_or_404(Debtor, pk=pk, user=request.user)
    all_transactions = debtor.transactions.all()

    if request.method == "POST":
        form = TransactionForm(request.POST)
        if form.is_valid():
            transaction = form.save(commit=False)
            transaction.debtor = debtor
            transaction.save()
            messages.success(request, _("Transaction of ৳%(amount)s added.") % {"amount": transaction.amount})
            return redirect("debtor_detail", pk=pk)
    else:
        form = TransactionForm(initial={"date": django.utils.timezone.now().date()})

    # Calculate all-time totals for this specific debtor (never period-filtered —
    # outstanding balance only makes sense as a current, running snapshot).
    stats = all_transactions.aggregate(
        lent=Coalesce(Sum("amount", filter=Q(transaction_type=Transaction.LEND)), Value(0, output_field=DecimalField())),
        received=Coalesce(Sum("amount", filter=Q(transaction_type=Transaction.RECEIVE)), Value(0, output_field=DecimalField())),
    )
    remaining = stats["lent"] - stats["received"]

    selected_year, selected_month = _parse_year_month(request)
    transactions = all_transactions
    if selected_year:
        transactions = transactions.filter(date__year=selected_year)
    if selected_month:
        transactions = transactions.filter(date__month=selected_month)
    transactions = transactions.order_by("-date", "-created_at")

    period_stats = transactions.aggregate(
        lent=Coalesce(Sum("amount", filter=Q(transaction_type=Transaction.LEND)), Value(0, output_field=DecimalField())),
        received=Coalesce(Sum("amount", filter=Q(transaction_type=Transaction.RECEIVE)), Value(0, output_field=DecimalField())),
    )

    year_options = list(all_transactions.values_list("date__year", flat=True).distinct().order_by("-date__year"))

    if request.GET.get("export") == "csv":
        rows = [
            (tx.date.isoformat(), tx.get_transaction_type_display(), tx.amount, tx.note)
            for tx in transactions
        ]
        return _csv_response(
            f"{debtor.name}_transactions.csv",
            [_("Date"), _("Type"), _("Amount"), _("Note")],
            rows,
        )

    context = {
        "debtor": debtor,
        "transactions": transactions,
        "form": form,
        "lent": stats["lent"],
        "received": stats["received"],
        "remaining": remaining,
        "period_lent": period_stats["lent"],
        "period_received": period_stats["received"],
        "year_options": year_options,
        "month_choices": MONTH_CHOICES,
        "selected_year": selected_year,
        "selected_month": selected_month,
        "selected_month_date": date_cls(2000, selected_month, 1) if selected_month else None,
        "chart_received": float(stats["received"]),
        "chart_remaining": float(remaining) if remaining > 0 else 0,
    }
    return render(request, "debtors/debtor_detail.html", context)


@login_required
def debtor_list_view(request):
    valid_filter_types = {"include", "exclude"}
    filter_type = request.GET.get("filter_type", "include").strip().lower()
    if filter_type not in valid_filter_types:
        filter_type = "include"

    selected_categories = [
        category
        for category in request.GET.getlist("category")
        if category in DebtorCategory.values
    ]

    valid_payment_statuses = {"ALL", "PAID", "UNPAID"}
    payment_status = request.GET.get("payment_status", "ALL").strip().upper()
    if payment_status not in valid_payment_statuses:
        payment_status = "ALL"

    search_query = request.GET.get("q", "").strip()

    debtors_base_qs = request.user.debtors.all()
    if selected_categories:
        if filter_type == "exclude":
            debtors_base_qs = debtors_base_qs.exclude(category__in=selected_categories)
        else:
            debtors_base_qs = debtors_base_qs.filter(category__in=selected_categories)

    if search_query:
        debtors_base_qs = debtors_base_qs.filter(name__icontains=search_query)

    debtors_qs = debtors_base_qs.annotate(
        total_lent_amt=Coalesce(
            Sum("transactions__amount", filter=Q(transactions__transaction_type=Transaction.LEND)),
            Value(0, output_field=DecimalField()),
        ),
        total_received_amt=Coalesce(
            Sum("transactions__amount", filter=Q(transactions__transaction_type=Transaction.RECEIVE)),
            Value(0, output_field=DecimalField()),
        ),
    )

    if payment_status == "PAID":
        debtors_qs = debtors_qs.filter(total_lent_amt__lte=F("total_received_amt"))
    elif payment_status == "UNPAID":
        debtors_qs = debtors_qs.filter(total_lent_amt__gt=F("total_received_amt"))

    debtors_qs = debtors_qs.order_by("name")

    stats = debtors_qs.aggregate(
        total_lent=Coalesce(Sum("total_lent_amt"), Value(0, output_field=DecimalField())),
        total_received=Coalesce(Sum("total_received_amt"), Value(0, output_field=DecimalField())),
    )
    remaining = stats["total_lent"] - stats["total_received"]

    # Calculate progress percentage
    for dr in debtors_qs:
        if dr.total_lent_amt > 0:
            dr.received_percent = min(100, int((dr.total_received_amt / dr.total_lent_amt) * 100))
        else:
            dr.received_percent = 0

    if request.GET.get("export") == "csv":
        rows = [
            (
                dr.name,
                dr.get_category_display(),
                dr.total_lent_amt,
                dr.total_received_amt,
                dr.total_lent_amt - dr.total_received_amt,
                _("Fully Collected") if dr.total_lent_amt <= dr.total_received_amt else _("Unpaid"),
            )
            for dr in debtors_qs
        ]
        return _csv_response(
            "debtors.csv",
            [_("Debtor"), _("Category"), _("Total Lent"), _("Total Received"), _("Remaining to Collect"), _("Status")],
            rows,
        )

    context = {
        "debtors": debtors_qs,
        "total_lent": stats["total_lent"],
        "total_received": stats["total_received"],
        "remaining": remaining,
        "selected_categories": selected_categories,
        "category_choices": DebtorCategory.choices,
        "filter_type": filter_type,
        "payment_status": payment_status,
        "search_query": search_query,
    }
    return render(request, "debtors/debtor_list.html", context)

@login_required
def transaction_edit_view(request, pk):
    transaction = get_object_or_404(Transaction, pk=pk, debtor__user=request.user)
    debtor = transaction.debtor
    if request.method == "POST":
        form = TransactionForm(request.POST, instance=transaction)
        if form.is_valid():
            form.save()
            messages.success(request, _("Transaction updated."))
            return redirect("debtor_detail", pk=debtor.pk)
    else:
        form = TransactionForm(instance=transaction)
    return render(request, "debtors/debtor_form.html", {"form": form, "title": _("Edit Transaction"), "back_url": f"/debtors/{debtor.pk}/"})


@login_required
def transaction_delete_view(request, pk):
    transaction = get_object_or_404(Transaction, pk=pk, debtor__user=request.user)
    debtor = transaction.debtor
    amount = transaction.amount
    transaction.delete()
    messages.success(request, _("Transaction of ৳%(amount)s deleted.") % {"amount": amount})
    return redirect("debtor_detail", pk=debtor.pk)
