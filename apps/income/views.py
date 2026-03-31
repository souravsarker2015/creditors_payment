from django.shortcuts import render, redirect, get_object_or_404
import django.utils.timezone
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum, Q, DecimalField, Value
from django.db.models.functions import Coalesce

from .models import IncomeSource, IncomeTransaction
from .forms import IncomeSourceForm, IncomeTransactionForm


@login_required
def dashboard_view(request):
    """Summary of all income for the user."""
    stats = request.user.income_sources.aggregate(
        total_income=Coalesce(
            Sum("transactions__amount"),
            Value(0, output_field=DecimalField()),
        )
    )
    
    total_income = stats["total_income"]
    
    # Source-wise breakdown
    sources_qs = request.user.income_sources.annotate(
        s_income=Coalesce(Sum("transactions__amount"), Value(0, output_field=DecimalField()))
    )
    
    source_labels = [s.name for s in sources_qs if s.s_income > 0]
    source_data = [float(s.s_income) for s in sources_qs if s.s_income > 0]
    
    recent_transactions = IncomeTransaction.objects.filter(
        source__user=request.user
    ).select_related("source").order_by("-date", "-created_at")[:10]
    
    context = {
        "total_income": total_income,
        "source_labels": source_labels,
        "source_data": source_data,
        "recent_transactions": recent_transactions,
    }
    return render(request, "income/dashboard.html", context)


@login_required
def income_source_list_view(request):
    sources = request.user.income_sources.annotate(
        total_amt=Coalesce(Sum("transactions__amount"), Value(0, output_field=DecimalField()))
    ).order_by("-total_amt")
    return render(request, "income/source_list.html", {"sources": sources})


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
    transactions = source.transactions.all().order_by("-date", "-created_at")
    
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
        
    total_source_income = source.total_income
    
    context = {
        "source": source,
        "transactions": transactions,
        "form": form,
        "total_source_income": total_source_income,
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
