from django.shortcuts import render, redirect, get_object_or_404
import django.utils.timezone
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum, Q, DecimalField, Value
from django.db.models.functions import Coalesce

from .models import ExpenseCategory, Expense
from .forms import ExpenseCategoryForm, ExpenseForm


@login_required
def dashboard_view(request):
    """Summary of all expenses for the user."""
    categories_qs = request.user.expense_categories.annotate(
        total=Coalesce(Sum("expenses__amount"), Value(0, output_field=DecimalField()))
    )
    
    total_spent = request.user.expenses.aggregate(total_spent=Coalesce(Sum("amount"), Value(0, output_field=DecimalField())))["total_spent"]
    
    category_labels = [c.name for c in categories_qs if c.total > 0]
    category_data = [float(c.total) for c in categories_qs if c.total > 0]
    
    recent_expenses = request.user.expenses.select_related("category").order_by("-date", "-created_at")[:10]
    
    context = {
        "total_spent": total_spent,
        "category_labels": category_labels,
        "category_data": category_data,
        "recent_expenses": recent_expenses,
    }
    return render(request, "expense/dashboard.html", context)


@login_required
def expense_list_view(request):
    expenses = request.user.expenses.select_related("category").order_by("-date", "-created_at")
    return render(request, "expense/expense_list.html", {"expenses": expenses})


@login_required
def expense_create_view(request):
    if request.method == "POST":
        form = ExpenseForm(request.POST, user=request.user)
        if form.is_valid():
            expense = form.save(commit=False)
            expense.user = request.user
            expense.save()
            messages.success(request, f"Expense of ৳{expense.amount} recorded.")
            return redirect("expense_list")
    else:
        form = ExpenseForm(user=request.user, initial={"date": django.utils.timezone.now().date()})
    return render(request, "expense/expense_form.html", {"form": form, "title": "Add New Expense"})


@login_required
def expense_edit_view(request, pk):
    expense = get_object_or_404(Expense, pk=pk, user=request.user)
    if request.method == "POST":
        form = ExpenseForm(request.POST, instance=expense, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Expense updated.")
            return redirect("expense_list")
    else:
        form = ExpenseForm(instance=expense, user=request.user)
    return render(request, "expense/expense_form.html", {"form": form, "title": "Edit Expense"})


@login_required
def expense_delete_view(request, pk):
    expense = get_object_or_404(Expense, pk=pk, user=request.user)
    amt = expense.amount
    expense.delete()
    messages.success(request, f"Expense of ৳{amt} deleted.")
    return redirect("expense_list")


@login_required
def category_list_view(request):
    categories = request.user.expense_categories.annotate(
        total_amt=Coalesce(Sum("expenses__amount"), Value(0, output_field=DecimalField()))
    ).order_by("-total_amt")
    return render(request, "expense/category_list.html", {"categories": categories})


@login_required
def category_create_view(request):
    if request.method == "POST":
        form = ExpenseCategoryForm(request.POST)
        if form.is_valid():
            cat = form.save(commit=False)
            cat.user = request.user
            cat.save()
            messages.success(request, f"Category '{cat.name}' created.")
            return redirect("category_list")
    else:
        form = ExpenseCategoryForm()
    return render(request, "expense/expense_form.html", {"form": form, "title": "Add Category"})
