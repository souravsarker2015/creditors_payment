from django.shortcuts import render, redirect, get_object_or_404
import django.utils.timezone
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum, Q, DecimalField, Value
from django.db.models.functions import Coalesce
from datetime import date as date_cls

from .models import IncomeSource, IncomeTransaction
from .forms import IncomeSourceForm, IncomeTransactionForm


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


def _apply_transaction_filters(qs, selected_year=None, date_from=None, date_to=None):
    if selected_year:
        qs = qs.filter(date__year=selected_year)
    if date_from:
        qs = qs.filter(date__gte=date_from)
    if date_to:
        qs = qs.filter(date__lte=date_to)
    return qs


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
    
    context = {
        "total_income": total_income,
        "source_labels": source_labels,
        "source_data": source_data,
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

    sources = filters["filtered_sources"].annotate(
        total_amt=Coalesce(
            Sum("transactions__amount", filter=tx_filter_q),
            Value(0, output_field=DecimalField()),
        )
    ).order_by("-total_amt", "name")

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

    context = {
        "sources": sources,
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
    }
    return render(request, "income/source_list.html", context)


@login_required
def income_source_create_view(request):
    if request.method == "POST":
        form = IncomeSourceForm(request.POST)
        if form.is_valid():
            source = form.save(commit=False)
            source.user = request.user
            source.save()
            messages.success(request, f"Income source '{source.name}' created.")
            return redirect("income_source_list")
    else:
        form = IncomeSourceForm()
    return render(request, "income/source_form.html", {"form": form, "title": "Add Income Source"})


@login_required
def income_source_edit_view(request, pk):
    source = get_object_or_404(IncomeSource, pk=pk, user=request.user)
    if request.method == "POST":
        form = IncomeSourceForm(request.POST, instance=source)
        if form.is_valid():
            form.save()
            messages.success(request, f"Source '{source.name}' updated.")
            return redirect("income_source_list")
    else:
        form = IncomeSourceForm(instance=source)
    return render(request, "income/source_form.html", {"form": form, "title": f"Edit {source.name}"})


@login_required
def income_source_detail_view(request, pk):
    source = get_object_or_404(IncomeSource, pk=pk, user=request.user)
    selected_year = request.GET.get("year", "").strip()
    if selected_year.isdigit():
        selected_year = int(selected_year)
    else:
        selected_year = None
    date_from = _parse_iso_date(request.GET.get("date_from", "").strip())
    date_to = _parse_iso_date(request.GET.get("date_to", "").strip())
    if date_from and date_to and date_from > date_to:
        date_from, date_to = date_to, date_from

    transactions = _apply_transaction_filters(
        source.transactions.all(),
        selected_year=selected_year,
        date_from=date_from,
        date_to=date_to,
    ).order_by("-date", "-created_at")
    
    if request.method == "POST":
        form = IncomeTransactionForm(request.POST)
        if form.is_valid():
            tx = form.save(commit=False)
            tx.source = source
            tx.save()
            messages.success(request, f"Income of ৳{tx.amount} recorded.")
            return redirect("income_source_detail", pk=pk)
    else:
        form = IncomeTransactionForm(initial={"date": django.utils.timezone.now().date()})
        
    total_source_income = transactions.aggregate(
        total=Coalesce(Sum("amount"), Value(0, output_field=DecimalField()))
    )["total"]

    year_options = (
        source.transactions.values_list("date__year", flat=True)
        .distinct()
        .order_by("-date__year")
    )
    
    context = {
        "source": source,
        "transactions": transactions,
        "form": form,
        "total_source_income": total_source_income,
        "year_options": year_options,
        "selected_year": selected_year,
        "date_from": date_from.isoformat() if date_from else "",
        "date_to": date_to.isoformat() if date_to else "",
    }
    return render(request, "income/source_detail.html", context)


@login_required
def transaction_edit_view(request, pk):
    tx = get_object_or_404(IncomeTransaction, pk=pk, source__user=request.user)
    source = tx.source
    if request.method == "POST":
        form = IncomeTransactionForm(request.POST, instance=tx)
        if form.is_valid():
            form.save()
            messages.success(request, "Income entry updated.")
            return redirect("income_source_detail", pk=source.pk)
    else:
        form = IncomeTransactionForm(instance=tx)
    return render(request, "income/source_form.html", {"form": form, "title": "Edit Income Entry", "back_url": f"/income/sources/{source.pk}/"})


@login_required
def transaction_delete_view(request, pk):
    tx = get_object_or_404(IncomeTransaction, pk=pk, source__user=request.user)
    source = tx.source
    amt = tx.amount
    tx.delete()
    messages.success(request, f"Income entry of ৳{amt} deleted.")
    return redirect("income_source_detail", pk=source.pk)
