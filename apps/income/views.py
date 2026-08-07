import csv
import io
from decimal import Decimal, InvalidOperation
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse
import django.utils.timezone
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum, Q, DecimalField, Value
from django.db.models.functions import Coalesce, TruncMonth
from django.core.paginator import Paginator
from django.utils import dateformat
from django.utils.translation import gettext as _
from datetime import date as date_cls

from .models import IncomeSource, IncomeTransaction
from .forms import IncomeSourceForm, IncomeTransactionForm


def _row_value(row, fieldnames, key):
    """Reads a value from a csv.DictReader row by lowercased column name."""
    col = fieldnames.get(key)
    if col is None:
        return ""
    return (row.get(col) or "").strip()

SORT_OPTIONS = [
    ("-amount", _("Total Earned (High to Low)")),
    ("amount", _("Total Earned (Low to High)")),
    ("name", _("Name (A–Z)")),
    ("-name", _("Name (Z–A)")),
]
SORT_FIELDS = {
    "-amount": ["-total_amt", "name"],
    "amount": ["total_amt", "name"],
    "name": ["name"],
    "-name": ["-name"],
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


def _csv_response(filename, header, rows):
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.write("\ufeff")  # UTF-8 BOM so Excel renders Bangla text correctly
    writer = csv.writer(response)
    writer.writerow(header)
    writer.writerows(rows)
    return response


def _parse_iso_date(value):
    if not value:
        return None
    try:
        return date_cls.fromisoformat(value)
    except ValueError:
        return None


def _get_income_filters(request, user):
    filter_mode = request.GET.get("filter_mode", "include").strip().lower()
    if filter_mode not in {"include", "exclude"}:
        filter_mode = "include"

    selected_source_ids = []
    for raw in request.GET.getlist("source"):
        try:
            selected_source_ids.append(int(raw))
        except (TypeError, ValueError):
            continue
    selected_source_ids = list(dict.fromkeys(selected_source_ids))

    selected_year = request.GET.get("year", "").strip()
    if selected_year.isdigit():
        selected_year = int(selected_year)
    else:
        selected_year = None

    date_from = _parse_iso_date(request.GET.get("date_from", "").strip())
    date_to = _parse_iso_date(request.GET.get("date_to", "").strip())
    if date_from and date_to and date_from > date_to:
        date_from, date_to = date_to, date_from

    all_sources = user.income_sources.all().order_by("name")
    valid_source_ids = set(all_sources.values_list("id", flat=True))
    selected_source_ids = [sid for sid in selected_source_ids if sid in valid_source_ids]

    sources_qs = all_sources
    if selected_source_ids:
        if filter_mode == "exclude":
            sources_qs = sources_qs.exclude(id__in=selected_source_ids)
        else:
            sources_qs = sources_qs.filter(id__in=selected_source_ids)

    return {
        "filter_mode": filter_mode,
        "selected_source_ids": selected_source_ids,
        "selected_year": selected_year,
        "date_from": date_from,
        "date_to": date_to,
        "all_sources": all_sources,
        "filtered_sources": sources_qs,
    }


def _apply_transaction_filters(qs, selected_year=None, selected_month=None, date_from=None, date_to=None):
    if selected_year:
        qs = qs.filter(date__year=selected_year)
    if selected_month:
        qs = qs.filter(date__month=selected_month)
    if date_from:
        qs = qs.filter(date__gte=date_from)
    if date_to:
        qs = qs.filter(date__lte=date_to)
    return qs


MONTH_CHOICES = [(i, date_cls(2000, i, 1)) for i in range(1, 13)]


@login_required
def dashboard_view(request):
    """Summary of all income for the user."""
    filters = _get_income_filters(request, request.user)

    filtered_transactions = IncomeTransaction.objects.filter(
        source__in=filters["filtered_sources"]
    )
    filtered_transactions = _apply_transaction_filters(
        filtered_transactions,
        selected_year=filters["selected_year"],
        date_from=filters["date_from"],
        date_to=filters["date_to"],
    )

    total_income = filtered_transactions.aggregate(
        total_income=Coalesce(Sum("amount"), Value(0, output_field=DecimalField()))
    )["total_income"]

    source_totals = (
        filtered_transactions.values("source__name")
        .annotate(total=Coalesce(Sum("amount"), Value(0, output_field=DecimalField())))
        .order_by("-total", "source__name")
    )
    source_labels = [row["source__name"] for row in source_totals if row["total"] > 0]
    source_data = [float(row["total"]) for row in source_totals if row["total"] > 0]

    recent_transactions = filtered_transactions.select_related("source").order_by(
        "-date", "-created_at"
    )[:10]

    year_options = (
        IncomeTransaction.objects.filter(source__in=filters["filtered_sources"])
        .values_list("date__year", flat=True)
        .distinct()
        .order_by("-date__year")
    )

    # Rolling 12-month income trend.
    month_starts = _last_12_month_starts()
    monthly_totals = (
        IncomeTransaction.objects.filter(source__user=request.user, date__gte=month_starts[0])
        .annotate(month=TruncMonth("date"))
        .values("month")
        .annotate(total=Sum("amount"))
    )
    total_by_month = {row["month"]: row["total"] for row in monthly_totals}
    trend_labels = month_starts
    trend_income = [float(total_by_month.get(d, 0) or 0) for d in month_starts]

    context = {
        "total_income": total_income,
        "source_labels": source_labels,
        "source_data": source_data,
        "trend_labels": trend_labels,
        "trend_income": trend_income,
        "recent_transactions": recent_transactions,
        "available_sources": filters["all_sources"],
        "selected_source_ids": filters["selected_source_ids"],
        "filter_mode": filters["filter_mode"],
        "year_options": year_options,
        "selected_year": filters["selected_year"],
        "date_from": filters["date_from"].isoformat() if filters["date_from"] else "",
        "date_to": filters["date_to"].isoformat() if filters["date_to"] else "",
    }
    return render(request, "income/dashboard.html", context)


@login_required
def income_source_list_view(request):
    filters = _get_income_filters(request, request.user)

    tx_filter_q = Q()
    if filters["selected_year"]:
        tx_filter_q &= Q(transactions__date__year=filters["selected_year"])
    if filters["date_from"]:
        tx_filter_q &= Q(transactions__date__gte=filters["date_from"])
    if filters["date_to"]:
        tx_filter_q &= Q(transactions__date__lte=filters["date_to"])

    sort = request.GET.get("sort", "-amount")
    if sort not in SORT_FIELDS:
        sort = "-amount"

    sources = filters["filtered_sources"].annotate(
        total_amt=Coalesce(
            Sum("transactions__amount", filter=tx_filter_q),
            Value(0, output_field=DecimalField()),
        )
    ).order_by(*SORT_FIELDS[sort])

    filtered_transactions = IncomeTransaction.objects.filter(source__in=filters["filtered_sources"])
    filtered_transactions = _apply_transaction_filters(
        filtered_transactions,
        selected_year=filters["selected_year"],
        date_from=filters["date_from"],
        date_to=filters["date_to"],
    )

    total_sources = filters["filtered_sources"].count()
    total_income = filtered_transactions.aggregate(
        total=Coalesce(Sum("amount"), Value(0, output_field=DecimalField()))
    )["total"]
    avg_income = total_income / total_sources if total_sources > 0 else 0

    year_options = (
        IncomeTransaction.objects.filter(source__in=filters["filtered_sources"])
        .values_list("date__year", flat=True)
        .distinct()
        .order_by("-date__year")
    )

    if request.GET.get("export") == "csv":
        rows = [(src.name, src.total_amt) for src in sources]
        return _csv_response(
            "income_sources.csv",
            [_("Source"), _("Total Earned")],
            rows,
        )

    paginator = Paginator(sources, 9)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    base_query = request.GET.copy()
    base_query.pop("page", None)
    base_query_string = base_query.urlencode()

    context = {
        "page_obj": page_obj,
        "pagination_window": _build_pagination_window(page_obj),
        "total_sources": total_sources,
        "total_income": total_income,
        "avg_income": avg_income,
        "available_sources": filters["all_sources"],
        "selected_source_ids": filters["selected_source_ids"],
        "filter_mode": filters["filter_mode"],
        "year_options": year_options,
        "selected_year": filters["selected_year"],
        "date_from": filters["date_from"].isoformat() if filters["date_from"] else "",
        "date_to": filters["date_to"].isoformat() if filters["date_to"] else "",
        "sort": sort,
        "sort_options": SORT_OPTIONS,
        "base_query_string": base_query_string,
    }
    return render(request, "income/source_list.html", context)


@login_required
def income_source_import_template_view(request):
    rows = [(_("Acme Corp Salary"), _("Monthly salary from Acme Corp"), "50000")]
    return _csv_response(
        "income_source_import_template.csv",
        [_("Name"), _("Description"), _("Opening Income")],
        rows,
    )


@login_required
def income_source_import_view(request):
    if request.method != "POST":
        return redirect("income_source_list")

    csv_file = request.FILES.get("csv_file")
    if not csv_file:
        messages.error(request, _("Please choose a CSV file to import."))
        return redirect("income_source_list")

    try:
        decoded = csv_file.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        messages.error(request, _("Could not read that file. Please upload a UTF-8 encoded CSV."))
        return redirect("income_source_list")

    reader = csv.DictReader(io.StringIO(decoded))
    if not reader.fieldnames:
        messages.error(request, _("The CSV file appears to be empty."))
        return redirect("income_source_list")

    fieldnames = {(f or "").strip().lower(): f for f in reader.fieldnames}
    if "name" not in fieldnames:
        messages.error(request, _("The CSV must have a 'Name' column."))
        return redirect("income_source_list")

    existing_names = {n.lower() for n in request.user.income_sources.values_list("name", flat=True)}
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

        description = _row_value(row, fieldnames, "description")

        raw_amount = _row_value(row, fieldnames, "opening income") or _row_value(row, fieldnames, "opening_income")
        try:
            opening_amount = Decimal(raw_amount) if raw_amount else Decimal("0")
        except InvalidOperation:
            opening_amount = Decimal("0")

        source = IncomeSource.objects.create(user=request.user, name=name, description=description)
        if opening_amount > 0:
            IncomeTransaction.objects.create(
                source=source,
                amount=opening_amount,
                date=today,
                note=_("Opening balance (imported)"),
            )

        existing_names.add(name.lower())
        created += 1

    if created:
        messages.success(request, _("Imported %(count)s income source(s).") % {"count": created})
    skipped_total = skipped_duplicate + skipped_blank
    if skipped_total:
        messages.warning(
            request,
            _("Skipped %(count)s row(s): %(dup)s duplicate name(s), %(blank)s blank name(s).")
            % {"count": skipped_total, "dup": skipped_duplicate, "blank": skipped_blank},
        )
    if not created and not skipped_total:
        messages.error(request, _("No rows found to import."))

    return redirect("income_source_list")


@login_required
def income_source_create_view(request):
    if request.method == "POST":
        form = IncomeSourceForm(request.POST)
        if form.is_valid():
            source = form.save(commit=False)
            source.user = request.user
            source.save()
            messages.success(request, _("Income source '%(name)s' created.") % {"name": source.name})
            return redirect("income_source_list")
    else:
        form = IncomeSourceForm()
    return render(request, "income/source_form.html", {"form": form, "title": _("Add Income Source")})


@login_required
def income_source_edit_view(request, pk):
    source = get_object_or_404(IncomeSource, pk=pk, user=request.user)
    if request.method == "POST":
        form = IncomeSourceForm(request.POST, instance=source)
        if form.is_valid():
            form.save()
            messages.success(request, _("Source '%(name)s' updated.") % {"name": source.name})
            return redirect("income_source_list")
    else:
        form = IncomeSourceForm(instance=source)
    return render(request, "income/source_form.html", {"form": form, "title": _("Edit %(name)s") % {"name": source.name}})


@login_required
def income_source_detail_view(request, pk):
    source = get_object_or_404(IncomeSource, pk=pk, user=request.user)
    all_transactions = source.transactions.all()

    selected_year = request.GET.get("year", "").strip()
    selected_year = int(selected_year) if selected_year.isdigit() else None
    raw_month = request.GET.get("month", "").strip()
    selected_month = int(raw_month) if raw_month.isdigit() and 1 <= int(raw_month) <= 12 else None
    date_from = _parse_iso_date(request.GET.get("date_from", "").strip())
    date_to = _parse_iso_date(request.GET.get("date_to", "").strip())
    if date_from and date_to and date_from > date_to:
        date_from, date_to = date_to, date_from

    transactions = _apply_transaction_filters(
        all_transactions,
        selected_year=selected_year,
        selected_month=selected_month,
        date_from=date_from,
        date_to=date_to,
    ).order_by("-date", "-created_at")

    if request.method == "POST":
        form = IncomeTransactionForm(request.POST)
        if form.is_valid():
            tx = form.save(commit=False)
            tx.source = source
            tx.save()
            messages.success(request, _("Income of ৳%(amount)s recorded.") % {"amount": tx.amount})
            return redirect("income_source_detail", pk=pk)
    else:
        form = IncomeTransactionForm(initial={"date": django.utils.timezone.now().date()})

    # All-time cumulative revenue (never period-filtered, a true running total).
    total_source_income = all_transactions.aggregate(
        total=Coalesce(Sum("amount"), Value(0, output_field=DecimalField()))
    )["total"]

    period_income = transactions.aggregate(
        total=Coalesce(Sum("amount"), Value(0, output_field=DecimalField()))
    )["total"]

    year_options = list(
        all_transactions.values_list("date__year", flat=True)
        .distinct()
        .order_by("-date__year")
    )

    if request.GET.get("export") == "csv":
        rows = [(tx.date.isoformat(), tx.amount, tx.note) for tx in transactions]
        return _csv_response(
            f"{source.name}_transactions.csv",
            [_("Date"), _("Amount"), _("Note")],
            rows,
        )

    context = {
        "source": source,
        "transactions": transactions,
        "form": form,
        "total_source_income": total_source_income,
        "period_income": period_income,
        "year_options": year_options,
        "month_choices": MONTH_CHOICES,
        "selected_month": selected_month,
        "selected_month_date": date_cls(2000, selected_month, 1) if selected_month else None,
        "selected_year": selected_year,
        "date_from": date_from.isoformat() if date_from else "",
        "date_to": date_to.isoformat() if date_to else "",
    }
    return render(request, "income/source_detail.html", context)


@login_required
def income_source_statement_view(request, pk):
    source = get_object_or_404(IncomeSource, pk=pk, user=request.user)
    all_transactions = source.transactions.all()

    selected_year = request.GET.get("year", "").strip()
    selected_year = int(selected_year) if selected_year.isdigit() else None
    raw_month = request.GET.get("month", "").strip()
    selected_month = int(raw_month) if raw_month.isdigit() and 1 <= int(raw_month) <= 12 else None
    date_from = _parse_iso_date(request.GET.get("date_from", "").strip())
    date_to = _parse_iso_date(request.GET.get("date_to", "").strip())
    if date_from and date_to and date_from > date_to:
        date_from, date_to = date_to, date_from

    transactions = _apply_transaction_filters(
        all_transactions,
        selected_year=selected_year,
        selected_month=selected_month,
        date_from=date_from,
        date_to=date_to,
    ).order_by("date", "created_at")

    total_source_income = all_transactions.aggregate(
        total=Coalesce(Sum("amount"), Value(0, output_field=DecimalField()))
    )["total"]
    period_income = transactions.aggregate(
        total=Coalesce(Sum("amount"), Value(0, output_field=DecimalField()))
    )["total"]

    if date_from or date_to:
        period_label = f"{date_from.isoformat() if date_from else '…'} – {date_to.isoformat() if date_to else '…'}"
    else:
        period_label = _period_label(selected_year, selected_month)

    rows = [(tx.date.strftime("%d %b %Y"), tx.note or "-", f"{tx.amount:,.2f}") for tx in transactions]

    return _render_statement(
        request,
        entity_label=_("Income Source"),
        entity_name=source.name,
        entity_meta=[(_("Description"), source.description)],
        period_label=period_label,
        summary_rows=[
            (_("Total Earned"), f"{total_source_income:,.2f}", "positive"),
            (_("Earned This Period"), f"{period_income:,.2f}", ""),
        ],
        columns=[_("Date"), _("Note"), _("Amount (৳)")],
        rows=rows,
        back_url=request.META.get("HTTP_REFERER") or f"/income/sources/{source.pk}/",
    )


@login_required
def transaction_edit_view(request, pk):
    tx = get_object_or_404(IncomeTransaction, pk=pk, source__user=request.user)
    source = tx.source
    if request.method == "POST":
        form = IncomeTransactionForm(request.POST, instance=tx)
        if form.is_valid():
            form.save()
            messages.success(request, _("Income entry updated."))
            return redirect("income_source_detail", pk=source.pk)
    else:
        form = IncomeTransactionForm(instance=tx)
    return render(request, "income/source_form.html", {"form": form, "title": _("Edit Income Entry"), "back_url": f"/income/sources/{source.pk}/"})


@login_required
def transaction_delete_view(request, pk):
    tx = get_object_or_404(IncomeTransaction, pk=pk, source__user=request.user)
    source = tx.source
    amt = tx.amount
    tx.delete()
    messages.success(request, _("Income entry of ৳%(amount)s deleted.") % {"amount": amt})
    return redirect("income_source_detail", pk=source.pk)
