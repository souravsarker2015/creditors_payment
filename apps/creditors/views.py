from django.shortcuts import render, redirect, get_object_or_404
import django.utils.timezone
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum, Q, DecimalField, Value
from django.db.models.functions import Coalesce

from .models import Creditor, Transaction


@login_required
def dashboard_view(request):
    # Global summary stats for the current user
    stats = request.user.creditors.aggregate(
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
    creditors_qs = request.user.creditors.annotate(
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
    recent_transactions = Transaction.objects.filter(
        creditor__user=request.user
    ).select_related("creditor").order_by("-date", "-created_at")[:10]
    
    context = {
        "total_borrowed": total_borrowed,
        "total_paid": total_paid,
        "remaining": remaining,
        "creditor_labels": creditor_labels,
        "creditor_remaining": creditor_remaining,
        "creditor_paid": creditor_paid,
        "recent_transactions": recent_transactions,
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
            messages.success(request, f"Creditor '{creditor.name}' added successfully.")
            return redirect("creditor_list")
    else:
        form = CreditorForm()
    return render(request, "creditors/creditor_form.html", {"form": form, "title": "Add New Creditor"})


@login_required
def creditor_edit_view(request, pk):
    creditor = get_object_or_404(Creditor, pk=pk, user=request.user)
    if request.method == "POST":
        form = CreditorForm(request.POST, instance=creditor)
        if form.is_valid():
            form.save()
            messages.success(request, f"Creditor '{creditor.name}' updated successfully.")
            return redirect("creditor_list")
    else:
        form = CreditorForm(instance=creditor)
    return render(request, "creditors/creditor_form.html", {"form": form, "title": f"Edit {creditor.name}"})


@login_required
def creditor_detail_view(request, pk):
    creditor = get_object_or_404(Creditor, pk=pk, user=request.user)
    transactions = creditor.transactions.all().order_by("-date", "-created_at")
    
    if request.method == "POST":
        form = TransactionForm(request.POST)
        if form.is_valid():
            transaction = form.save(commit=False)
            transaction.creditor = creditor
            transaction.save()
            messages.success(request, f"Transaction of ৳{transaction.amount} added.")
            return redirect("creditor_detail", pk=pk)
    else:
        form = TransactionForm(initial={"date": django.utils.timezone.now().date()})
    
    # Calculate totals for this specific creditor
    stats = creditor.transactions.aggregate(
        borrowed=Coalesce(Sum("amount", filter=Q(transaction_type=Transaction.BORROW)), Value(0, output_field=DecimalField())),
        paid=Coalesce(Sum("amount", filter=Q(transaction_type=Transaction.REPAY)), Value(0, output_field=DecimalField())),
    )
    remaining = stats["borrowed"] - stats["paid"]
    
    context = {
        "creditor": creditor,
        "transactions": transactions,
        "form": form,
        "borrowed": stats["borrowed"],
        "paid": stats["paid"],
        "remaining": remaining,
        "chart_paid": float(stats["paid"]),
        "chart_remaining": float(remaining) if remaining > 0 else 0,
    }
    return render(request, "creditors/creditor_detail.html", context)


@login_required
def creditor_list_view(request):
    import django.utils.timezone
    creditors_qs = request.user.creditors.annotate(
        total_borrowed_amt=Coalesce(
            Sum("transactions__amount", filter=Q(transactions__transaction_type=Transaction.BORROW)),
            Value(0, output_field=DecimalField()),
        ),
        total_paid_amt=Coalesce(
            Sum("transactions__amount", filter=Q(transactions__transaction_type=Transaction.REPAY)),
            Value(0, output_field=DecimalField()),
        ),
    ).order_by("name")
    
    # Calculate progress percentage manually to avoid complex template logic
    for cr in creditors_qs:
        if cr.total_borrowed_amt > 0:
            cr.payment_percent = min(100, int((cr.total_paid_amt / cr.total_borrowed_amt) * 100))
        else:
            cr.payment_percent = 0
            

@login_required
def transaction_edit_view(request, pk):
    transaction = get_object_or_404(Transaction, pk=pk, creditor__user=request.user)
    creditor = transaction.creditor
    if request.method == "POST":
        form = TransactionForm(request.POST, instance=transaction)
        if form.is_valid():
            form.save()
            messages.success(request, f"Transaction updated.")
            return redirect("creditor_detail", pk=creditor.pk)
    else:
        form = TransactionForm(instance=transaction)
    return render(request, "creditors/creditor_form.html", {"form": form, "title": "Edit Transaction", "back_url": f"/creditors/{creditor.pk}/"})


@login_required
def transaction_delete_view(request, pk):
    transaction = get_object_or_404(Transaction, pk=pk, creditor__user=request.user)
    creditor = transaction.creditor
    amount = transaction.amount
    transaction.delete()
    messages.success(request, f"Transaction of ৳{amount} deleted.")
    return redirect("creditor_detail", pk=creditor.pk)
