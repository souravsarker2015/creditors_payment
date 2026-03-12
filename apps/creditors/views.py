from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum, Q, DecimalField, Value
from django.db.models.functions import Coalesce

from .models import Creditor, Transaction


def signup_view(request):
    if request.method == "POST":
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, f"Welcome {user.username}! Your account has been created.")
            return redirect("dashboard")
    else:
        form = UserCreationForm()
    return render(request, "creditors/signup.html", {"form": form})


def login_view(request):
    if request.method == "POST":
        form = AuthenticationForm(data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            return redirect("dashboard")
    else:
        form = AuthenticationForm()
    return render(request, "creditors/login.html", {"form": form})


def logout_view(request):
    logout(request)
    return redirect("login")


@login_required
def dashboard_view(request):
    # Summary stats for the current user
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
    
    # Recent activity
    recent_transactions = Transaction.objects.filter(
        creditor__user=request.user
    ).select_related("creditor").order_by("-date", "-created_at")[:10]
    
    context = {
        "total_borrowed": total_borrowed,
        "total_paid": total_paid,
        "remaining": remaining,
        "chart_paid": float(total_paid),
        "chart_remaining": float(remaining) if remaining > 0 else 0,
        "recent_transactions": recent_transactions,
    }
    return render(request, "creditors/dashboard.html", context)


@login_required
def creditor_list_view(request):
    creditors_qs = request.user.creditors.annotate(
        _borrowed=Coalesce(
            Sum("transactions__amount", filter=Q(transactions__transaction_type=Transaction.BORROW)),
            Value(0, output_field=DecimalField()),
        ),
        _paid=Coalesce(
            Sum("transactions__amount", filter=Q(transactions__transaction_type=Transaction.REPAY)),
            Value(0, output_field=DecimalField()),
        ),
    ).order_by("name")
    
    # Calculate progress percentage manually to avoid complex template logic
    for cr in creditors_qs:
        if cr._borrowed > 0:
            cr.payment_percent = min(100, int((cr._paid / cr._borrowed) * 100))
        else:
            cr.payment_percent = 0
            
    return render(request, "creditors/creditor_list.html", {"creditors": creditors_qs})
