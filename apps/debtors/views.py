from django.shortcuts import render, redirect, get_object_or_404
import django.utils.timezone
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum, Q, DecimalField, Value
from django.db.models.functions import Coalesce

from .models import Debtor, Transaction
from .forms import DebtorForm, TransactionForm


@login_required
def dashboard_view(request):
    # Global summary stats for the current user
    stats = request.user.debtors.aggregate(
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
    debtors_qs = request.user.debtors.annotate(
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
    recent_transactions = Transaction.objects.filter(
        debtor__user=request.user
    ).select_related("debtor").order_by("-date", "-created_at")[:10]
    
    context = {
        "total_lent": total_lent,
        "total_received": total_received,
        "remaining": remaining,
        "debtor_labels": debtor_labels,
        "debtor_remaining": debtor_remaining,
        "debtor_received": debtor_received,
        "recent_transactions": recent_transactions,
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
            messages.success(request, f"Debtor '{debtor.name}' added successfully.")
            return redirect("debtor_list")
    else:
        form = DebtorForm()
    return render(request, "debtors/debtor_form.html", {"form": form, "title": "Add New Debtor"})


@login_required
def debtor_edit_view(request, pk):
    debtor = get_object_or_404(Debtor, pk=pk, user=request.user)
    if request.method == "POST":
        form = DebtorForm(request.POST, instance=debtor)
        if form.is_valid():
            form.save()
            messages.success(request, f"Debtor '{debtor.name}' updated successfully.")
            return redirect("debtor_list")
    else:
        form = DebtorForm(instance=debtor)
    return render(request, "debtors/debtor_form.html", {"form": form, "title": f"Edit {debtor.name}"})


@login_required
def debtor_detail_view(request, pk):
    debtor = get_object_or_404(Debtor, pk=pk, user=request.user)
    transactions = debtor.transactions.all().order_by("-date", "-created_at")
    
    if request.method == "POST":
        form = TransactionForm(request.POST)
        if form.is_valid():
            transaction = form.save(commit=False)
            transaction.debtor = debtor
            transaction.save()
            messages.success(request, f"Transaction of ৳{transaction.amount} added.")
            return redirect("debtor_detail", pk=pk)
    else:
        form = TransactionForm(initial={"date": django.utils.timezone.now().date()})
    
    # Calculate totals for this specific debtor
    stats = debtor.transactions.aggregate(
        lent=Coalesce(Sum("amount", filter=Q(transaction_type=Transaction.LEND)), Value(0, output_field=DecimalField())),
        received=Coalesce(Sum("amount", filter=Q(transaction_type=Transaction.RECEIVE)), Value(0, output_field=DecimalField())),
    )
    remaining = stats["lent"] - stats["received"]
    
    context = {
        "debtor": debtor,
        "transactions": transactions,
        "form": form,
        "lent": stats["lent"],
        "received": stats["received"],
        "remaining": remaining,
        "chart_received": float(stats["received"]),
        "chart_remaining": float(remaining) if remaining > 0 else 0,
    }
    return render(request, "debtors/debtor_detail.html", context)


@login_required
def debtor_list_view(request):
    debtors_qs = request.user.debtors.annotate(
        total_lent_amt=Coalesce(
            Sum("transactions__amount", filter=Q(transactions__transaction_type=Transaction.LEND)),
            Value(0, output_field=DecimalField()),
        ),
        total_received_amt=Coalesce(
            Sum("transactions__amount", filter=Q(transactions__transaction_type=Transaction.RECEIVE)),
            Value(0, output_field=DecimalField()),
        ),
    ).order_by("name")
    
    # Calculate progress percentage
    for dr in debtors_qs:
        if dr.total_lent_amt > 0:
            dr.received_percent = min(100, int((dr.total_received_amt / dr.total_lent_amt) * 100))
        else:
            dr.received_percent = 0
            

@login_required
def transaction_edit_view(request, pk):
    transaction = get_object_or_404(Transaction, pk=pk, debtor__user=request.user)
    debtor = transaction.debtor
    if request.method == "POST":
        form = TransactionForm(request.POST, instance=transaction)
        if form.is_valid():
            form.save()
            messages.success(request, f"Transaction updated.")
            return redirect("debtor_detail", pk=debtor.pk)
    else:
        form = TransactionForm(instance=transaction)
    return render(request, "debtors/debtor_form.html", {"form": form, "title": "Edit Transaction", "back_url": f"/debtors/{debtor.pk}/"})


@login_required
def transaction_delete_view(request, pk):
    transaction = get_object_or_404(Transaction, pk=pk, debtor__user=request.user)
    debtor = transaction.debtor
    amount = transaction.amount
    transaction.delete()
    messages.success(request, f"Transaction of ৳{amount} deleted.")
    return redirect("debtor_detail", pk=debtor.pk)
