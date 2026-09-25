import csv
import io
from decimal import Decimal, InvalidOperation
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.http import HttpResponse
import django.utils.timezone
from datetime import date as date_cls, timedelta
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.db.models import Sum, Q, F, DecimalField, Value
from django.db.models.functions import Coalesce, TruncMonth
from django.core.paginator import Paginator
from django.utils import dateformat
from django.utils.translation import gettext as _

from .models import Debtor, DebtorCategory, Transaction, DUE_SOON_DAYS
from apps.core.status import apply_status_filter, toggle_active


def _row_value(row, fieldnames, key):
    """Reads a value from a csv.DictReader row by lowercased column name."""
    col = fieldnames.get(key)
    if col is None:
        return ""
    return (row.get(col) or "").strip()

SORT_OPTIONS = [
    ("name", _("Name (A–Z)")),
    ("-name", _("Name (Z–A)")),
    ("-remaining", _("Remaining (High to Low)")),
    ("remaining", _("Remaining (Low to High)")),
]
SORT_FIELDS = {
    "name": ["name"],
    "-name": ["-name"],
    "remaining": ["remaining_amt", "name"],
    "-remaining": ["-remaining_amt", "name"],
}


def _build_pagination_window(page_obj, window=2):
    """Compact list of page numbers around the current page, with None as a '…' gap."""
    total_pages = page_obj.paginator.num_pages
    current = page_obj.number
    pages = {1, total_pages}

    for page_number in range(current - window, current + window + 1):
        if 1 <= page_number <= total_pages:
            pages.add(page_number)

    ordered_pages = sorted(pages)
    compact_pages = []
    previous = None

    for page_number in ordered_pages:
        if previous is not None and page_number - previous > 1:
            compact_pages.append(None)
        compact_pages.append(page_number)
        previous = page_number

    return compact_pages


def _csv_response(filename, header, rows):
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.write("\ufeff")  # UTF-8 BOM so Excel renders Bangla text correctly
    writer = csv.writer(response)
    writer.writerow(header)
    writer.writerows(rows)
    return response


def _last_12_month_starts():
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

    # Debtors needing attention: an outstanding balance with a due date that
    # has passed or is coming up within DUE_SOON_DAYS.
    today = django.utils.timezone.now().date()
    due_soon_cutoff = today + timedelta(days=DUE_SOON_DAYS)
    overdue_debtors = []
    due_soon_debtors = []
    for d in debtors_qs:
        rem = d.d_lent - d.d_received
        if d.due_date and rem > 0:
            d.remaining_amt = rem
            if d.due_date < today:
                overdue_debtors.append(d)
            elif d.due_date <= due_soon_cutoff:
                due_soon_debtors.append(d)
    overdue_debtors.sort(key=lambda d: d.due_date)
    due_soon_debtors.sort(key=lambda d: d.due_date)

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

    # Rolling 12-month Lent vs Received trend.
    month_starts = _last_12_month_starts()
    monthly_totals = (
        Transaction.objects.filter(debtor__user=request.user, date__gte=month_starts[0])
        .annotate(month=TruncMonth("date"))
        .values("month", "transaction_type")
        .annotate(total=Sum("amount"))
    )
    lent_by_month = {row["month"]: row["total"] for row in monthly_totals if row["transaction_type"] == Transaction.LEND}
    received_by_month = {row["month"]: row["total"] for row in monthly_totals if row["transaction_type"] == Transaction.RECEIVE}
    trend_labels = month_starts
    trend_lent = [float(lent_by_month.get(d, 0) or 0) for d in month_starts]
    trend_received = [float(received_by_month.get(d, 0) or 0) for d in month_starts]

    context = {
        "total_lent": total_lent,
        "total_received": total_received,
        "remaining": remaining,
        "debtor_labels": debtor_labels,
        "debtor_remaining": debtor_remaining,
        "debtor_received": debtor_received,
        "trend_labels": trend_labels,
        "trend_lent": trend_lent,
        "trend_received": trend_received,
        "recent_transactions": recent_transactions,
        "overdue_debtors": overdue_debtors,
        "due_soon_debtors": due_soon_debtors,
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

    due_status = None
    if debtor.due_date and remaining > 0:
        today = django.utils.timezone.now().date()
        if debtor.due_date < today:
            due_status = "overdue"
        elif debtor.due_date <= today + timedelta(days=DUE_SOON_DAYS):
            due_status = "due_soon"

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
        "due_status": due_status,
    }
    return render(request, "debtors/debtor_detail.html", context)


@login_required
def debtor_statement_view(request, pk):
    debtor = get_object_or_404(Debtor, pk=pk, user=request.user)
    all_transactions = debtor.transactions.all()

    selected_year, selected_month = _parse_year_month(request)
    transactions = all_transactions
    if selected_year:
        transactions = transactions.filter(date__year=selected_year)
    if selected_month:
        transactions = transactions.filter(date__month=selected_month)
    transactions = transactions.order_by("date", "created_at")

    stats = all_transactions.aggregate(
        lent=Coalesce(Sum("amount", filter=Q(transaction_type=Transaction.LEND)), Value(0, output_field=DecimalField())),
        received=Coalesce(Sum("amount", filter=Q(transaction_type=Transaction.RECEIVE)), Value(0, output_field=DecimalField())),
    )
    remaining = stats["lent"] - stats["received"]

    rows = [
        (tx.date.strftime("%d %b %Y"), tx.get_transaction_type_display(), tx.note or "-", f"{tx.amount:,.2f}")
        for tx in transactions
    ]

    return _render_statement(
        request,
        entity_label=_("Debtor"),
        entity_name=debtor.name,
        entity_meta=[(_("Phone"), debtor.phone), (_("Category"), debtor.get_category_display())],
        period_label=_period_label(selected_year, selected_month),
        summary_rows=[
            (_("Total Lent"), f"{stats['lent']:,.2f}", ""),
            (_("Total Received"), f"{stats['received']:,.2f}", "positive"),
            (_("Remaining to Collect"), f"{remaining:,.2f}", "negative" if remaining > 0 else "positive"),
        ],
        columns=[_("Date"), _("Type"), _("Note"), _("Amount (৳)")],
        rows=rows,
        back_url=request.META.get("HTTP_REFERER") or f"/debtors/debtors/{debtor.pk}/",
    )


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

    status, debtors_base_qs, status_counts = apply_status_filter(request, debtors_base_qs)

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

    sort = request.GET.get("sort", "name")
    if sort not in SORT_FIELDS:
        sort = "name"
    debtors_qs = debtors_qs.annotate(
        remaining_amt=F("total_lent_amt") - F("total_received_amt")
    ).order_by(*SORT_FIELDS[sort])

    stats = debtors_qs.aggregate(
        total_lent=Coalesce(Sum("total_lent_amt"), Value(0, output_field=DecimalField())),
        total_received=Coalesce(Sum("total_received_amt"), Value(0, output_field=DecimalField())),
    )
    remaining = stats["total_lent"] - stats["total_received"]

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

    paginator = Paginator(debtors_qs, 9)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    # Calculate progress percentage
    today = django.utils.timezone.now().date()
    due_soon_cutoff = today + timedelta(days=DUE_SOON_DAYS)
    for dr in page_obj:
        if dr.total_lent_amt > 0:
            dr.received_percent = min(100, int((dr.total_received_amt / dr.total_lent_amt) * 100))
        else:
            dr.received_percent = 0

        dr.due_status = None
        if dr.due_date and dr.remaining_amt > 0:
            if dr.due_date < today:
                dr.due_status = "overdue"
            elif dr.due_date <= due_soon_cutoff:
                dr.due_status = "due_soon"

    base_query = request.GET.copy()
    base_query.pop("page", None)
    base_query_string = base_query.urlencode()

    context = {
        "page_obj": page_obj,
        "pagination_window": _build_pagination_window(page_obj),
        "total_lent": stats["total_lent"],
        "total_received": stats["total_received"],
        "remaining": remaining,
        "selected_categories": selected_categories,
        "category_choices": DebtorCategory.choices,
        "filter_type": filter_type,
        "payment_status": payment_status,
        "search_query": search_query,
        "status": status,
        "status_counts": status_counts,
        "sort": sort,
        "sort_options": SORT_OPTIONS,
        "base_query_string": base_query_string,
    }
    return render(request, "debtors/debtor_list.html", context)


@login_required
def debtor_import_template_view(request):
    rows = [(_("Karim Uddin"), "01711000000", _("Friend"), _("Lent for emergency"), "5000")]
    return _csv_response(
        "debtor_import_template.csv",
        [_("Name"), _("Phone"), _("Category"), _("Note"), _("Opening Balance")],
        rows,
    )


@login_required
def debtor_import_view(request):
    if request.method != "POST":
        return redirect("debtor_list")

    csv_file = request.FILES.get("csv_file")
    if not csv_file:
        messages.error(request, _("Please choose a CSV file to import."))
        return redirect("debtor_list")

    try:
        decoded = csv_file.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        messages.error(request, _("Could not read that file. Please upload a UTF-8 encoded CSV."))
        return redirect("debtor_list")

    reader = csv.DictReader(io.StringIO(decoded))
    if not reader.fieldnames:
        messages.error(request, _("The CSV file appears to be empty."))
        return redirect("debtor_list")

    fieldnames = {(f or "").strip().lower(): f for f in reader.fieldnames}
    if "name" not in fieldnames:
        messages.error(request, _("The CSV must have a 'Name' column."))
        return redirect("debtor_list")

    category_lookup = {}
    for value, label in DebtorCategory.choices:
        category_lookup[value.lower()] = value
        category_lookup[str(label).lower()] = value

    existing_names = {n.lower() for n in request.user.debtors.values_list("name", flat=True)}
    today = django.utils.timezone.now().date()

    created = 0
    skipped_duplicate = 0
    skipped_blank = 0

    for row in reader:
        name = _row_value(row, fieldnames, "name")
        if not name:
            skipped_blank += 1
            continue
        if name.lower() in existing_names:
            skipped_duplicate += 1
            continue

        phone = _row_value(row, fieldnames, "phone")
        note = _row_value(row, fieldnames, "note")
        category = category_lookup.get(_row_value(row, fieldnames, "category").lower(), DebtorCategory.OTHER)

        raw_balance = _row_value(row, fieldnames, "opening balance") or _row_value(row, fieldnames, "opening_balance")
        try:
            opening_balance = Decimal(raw_balance) if raw_balance else Decimal("0")
        except InvalidOperation:
            opening_balance = Decimal("0")

        debtor = Debtor.objects.create(
            user=request.user, name=name, phone=phone, note=note, category=category
        )
        if opening_balance > 0:
            Transaction.objects.create(
                debtor=debtor,
                transaction_type=Transaction.LEND,
                amount=opening_balance,
                date=today,
                note=_("Opening balance (imported)"),
            )

        existing_names.add(name.lower())
        created += 1

    if created:
        messages.success(request, _("Imported %(count)s debtor(s).") % {"count": created})
    skipped_total = skipped_duplicate + skipped_blank
    if skipped_total:
        messages.warning(
            request,
            _("Skipped %(count)s row(s): %(dup)s duplicate name(s), %(blank)s blank name(s).")
            % {"count": skipped_total, "dup": skipped_duplicate, "blank": skipped_blank},
        )
    if not created and not skipped_total:
        messages.error(request, _("No rows found to import."))

    return redirect("debtor_list")


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
    return render(request, "debtors/debtor_form.html", {"form": form, "title": _("Edit Transaction"), "back_url": reverse("debtor_detail", args=[debtor.pk])})


@login_required
@require_POST
def transaction_delete_view(request, pk):
    transaction = get_object_or_404(Transaction, pk=pk, debtor__user=request.user)
    debtor = transaction.debtor
    amount = transaction.amount
    transaction.delete()
    messages.success(request, _("Transaction of ৳%(amount)s deleted.") % {"amount": amount})
    return redirect("debtor_detail", pk=debtor.pk)


@login_required
@require_POST
def debtor_toggle_active_view(request, pk):
    obj = get_object_or_404(Debtor, pk=pk, user=request.user)
    return toggle_active(request, obj, "debtor_list")
