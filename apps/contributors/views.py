import csv
from datetime import date as date_cls
from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse
import django.utils.timezone
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Q, DecimalField, Value
from django.db.models.functions import Coalesce, TruncMonth
from django.utils import dateformat
from django.utils.translation import gettext as _
from .models import Contributor, ContributorCategory, Contribution
from .forms import ContributorForm, ContributionForm

MONTH_CHOICES = [(i, date_cls(2000, i, 1)) for i in range(1, 13)]


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

    contributors = contributors_base_qs.annotate(
        total_amount=Coalesce(
            Sum("contributions__amount"),
            Value(0, output_field=DecimalField()),
        )
    )

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

    context = {
        "contributors": contributors,
        "total_contributors": total_contributors,
        "total_contribution_amount": total_contribution_amount,
        "avg_contribution": avg_contribution,
        "selected_categories": selected_categories,
        "category_choices": ContributorCategory.choices,
        "filter_type": filter_type,
        "search_query": search_query,
    }
    return render(request, 'contributors/contributor_list.html', context)

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
def contribution_delete(request, pk):
    contribution = get_object_or_404(Contribution, pk=pk, contributor__user=request.user)
    contributor_pk = contribution.contributor.pk
    contribution.delete()
    return redirect('contributor_detail', pk=contributor_pk)
