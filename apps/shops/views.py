import csv
import io
from decimal import Decimal, InvalidOperation
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse
import django.utils.timezone
from datetime import date as date_cls
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum, Q, F, DecimalField, Value
from django.db.models.functions import Coalesce, TruncMonth
from django.core.paginator import Paginator
from django.utils import dateformat
from django.utils.translation import gettext as _


def _row_value(row, fieldnames, key):
    """Reads a value from a csv.DictReader row by lowercased column name."""
    col = fieldnames.get(key)
    if col is None:
        return ""
    return (row.get(col) or "").strip()


def _csv_response(filename, header, rows):
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.write("\ufeff")  # UTF-8 BOM so Excel renders Bangla text correctly
    writer = csv.writer(response)
    writer.writerow(header)
    writer.writerows(rows)
    return response

from .models import Shop, ShopCategory, Transaction

MONTH_CHOICES = [(i, date_cls(2000, i, 1)) for i in range(1, 13)]

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


def _parse_year_month(request):
    raw_year = request.GET.get("year", "").strip()
    year = int(raw_year) if raw_year.isdigit() else None
    raw_month = request.GET.get("month", "").strip()
    month = int(raw_month) if raw_month.isdigit() and 1 <= int(raw_month) <= 12 else None
    return year, month


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


from .forms import ShopForm, TransactionForm


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


@login_required
def dashboard_view(request):
    valid_filter_types = {"include", "exclude"}
    filter_type = request.GET.get("filter_type", "include").strip().lower()
    if filter_type not in valid_filter_types:
        filter_type = "include"

    selected_categories = [
        category
        for category in request.GET.getlist("category")
        if category in ShopCategory.values
    ]

    shops_base_qs = request.user.shops.all()
    if selected_categories:
        if filter_type == "exclude":
            shops_base_qs = shops_base_qs.exclude(category__in=selected_categories)
        else:
            shops_base_qs = shops_base_qs.filter(category__in=selected_categories)

    # Global summary stats for the current user
    stats = shops_base_qs.aggregate(
        total_due=Coalesce(
            Sum(
                "transactions__amount",
                filter=Q(transactions__transaction_type=Transaction.PURCHASE),
            ),
            Value(0, output_field=DecimalField()),
        ),
        total_paid=Coalesce(
            Sum(
                "transactions__amount",
                filter=Q(transactions__transaction_type=Transaction.PAYMENT),
            ),
            Value(0, output_field=DecimalField()),
        ),
    )

    total_due = stats["total_due"]
    total_paid = stats["total_paid"]
    remaining = total_due - total_paid

    # Shop-wise breakdown for charts
    shops_qs = shops_base_qs.annotate(
        s_due=Coalesce(Sum("transactions__amount", filter=Q(transactions__transaction_type=Transaction.PURCHASE)), Value(0, output_field=DecimalField())),
        s_paid=Coalesce(Sum("transactions__amount", filter=Q(transactions__transaction_type=Transaction.PAYMENT)), Value(0, output_field=DecimalField())),
    )

    shop_labels = []
    shop_remaining = []
    shop_paid = []

    for s in shops_qs:
        rem = s.s_due - s.s_paid
        if s.s_due > 0 or s.s_paid > 0:
            shop_labels.append(s.name)
            shop_remaining.append(float(rem) if rem > 0 else 0)
            shop_paid.append(float(s.s_paid))

    # Recent activity
    recent_transactions = Transaction.objects.filter(shop__user=request.user)
    if selected_categories:
        if filter_type == "exclude":
            recent_transactions = recent_transactions.exclude(
                shop__category__in=selected_categories
            )
        else:
            recent_transactions = recent_transactions.filter(
                shop__category__in=selected_categories
            )
    recent_transactions = recent_transactions.select_related("shop").order_by(
        "-date", "-created_at"
    )[:10]

    # Rolling 12-month Purchased vs Paid trend.
    month_starts = _last_12_month_starts()
    monthly_totals = (
        Transaction.objects.filter(shop__user=request.user, date__gte=month_starts[0])
        .annotate(month=TruncMonth("date"))
        .values("month", "transaction_type")
        .annotate(total=Sum("amount"))
    )
    due_by_month = {row["month"]: row["total"] for row in monthly_totals if row["transaction_type"] == Transaction.PURCHASE}
    paid_by_month = {row["month"]: row["total"] for row in monthly_totals if row["transaction_type"] == Transaction.PAYMENT}
    trend_labels = month_starts
    trend_due = [float(due_by_month.get(d, 0) or 0) for d in month_starts]
    trend_paid = [float(paid_by_month.get(d, 0) or 0) for d in month_starts]

    context = {
        "total_due": total_due,
        "total_paid": total_paid,
        "remaining": remaining,
        "shop_labels": shop_labels,
        "shop_remaining": shop_remaining,
        "shop_paid": shop_paid,
        "trend_labels": trend_labels,
        "trend_due": trend_due,
        "trend_paid": trend_paid,
        "recent_transactions": recent_transactions,
        "selected_categories": selected_categories,
        "category_choices": ShopCategory.choices,
        "filter_type": filter_type,
    }
    return render(request, "shops/dashboard.html", context)


@login_required
def shop_create_view(request):
    if request.method == "POST":
        form = ShopForm(request.POST)
        if form.is_valid():
            shop = form.save(commit=False)
            shop.user = request.user
            shop.save()
            messages.success(request, _("Shop '%(name)s' added successfully.") % {"name": shop.name})
            return redirect("shop_list")
    else:
        form = ShopForm()
    return render(request, "shops/shop_form.html", {"form": form, "title": _("Add New Shop")})


@login_required
def shop_edit_view(request, pk):
    shop = get_object_or_404(Shop, pk=pk, user=request.user)
    if request.method == "POST":
        form = ShopForm(request.POST, instance=shop)
        if form.is_valid():
            form.save()
            messages.success(request, _("Shop '%(name)s' updated successfully.") % {"name": shop.name})
            return redirect("shop_list")
    else:
        form = ShopForm(instance=shop)
    return render(request, "shops/shop_form.html", {"form": form, "title": _("Edit %(name)s") % {"name": shop.name}})


@login_required
def shop_detail_view(request, pk):
    shop = get_object_or_404(Shop, pk=pk, user=request.user)
    all_transactions = shop.transactions.all()

    if request.method == "POST":
        form = TransactionForm(request.POST)
        if form.is_valid():
            transaction = form.save(commit=False)
            transaction.shop = shop
            transaction.save()
            messages.success(request, _("Transaction of ৳%(amount)s added.") % {"amount": transaction.amount})
            return redirect("shop_detail", pk=pk)
    else:
        form = TransactionForm(initial={"date": django.utils.timezone.now().date()})

    # Calculate all-time totals for this specific shop (never period-filtered —
    # outstanding balance only makes sense as a current, running snapshot).
    stats = all_transactions.aggregate(
        due=Coalesce(Sum("amount", filter=Q(transaction_type=Transaction.PURCHASE)), Value(0, output_field=DecimalField())),
        paid=Coalesce(Sum("amount", filter=Q(transaction_type=Transaction.PAYMENT)), Value(0, output_field=DecimalField())),
    )
    remaining = stats["due"] - stats["paid"]

    selected_year, selected_month = _parse_year_month(request)
    transactions = all_transactions
    if selected_year:
        transactions = transactions.filter(date__year=selected_year)
    if selected_month:
        transactions = transactions.filter(date__month=selected_month)
    transactions = transactions.order_by("-date", "-created_at")

    period_stats = transactions.aggregate(
        due=Coalesce(Sum("amount", filter=Q(transaction_type=Transaction.PURCHASE)), Value(0, output_field=DecimalField())),
        paid=Coalesce(Sum("amount", filter=Q(transaction_type=Transaction.PAYMENT)), Value(0, output_field=DecimalField())),
    )

    year_options = list(all_transactions.values_list("date__year", flat=True).distinct().order_by("-date__year"))

    if request.GET.get("export") == "csv":
        rows = [
            (tx.date.isoformat(), tx.get_transaction_type_display(), tx.amount, tx.note)
            for tx in transactions
        ]
        return _csv_response(
            f"{shop.name}_transactions.csv",
            [_("Date"), _("Type"), _("Amount"), _("Note")],
            rows,
        )

    context = {
        "shop": shop,
        "transactions": transactions,
        "form": form,
        "due": stats["due"],
        "paid": stats["paid"],
        "remaining": remaining,
        "period_due": period_stats["due"],
        "period_paid": period_stats["paid"],
        "year_options": year_options,
        "month_choices": MONTH_CHOICES,
        "selected_year": selected_year,
        "selected_month": selected_month,
        "selected_month_date": date_cls(2000, selected_month, 1) if selected_month else None,
        "chart_paid": float(stats["paid"]),
        "chart_remaining": float(remaining) if remaining > 0 else 0,
    }
    return render(request, "shops/shop_detail.html", context)


@login_required
def shop_statement_view(request, pk):
    shop = get_object_or_404(Shop, pk=pk, user=request.user)
    all_transactions = shop.transactions.all()

    selected_year, selected_month = _parse_year_month(request)
    transactions = all_transactions
    if selected_year:
        transactions = transactions.filter(date__year=selected_year)
    if selected_month:
        transactions = transactions.filter(date__month=selected_month)
    transactions = transactions.order_by("date", "created_at")

    stats = all_transactions.aggregate(
        due=Coalesce(Sum("amount", filter=Q(transaction_type=Transaction.PURCHASE)), Value(0, output_field=DecimalField())),
        paid=Coalesce(Sum("amount", filter=Q(transaction_type=Transaction.PAYMENT)), Value(0, output_field=DecimalField())),
    )
    remaining = stats["due"] - stats["paid"]

    rows = [
        (tx.date.strftime("%d %b %Y"), tx.get_transaction_type_display(), tx.note or "-", f"{tx.amount:,.2f}")
        for tx in transactions
    ]

    return _render_statement(
        request,
        entity_label=_("Shop"),
        entity_name=shop.name,
        entity_meta=[(_("Phone"), shop.phone), (_("Category"), shop.get_category_display())],
        period_label=_period_label(selected_year, selected_month),
        summary_rows=[
            (_("Total Due"), f"{stats['due']:,.2f}", ""),
            (_("Total Paid"), f"{stats['paid']:,.2f}", "positive"),
            (_("Remaining Due"), f"{remaining:,.2f}", "negative" if remaining > 0 else "positive"),
        ],
        columns=[_("Date"), _("Type"), _("Note"), _("Amount (৳)")],
        rows=rows,
        back_url=request.META.get("HTTP_REFERER") or f"/shops/{shop.pk}/",
    )


@login_required
def shop_list_view(request):
    valid_filter_types = {"include", "exclude"}
    filter_type = request.GET.get("filter_type", "include").strip().lower()
    if filter_type not in valid_filter_types:
        filter_type = "include"

    selected_categories = [
        category
        for category in request.GET.getlist("category")
        if category in ShopCategory.values
    ]

    valid_payment_statuses = {"ALL", "PAID", "UNPAID"}
    payment_status = request.GET.get("payment_status", "ALL").strip().upper()
    if payment_status not in valid_payment_statuses:
        payment_status = "ALL"

    search_query = request.GET.get("q", "").strip()

    shops_base_qs = request.user.shops.all()
    if selected_categories:
        if filter_type == "exclude":
            shops_base_qs = shops_base_qs.exclude(category__in=selected_categories)
        else:
            shops_base_qs = shops_base_qs.filter(category__in=selected_categories)

    if search_query:
        shops_base_qs = shops_base_qs.filter(name__icontains=search_query)

    shops_qs = shops_base_qs.annotate(
        total_due_amt=Coalesce(
            Sum("transactions__amount", filter=Q(transactions__transaction_type=Transaction.PURCHASE)),
            Value(0, output_field=DecimalField()),
        ),
        total_paid_amt=Coalesce(
            Sum("transactions__amount", filter=Q(transactions__transaction_type=Transaction.PAYMENT)),
            Value(0, output_field=DecimalField()),
        ),
    )

    if payment_status == "PAID":
        shops_qs = shops_qs.filter(total_due_amt__lte=F("total_paid_amt"))
    elif payment_status == "UNPAID":
        shops_qs = shops_qs.filter(total_due_amt__gt=F("total_paid_amt"))

    sort = request.GET.get("sort", "name")
    if sort not in SORT_FIELDS:
        sort = "name"
    shops_qs = shops_qs.annotate(
        remaining_amt=F("total_due_amt") - F("total_paid_amt")
    ).order_by(*SORT_FIELDS[sort])

    stats = shops_qs.aggregate(
        total_due=Coalesce(Sum("total_due_amt"), Value(0, output_field=DecimalField())),
        total_paid=Coalesce(Sum("total_paid_amt"), Value(0, output_field=DecimalField())),
    )
    remaining = stats["total_due"] - stats["total_paid"]

    if request.GET.get("export") == "csv":
        rows = [
            (
                sh.name,
                sh.get_category_display(),
                sh.total_due_amt,
                sh.total_paid_amt,
                sh.total_due_amt - sh.total_paid_amt,
                _("Paid Completely") if sh.total_due_amt <= sh.total_paid_amt else _("Unpaid"),
            )
            for sh in shops_qs
        ]
        return _csv_response(
            "shops.csv",
            [_("Shop"), _("Category"), _("Total Due"), _("Total Paid"), _("Remaining Due"), _("Status")],
            rows,
        )

    paginator = Paginator(shops_qs, 9)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    # Calculate progress percentage manually to avoid complex template logic
    for sh in page_obj:
        if sh.total_due_amt > 0:
            sh.payment_percent = min(100, int((sh.total_paid_amt / sh.total_due_amt) * 100))
        else:
            sh.payment_percent = 0

    base_query = request.GET.copy()
    base_query.pop("page", None)
    base_query_string = base_query.urlencode()

    context = {
        "page_obj": page_obj,
        "pagination_window": _build_pagination_window(page_obj),
        "total_due": stats["total_due"],
        "total_paid": stats["total_paid"],
        "remaining": remaining,
        "selected_categories": selected_categories,
        "category_choices": ShopCategory.choices,
        "filter_type": filter_type,
        "payment_status": payment_status,
        "search_query": search_query,
        "sort": sort,
        "sort_options": SORT_OPTIONS,
        "base_query_string": base_query_string,
    }
    return render(request, "shops/shop_list.html", context)


@login_required
def shop_import_template_view(request):
    rows = [(_("Rahim Store"), "01711000000", _("Grocery"), _("Monthly groceries on credit"), "3000")]
    return _csv_response(
        "shop_import_template.csv",
        [_("Name"), _("Phone"), _("Category"), _("Note"), _("Opening Balance")],
        rows,
    )


@login_required
def shop_import_view(request):
    if request.method != "POST":
        return redirect("shop_list")

    csv_file = request.FILES.get("csv_file")
    if not csv_file:
        messages.error(request, _("Please choose a CSV file to import."))
        return redirect("shop_list")

    try:
        decoded = csv_file.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        messages.error(request, _("Could not read that file. Please upload a UTF-8 encoded CSV."))
        return redirect("shop_list")

    reader = csv.DictReader(io.StringIO(decoded))
    if not reader.fieldnames:
        messages.error(request, _("The CSV file appears to be empty."))
        return redirect("shop_list")

    fieldnames = {(f or "").strip().lower(): f for f in reader.fieldnames}
    if "name" not in fieldnames:
        messages.error(request, _("The CSV must have a 'Name' column."))
        return redirect("shop_list")

    category_lookup = {}
    for value, label in ShopCategory.choices:
        category_lookup[value.lower()] = value
        category_lookup[str(label).lower()] = value

    existing_names = {n.lower() for n in request.user.shops.values_list("name", flat=True)}
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
        category = category_lookup.get(_row_value(row, fieldnames, "category").lower(), ShopCategory.OTHER)

        raw_balance = _row_value(row, fieldnames, "opening balance") or _row_value(row, fieldnames, "opening_balance")
        try:
            opening_balance = Decimal(raw_balance) if raw_balance else Decimal("0")
        except InvalidOperation:
            opening_balance = Decimal("0")

        shop = Shop.objects.create(
            user=request.user, name=name, phone=phone, note=note, category=category
        )
        if opening_balance > 0:
            Transaction.objects.create(
                shop=shop,
                transaction_type=Transaction.PURCHASE,
                amount=opening_balance,
                date=today,
                note=_("Opening balance (imported)"),
            )

        existing_names.add(name.lower())
        created += 1

    if created:
        messages.success(request, _("Imported %(count)s shop(s).") % {"count": created})
    skipped_total = skipped_duplicate + skipped_blank
    if skipped_total:
        messages.warning(
            request,
            _("Skipped %(count)s row(s): %(dup)s duplicate name(s), %(blank)s blank name(s).")
            % {"count": skipped_total, "dup": skipped_duplicate, "blank": skipped_blank},
        )
    if not created and not skipped_total:
        messages.error(request, _("No rows found to import."))

    return redirect("shop_list")


@login_required
def transaction_edit_view(request, pk):
    transaction = get_object_or_404(Transaction, pk=pk, shop__user=request.user)
    shop = transaction.shop
    if request.method == "POST":
        form = TransactionForm(request.POST, instance=transaction)
        if form.is_valid():
            form.save()
            messages.success(request, _("Transaction updated."))
            return redirect("shop_detail", pk=shop.pk)
    else:
        form = TransactionForm(instance=transaction)
    return render(request, "shops/shop_form.html", {"form": form, "title": _("Edit Transaction"), "back_url": f"/shops/{shop.pk}/"})


@login_required
def transaction_delete_view(request, pk):
    transaction = get_object_or_404(Transaction, pk=pk, shop__user=request.user)
    shop = transaction.shop
    amount = transaction.amount
    transaction.delete()
    messages.success(request, _("Transaction of ৳%(amount)s deleted.") % {"amount": amount})
    return redirect("shop_detail", pk=shop.pk)
