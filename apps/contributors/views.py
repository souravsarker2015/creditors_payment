import csv
import io
from decimal import Decimal, InvalidOperation
from datetime import date as date_cls
from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse
import django.utils.timezone
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum, Q, DecimalField, Value
from django.views.decorators.http import require_POST
from django.db.models.functions import Coalesce, TruncMonth
from django.core.paginator import Paginator
from django.utils import dateformat
from django.utils.translation import gettext as _
from .models import Contributor, ContributorCategory, Contribution
from apps.core.status import apply_status_filter, toggle_active
from .forms import ContributorForm, ContributionForm


def _row_value(row, fieldnames, key):
    """Reads a value from a csv.DictReader row by lowercased column name."""
    col = fieldnames.get(key)
    if col is None:
        return ""
    return (row.get(col) or "").strip()

MONTH_CHOICES = [(i, date_cls(2000, i, 1)) for i in range(1, 13)]

SORT_OPTIONS = [
    ("name", _("Name (A–Z)")),
    ("-name", _("Name (Z–A)")),
    ("-amount", _("Total Given (High to Low)")),
    ("amount", _("Total Given (Low to High)")),
]
SORT_FIELDS = {
    "name": ["name"],
    "-name": ["-name"],
    "amount": ["total_amount", "name"],
    "-amount": ["-total_amount", "name"],
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

@login_required
def contributor_dashboard(request):
    valid_filter_types = {"include", "exclude"}
    filter_type = request.GET.get("filter_type", "include").strip().lower()
    if filter_type not in valid_filter_types:
        filter_type = "include"

    selected_categories = [
        category
        for category in request.GET.getlist("category")
        if category in ContributorCategory.values
    ]

    contributors = Contributor.objects.filter(user=request.user)
    if selected_categories:
        if filter_type == "exclude":
            contributors = contributors.exclude(category__in=selected_categories)
        else:
            contributors = contributors.filter(category__in=selected_categories)

    total_contributors = contributors.count()
    
    # Total contributions across all contributors
    total_contribution_amount = contributors.aggregate(
        total=Coalesce(Sum("contributions__amount"), Value(0, output_field=DecimalField()))
    )["total"]
    
    # Data for the chart: Top contributors
    top_contributors = contributors.annotate(
        total_amount=Coalesce(
            Sum("contributions__amount"),
            Value(0, output_field=DecimalField()),
        )
    ).order_by('-total_amount')[:10]
    
    chart_labels = [c.name for c in top_contributors if c.total_amount]
    chart_data = [float(c.total_amount) for c in top_contributors if c.total_amount]

    avg_contribution = total_contribution_amount / total_contributors if total_contributors > 0 else 0

    # Rolling 12-month contributions trend.
    month_starts = _last_12_month_starts()
    monthly_totals = (
        Contribution.objects.filter(contributor__user=request.user, date__gte=month_starts[0])
        .annotate(month=TruncMonth("date"))
        .values("month")
        .annotate(total=Sum("amount"))
    )
    total_by_month = {row["month"]: row["total"] for row in monthly_totals}
    trend_labels = month_starts
    trend_amount = [float(total_by_month.get(d, 0) or 0) for d in month_starts]

    context = {
        'total_contributors': total_contributors,
        'total_contribution_amount': total_contribution_amount,
        'avg_contribution': avg_contribution,
        'chart_labels': chart_labels,
        'chart_data': chart_data,
        'trend_labels': trend_labels,
        'trend_amount': trend_amount,
        'recent_contributions': Contribution.objects.filter(
            contributor__user=request.user
        ).filter(
            Q() if not selected_categories else (
                ~Q(contributor__category__in=selected_categories)
                if filter_type == "exclude"
                else Q(contributor__category__in=selected_categories)
            )
        ).select_related('contributor').order_by('-date', '-created_at')[:10],
        "selected_categories": selected_categories,
        "category_choices": ContributorCategory.choices,
        "filter_type": filter_type,
    }
    return render(request, 'contributors/dashboard.html', context)

@login_required
def contributor_list(request):
    valid_filter_types = {"include", "exclude"}
    filter_type = request.GET.get("filter_type", "include").strip().lower()
    if filter_type not in valid_filter_types:
        filter_type = "include"

    selected_categories = [
        category
        for category in request.GET.getlist("category")
        if category in ContributorCategory.values
    ]

    search_query = request.GET.get("q", "").strip()

    contributors_base_qs = Contributor.objects.filter(user=request.user)
    if selected_categories:
        if filter_type == "exclude":
            contributors_base_qs = contributors_base_qs.exclude(category__in=selected_categories)
        else:
            contributors_base_qs = contributors_base_qs.filter(category__in=selected_categories)

    if search_query:
        contributors_base_qs = contributors_base_qs.filter(name__icontains=search_query)

    status, contributors_base_qs, status_counts = apply_status_filter(request, contributors_base_qs)

    sort = request.GET.get("sort", "name")
    if sort not in SORT_FIELDS:
        sort = "name"
    contributors = contributors_base_qs.annotate(
        total_amount=Coalesce(
            Sum("contributions__amount"),
            Value(0, output_field=DecimalField()),
        )
    ).order_by(*SORT_FIELDS[sort])

    total_contributors = contributors_base_qs.count()
    total_contribution_amount = contributors_base_qs.aggregate(
        total=Coalesce(Sum("contributions__amount"), Value(0, output_field=DecimalField()))
    )["total"]
    avg_contribution = (
        total_contribution_amount / total_contributors if total_contributors > 0 else 0
    )

    if request.GET.get("export") == "csv":
        rows = [(c.name, c.get_category_display(), c.total_amount) for c in contributors]
        return _csv_response(
            "contributors.csv",
            [_("Contributor"), _("Category"), _("Total Given")],
            rows,
        )

    paginator = Paginator(contributors, 9)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    base_query = request.GET.copy()
    base_query.pop("page", None)
    base_query_string = base_query.urlencode()

    context = {
        "page_obj": page_obj,
        "pagination_window": _build_pagination_window(page_obj),
        "total_contributors": total_contributors,
        "total_contribution_amount": total_contribution_amount,
        "avg_contribution": avg_contribution,
        "selected_categories": selected_categories,
        "category_choices": ContributorCategory.choices,
        "filter_type": filter_type,
        "search_query": search_query,
        "status": status,
        "status_counts": status_counts,
        "sort": sort,
        "sort_options": SORT_OPTIONS,
        "base_query_string": base_query_string,
    }
    return render(request, 'contributors/contributor_list.html', context)


@login_required
def contributor_import_template_view(request):
    rows = [(_("Sajal Saha"), "01711000000", _("Sponsor"), _("Monthly sponsor"), "1000")]
    return _csv_response(
        "contributor_import_template.csv",
        [_("Name"), _("Phone"), _("Category"), _("Note"), _("Opening Contribution")],
        rows,
    )


@login_required
def contributor_import_view(request):
    if request.method != "POST":
        return redirect("contributor_list")

    csv_file = request.FILES.get("csv_file")
    if not csv_file:
        messages.error(request, _("Please choose a CSV file to import."))
        return redirect("contributor_list")

    try:
        decoded = csv_file.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        messages.error(request, _("Could not read that file. Please upload a UTF-8 encoded CSV."))
        return redirect("contributor_list")

    reader = csv.DictReader(io.StringIO(decoded))
    if not reader.fieldnames:
        messages.error(request, _("The CSV file appears to be empty."))
        return redirect("contributor_list")

    fieldnames = {(f or "").strip().lower(): f for f in reader.fieldnames}
    if "name" not in fieldnames:
        messages.error(request, _("The CSV must have a 'Name' column."))
        return redirect("contributor_list")

    category_lookup = {}
    for value, label in ContributorCategory.choices:
        category_lookup[value.lower()] = value
        category_lookup[str(label).lower()] = value

    existing_names = {n.lower() for n in Contributor.objects.filter(user=request.user).values_list("name", flat=True)}
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
        category = category_lookup.get(_row_value(row, fieldnames, "category").lower(), ContributorCategory.OTHER)

        raw_amount = _row_value(row, fieldnames, "opening contribution") or _row_value(row, fieldnames, "opening_contribution")
        try:
            opening_amount = Decimal(raw_amount) if raw_amount else Decimal("0")
        except InvalidOperation:
            opening_amount = Decimal("0")

        contributor = Contributor.objects.create(
            user=request.user, name=name, phone=phone, note=note, category=category
        )
        if opening_amount > 0:
            Contribution.objects.create(
                contributor=contributor,
                amount=opening_amount,
                date=today,
                note=_("Opening balance (imported)"),
            )

        existing_names.add(name.lower())
        created += 1

    if created:
        messages.success(request, _("Imported %(count)s contributor(s).") % {"count": created})
    skipped_total = skipped_duplicate + skipped_blank
    if skipped_total:
        messages.warning(
            request,
            _("Skipped %(count)s row(s): %(dup)s duplicate name(s), %(blank)s blank name(s).")
            % {"count": skipped_total, "dup": skipped_duplicate, "blank": skipped_blank},
        )
    if not created and not skipped_total:
        messages.error(request, _("No rows found to import."))

    return redirect("contributor_list")


@login_required
def contributor_create(request):
    if request.method == 'POST':
        form = ContributorForm(request.POST)
        if form.is_valid():
            contributor = form.save(commit=False)
            contributor.user = request.user
            contributor.save()
            return redirect('contributor_list')
    else:
        form = ContributorForm()
    return render(request, 'contributors/contributor_form.html', {'form': form, 'title': _('Add Contributor')})

@login_required
def contributor_update(request, pk):
    contributor = get_object_or_404(Contributor, pk=pk, user=request.user)
    if request.method == 'POST':
        form = ContributorForm(request.POST, instance=contributor)
        if form.is_valid():
            form.save()
            return redirect('contributor_list')
    else:
        form = ContributorForm(instance=contributor)
    return render(request, 'contributors/contributor_form.html', {'form': form, 'title': _('Edit Contributor')})

@login_required
def contributor_delete(request, pk):
    contributor = get_object_or_404(Contributor, pk=pk, user=request.user)
    if request.method == 'POST':
        contributor.delete()
        return redirect('contributor_list')
    return render(request, 'contributors/contributor_confirm_delete.html', {'contributor': contributor})

@login_required
def contributor_detail(request, pk):
    contributor = get_object_or_404(Contributor, pk=pk, user=request.user)
    all_contributions = contributor.contributions.all()

    # All-time totals (never period-filtered).
    total_amount = all_contributions.aggregate(Sum('amount'))['amount__sum'] or 0
    total_count = all_contributions.count()
    avg_amount = total_amount / total_count if total_count > 0 else 0

    if request.method == 'POST':
        form = ContributionForm(request.POST)
        if form.is_valid():
            contribution = form.save(commit=False)
            contribution.contributor = contributor
            contribution.save()
            return redirect('contributor_detail', pk=pk)
    else:
        form = ContributionForm()

    selected_year, selected_month = _parse_year_month(request)
    contributions = all_contributions
    if selected_year:
        contributions = contributions.filter(date__year=selected_year)
    if selected_month:
        contributions = contributions.filter(date__month=selected_month)
    contributions = contributions.order_by('-date')

    period_amount = contributions.aggregate(Sum('amount'))['amount__sum'] or 0
    year_options = list(all_contributions.values_list('date__year', flat=True).distinct().order_by('-date__year'))

    if request.GET.get('export') == 'csv':
        rows = [(c.date.isoformat(), c.note or '', c.amount) for c in contributions]
        return _csv_response(
            f"{contributor.name}_contributions.csv",
            [_("Date"), _("Note"), _("Amount")],
            rows,
        )

    context = {
        'contributor': contributor,
        'contributions': contributions,
        'total_amount': total_amount,
        'total_count': total_count,
        'avg_amount': avg_amount,
        'period_amount': period_amount,
        'year_options': year_options,
        'month_choices': MONTH_CHOICES,
        'selected_year': selected_year,
        'selected_month': selected_month,
        'selected_month_date': date_cls(2000, selected_month, 1) if selected_month else None,
        'form': form,
    }
    return render(request, 'contributors/contributor_detail.html', context)

@login_required
def contributor_statement_view(request, pk):
    contributor = get_object_or_404(Contributor, pk=pk, user=request.user)
    all_contributions = contributor.contributions.all()

    selected_year, selected_month = _parse_year_month(request)
    contributions = all_contributions
    if selected_year:
        contributions = contributions.filter(date__year=selected_year)
    if selected_month:
        contributions = contributions.filter(date__month=selected_month)
    contributions = contributions.order_by('date')

    total_amount = all_contributions.aggregate(Sum('amount'))['amount__sum'] or 0
    period_amount = contributions.aggregate(Sum('amount'))['amount__sum'] or 0

    rows = [(c.date.strftime("%d %b %Y"), c.note or "-", f"{c.amount:,.2f}") for c in contributions]

    return _render_statement(
        request,
        entity_label=_("Contributor"),
        entity_name=contributor.name,
        entity_meta=[(_("Phone"), contributor.phone), (_("Category"), contributor.get_category_display())],
        period_label=_period_label(selected_year, selected_month),
        summary_rows=[
            (_("Total Given"), f"{total_amount:,.2f}", "positive"),
            (_("Given This Period"), f"{period_amount:,.2f}", ""),
        ],
        columns=[_("Date"), _("Note"), _("Amount (৳)")],
        rows=rows,
        back_url=request.META.get("HTTP_REFERER") or f"/contributors/{contributor.pk}/",
    )

@login_required
def contribution_update(request, pk):
    contribution = get_object_or_404(Contribution, pk=pk, contributor__user=request.user)
    contributor = contribution.contributor
    if request.method == 'POST':
        form = ContributionForm(request.POST, instance=contribution)
        if form.is_valid():
            form.save()
            return redirect('contributor_detail', pk=contributor.pk)
    else:
        form = ContributionForm(instance=contribution)
    return render(request, 'contributors/contribution_form.html', {
        'form': form,
        'title': _('Edit Record'),
        'contributor': contributor
    })

@login_required
@require_POST
def contribution_delete(request, pk):
    contribution = get_object_or_404(Contribution, pk=pk, contributor__user=request.user)
    contributor_pk = contribution.contributor.pk
    contribution.delete()
    return redirect('contributor_detail', pk=contributor_pk)


@login_required
@require_POST
def contributor_toggle_active_view(request, pk):
    obj = get_object_or_404(Contributor, pk=pk, user=request.user)
    return toggle_active(request, obj, "contributor_list")
