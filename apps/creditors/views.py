import csv
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse
import django.utils.timezone
from datetime import date as date_cls
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum, Q, F, DecimalField, Value
from django.db.models.functions import Coalesce, TruncMonth
from django.utils import dateformat
from django.utils.translation import gettext as _

from .models import Creditor, CreditorCategory, Transaction

MONTH_CHOICES = [(i, date_cls(2000, i, 1)) for i in range(1, 13)]


def _csv_response(filename, header, rows):
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.write("\ufeff")  # UTF-8 BOM so Excel renders Bangla text correctly
    writer = csv.writer(response)
    writer.writerow(header)
    writer.writerows(rows)
    return response


def _last_12_month_starts():
    """List of 12 date(y, m, 1), oldest first, ending at the first of this month."""
    today = django.utils.timezone.now().date()
    starts = []
    for i in range(11, -1, -1):
        month_index = today.month - i
        year = today.year
        while month_index <= 0:
            month_index += 12
            year -= 1
        starts.append(date_cls(year, month_index, 1))
    return starts


def _period_label(selected_year, selected_month):
    if selected_month:
        return dateformat.format(date_cls(2000, selected_month, 1), "F") + f" {selected_year}"
    if selected_year:
        return str(selected_year)
    return _("All Time")


def _render_statement(request, *, entity_label, entity_name, entity_meta, period_label, summary_rows, columns, rows, back_url):
    return render(request, "statement.html", {
        "entity_label": entity_label,
        "entity_name": entity_name,
        "entity_meta": entity_meta,
        "period_label": period_label,
        "summary_rows": summary_rows,
        "columns": columns,
        "rows": rows,
        "back_url": back_url,
        "generated_at": django.utils.timezone.now(),
    })


def _parse_year_month(request):
    """Reads `year`/`month` GET params. Returns (year_or_None, month_or_None)."""
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
        if category in CreditorCategory.values
    ]

    creditors_base_qs = request.user.creditors.all()
    if selected_categories:
        if filter_type == "exclude":
            creditors_base_qs = creditors_base_qs.exclude(category__in=selected_categories)
        else:
            creditors_base_qs = creditors_base_qs.filter(category__in=selected_categories)

    # Global summary stats for the current user
    stats = creditors_base_qs.aggregate(
        total_borrowed=Coalesce(
            Sum(
                "transactions__amount",
                filter=Q(transactions__transaction_type=Transaction.BORROW),
            ),
            Value(0, output_field=DecimalField()),
        ),
        total_paid=Coalesce(
            Sum(
                "transactions__amount",
                filter=Q(transactions__transaction_type=Transaction.REPAY),
            ),
            Value(0, output_field=DecimalField()),
        ),
    )
    
    total_borrowed = stats["total_borrowed"]
    total_paid = stats["total_paid"]
    remaining = total_borrowed - total_paid
    
    # Creditor-wise breakdown for charts
    creditors_qs = creditors_base_qs.annotate(
        c_borrowed=Coalesce(Sum("transactions__amount", filter=Q(transactions__transaction_type=Transaction.BORROW)), Value(0, output_field=DecimalField())),
        c_paid=Coalesce(Sum("transactions__amount", filter=Q(transactions__transaction_type=Transaction.REPAY)), Value(0, output_field=DecimalField())),
    )
    
    creditor_labels = []
    creditor_remaining = []
    creditor_paid = []
    
    for c in creditors_qs:
        rem = c.c_borrowed - c.c_paid
        if c.c_borrowed > 0 or c.c_paid > 0:
            creditor_labels.append(c.name)
            creditor_remaining.append(float(rem) if rem > 0 else 0)
            creditor_paid.append(float(c.c_paid))

    # Recent activity
    recent_transactions = Transaction.objects.filter(creditor__user=request.user)
    if selected_categories:
        if filter_type == "exclude":
            recent_transactions = recent_transactions.exclude(
                creditor__category__in=selected_categories
            )
        else:
            recent_transactions = recent_transactions.filter(
                creditor__category__in=selected_categories
            )
    recent_transactions = recent_transactions.select_related("creditor").order_by(
        "-date", "-created_at"
    )[:10]

    # Rolling 12-month Borrowed vs Repaid trend.
    month_starts = _last_12_month_starts()
    monthly_totals = (
        Transaction.objects.filter(creditor__user=request.user, date__gte=month_starts[0])
        .annotate(month=TruncMonth("date"))
        .values("month", "transaction_type")
        .annotate(total=Sum("amount"))
    )
    borrowed_by_month = {row["month"]: row["total"] for row in monthly_totals if row["transaction_type"] == Transaction.BORROW}
    paid_by_month = {row["month"]: row["total"] for row in monthly_totals if row["transaction_type"] == Transaction.REPAY}
    trend_labels = month_starts
    trend_borrowed = [float(borrowed_by_month.get(d, 0) or 0) for d in month_starts]
    trend_paid = [float(paid_by_month.get(d, 0) or 0) for d in month_starts]

    context = {
        "total_borrowed": total_borrowed,
        "total_paid": total_paid,
        "remaining": remaining,
        "creditor_labels": creditor_labels,
        "creditor_remaining": creditor_remaining,
        "creditor_paid": creditor_paid,
        "trend_labels": trend_labels,
        "trend_borrowed": trend_borrowed,
        "trend_paid": trend_paid,
        "recent_transactions": recent_transactions,
        "selected_category": selected_categories[0] if len(selected_categories) == 1 else "",
        "selected_categories": selected_categories,
        "category_choices": CreditorCategory.choices,
        "filter_type": filter_type,
    }
    return render(request, "creditors/dashboard.html", context)


from .forms import CreditorForm, TransactionForm

@login_required
def creditor_create_view(request):
    if request.method == "POST":
        form = CreditorForm(request.POST)
        if form.is_valid():
            creditor = form.save(commit=False)
            creditor.user = request.user
            creditor.save()
            messages.success(request, _("Creditor '%(name)s' added successfully.") % {"name": creditor.name})
            return redirect("creditor_list")
    else:
        form = CreditorForm()
    return render(request, "creditors/creditor_form.html", {"form": form, "title": _("Add New Creditor")})


@login_required
def creditor_edit_view(request, pk):
    creditor = get_object_or_404(Creditor, pk=pk, user=request.user)
    if request.method == "POST":
        form = CreditorForm(request.POST, instance=creditor)
        if form.is_valid():
            form.save()
            messages.success(request, _("Creditor '%(name)s' updated successfully.") % {"name": creditor.name})
            return redirect("creditor_list")
    else:
        form = CreditorForm(instance=creditor)
    return render(request, "creditors/creditor_form.html", {"form": form, "title": _("Edit %(name)s") % {"name": creditor.name}})


@login_required
def creditor_detail_view(request, pk):
    creditor = get_object_or_404(Creditor, pk=pk, user=request.user)
    all_transactions = creditor.transactions.all()

    if request.method == "POST":
        form = TransactionForm(request.POST)
        if form.is_valid():
            transaction = form.save(commit=False)
            transaction.creditor = creditor
            transaction.save()
            messages.success(request, _("Transaction of ৳%(amount)s added.") % {"amount": transaction.amount})
            return redirect("creditor_detail", pk=pk)
    else:
        form = TransactionForm(initial={"date": django.utils.timezone.now().date()})

    # Calculate all-time totals for this specific creditor (never period-filtered —
    # outstanding balance only makes sense as a current, running snapshot).
    stats = all_transactions.aggregate(
        borrowed=Coalesce(Sum("amount", filter=Q(transaction_type=Transaction.BORROW)), Value(0, output_field=DecimalField())),
        paid=Coalesce(Sum("amount", filter=Q(transaction_type=Transaction.REPAY)), Value(0, output_field=DecimalField())),
    )
    remaining = stats["borrowed"] - stats["paid"]

    # Year/month filter narrows the transaction list and the "this period" figures below.
    selected_year, selected_month = _parse_year_month(request)
    transactions = all_transactions
    if selected_year:
        transactions = transactions.filter(date__year=selected_year)
    if selected_month:
        transactions = transactions.filter(date__month=selected_month)
    transactions = transactions.order_by("-date", "-created_at")

    period_stats = transactions.aggregate(
        borrowed=Coalesce(Sum("amount", filter=Q(transaction_type=Transaction.BORROW)), Value(0, output_field=DecimalField())),
        paid=Coalesce(Sum("amount", filter=Q(transaction_type=Transaction.REPAY)), Value(0, output_field=DecimalField())),
    )

    year_options = list(all_transactions.values_list("date__year", flat=True).distinct().order_by("-date__year"))

    if request.GET.get("export") == "csv":
        rows = [
            (tx.date.isoformat(), tx.get_transaction_type_display(), tx.amount, tx.note)
            for tx in transactions
        ]
        return _csv_response(
            f"{creditor.name}_transactions.csv",
            [_("Date"), _("Type"), _("Amount"), _("Note")],
            rows,
        )

    context = {
        "creditor": creditor,
        "transactions": transactions,
        "form": form,
        "borrowed": stats["borrowed"],
        "paid": stats["paid"],
        "remaining": remaining,
        "period_borrowed": period_stats["borrowed"],
        "period_paid": period_stats["paid"],
        "year_options": year_options,
        "month_choices": MONTH_CHOICES,
        "selected_year": selected_year,
        "selected_month": selected_month,
        "selected_month_date": date_cls(2000, selected_month, 1) if selected_month else None,
        "chart_paid": float(stats["paid"]),
        "chart_remaining": float(remaining) if remaining > 0 else 0,
    }
    return render(request, "creditors/creditor_detail.html", context)


@login_required
def creditor_statement_view(request, pk):
    creditor = get_object_or_404(Creditor, pk=pk, user=request.user)
    all_transactions = creditor.transactions.all()

    selected_year, selected_month = _parse_year_month(request)
    transactions = all_transactions
    if selected_year:
        transactions = transactions.filter(date__year=selected_year)
    if selected_month:
        transactions = transactions.filter(date__month=selected_month)
    transactions = transactions.order_by("date", "created_at")

    stats = all_transactions.aggregate(
        borrowed=Coalesce(Sum("amount", filter=Q(transaction_type=Transaction.BORROW)), Value(0, output_field=DecimalField())),
        paid=Coalesce(Sum("amount", filter=Q(transaction_type=Transaction.REPAY)), Value(0, output_field=DecimalField())),
    )
    remaining = stats["borrowed"] - stats["paid"]

    period_label = _period_label(selected_year, selected_month)

    rows = [
        (tx.date.strftime("%d %b %Y"), tx.get_transaction_type_display(), tx.note or "-", f"{tx.amount:,.2f}")
        for tx in transactions
    ]

    return _render_statement(
        request,
        entity_label=_("Creditor"),
        entity_name=creditor.name,
        entity_meta=[(_("Phone"), creditor.phone), (_("Category"), creditor.get_category_display())],
        period_label=period_label,
        summary_rows=[
            (_("Total Borrowed"), f"{stats['borrowed']:,.2f}", ""),
            (_("Total Repaid"), f"{stats['paid']:,.2f}", "positive"),
            (_("Outstanding Balance"), f"{remaining:,.2f}", "negative" if remaining > 0 else "positive"),
        ],
        columns=[_("Date"), _("Type"), _("Note"), _("Amount (৳)")],
        rows=rows,
        back_url=request.META.get("HTTP_REFERER") or f"/creditors/{creditor.pk}/",
    )


@login_required
def creditor_list_view(request):
    valid_filter_types = {"include", "exclude"}
    filter_type = request.GET.get("filter_type", "include").strip().lower()
    if filter_type not in valid_filter_types:
        filter_type = "include"

    selected_categories = [
        category
        for category in request.GET.getlist("category")
        if category in CreditorCategory.values
    ]

    valid_payment_statuses = {"ALL", "PAID", "UNPAID"}
    payment_status = request.GET.get("payment_status", "ALL").strip().upper()
    if payment_status not in valid_payment_statuses:
        payment_status = "ALL"

    search_query = request.GET.get("q", "").strip()

    creditors_base_qs = request.user.creditors.all()
    if selected_categories:
        if filter_type == "exclude":
            creditors_base_qs = creditors_base_qs.exclude(category__in=selected_categories)
        else:
            creditors_base_qs = creditors_base_qs.filter(category__in=selected_categories)

    if search_query:
        creditors_base_qs = creditors_base_qs.filter(name__icontains=search_query)

    creditors_qs = creditors_base_qs.annotate(
        total_borrowed_amt=Coalesce(
            Sum("transactions__amount", filter=Q(transactions__transaction_type=Transaction.BORROW)),
            Value(0, output_field=DecimalField()),
        ),
        total_paid_amt=Coalesce(
            Sum("transactions__amount", filter=Q(transactions__transaction_type=Transaction.REPAY)),
            Value(0, output_field=DecimalField()),
        ),
    )

    if payment_status == "PAID":
        creditors_qs = creditors_qs.filter(total_borrowed_amt__lte=F("total_paid_amt"))
    elif payment_status == "UNPAID":
        creditors_qs = creditors_qs.filter(total_borrowed_amt__gt=F("total_paid_amt"))

    creditors_qs = creditors_qs.order_by("name")

    stats = creditors_qs.aggregate(
        total_borrowed=Coalesce(Sum("total_borrowed_amt"), Value(0, output_field=DecimalField())),
        total_paid=Coalesce(Sum("total_paid_amt"), Value(0, output_field=DecimalField())),
    )
    remaining = stats["total_borrowed"] - stats["total_paid"]

    # Calculate progress percentage manually to avoid complex template logic
    for cr in creditors_qs:
        if cr.total_borrowed_amt > 0:
            cr.payment_percent = min(100, int((cr.total_paid_amt / cr.total_borrowed_amt) * 100))
        else:
            cr.payment_percent = 0

    if request.GET.get("export") == "csv":
        rows = [
            (
                cr.name,
                cr.get_category_display(),
                cr.total_borrowed_amt,
                cr.total_paid_amt,
                cr.total_borrowed_amt - cr.total_paid_amt,
                _("Paid Completely") if cr.total_borrowed_amt <= cr.total_paid_amt else _("Unpaid"),
            )
            for cr in creditors_qs
        ]
        return _csv_response(
            "creditors.csv",
            [_("Creditor"), _("Category"), _("Total Borrowed"), _("Total Paid"), _("Remaining Debt"), _("Status")],
            rows,
        )

    context = {
        "creditors": creditors_qs,
        "total_borrowed": stats["total_borrowed"],
        "total_paid": stats["total_paid"],
        "remaining": remaining,
        "selected_categories": selected_categories,
        "category_choices": CreditorCategory.choices,
        "filter_type": filter_type,
        "payment_status": payment_status,
        "search_query": search_query,
    }
    return render(request, "creditors/creditor_list.html", context)

@login_required
def transaction_edit_view(request, pk):
    transaction = get_object_or_404(Transaction, pk=pk, creditor__user=request.user)
    creditor = transaction.creditor
    if request.method == "POST":
        form = TransactionForm(request.POST, instance=transaction)
        if form.is_valid():
            form.save()
            messages.success(request, _("Transaction updated."))
            return redirect("creditor_detail", pk=creditor.pk)
    else:
        form = TransactionForm(instance=transaction)
    return render(request, "creditors/creditor_form.html", {"form": form, "title": _("Edit Transaction"), "back_url": f"/creditors/{creditor.pk}/"})


@login_required
def transaction_delete_view(request, pk):
    transaction = get_object_or_404(Transaction, pk=pk, creditor__user=request.user)
    creditor = transaction.creditor
    amount = transaction.amount
    transaction.delete()
    messages.success(request, _("Transaction of ৳%(amount)s deleted.") % {"amount": amount})
    return redirect("creditor_detail", pk=creditor.pk)
