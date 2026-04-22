from django.shortcuts import render, redirect, get_object_or_404
import django.utils.timezone
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum, Q, DecimalField, Value
from django.db.models.functions import Coalesce
from django.core.paginator import Paginator
from datetime import date as date_cls

from .models import ExpenseCategory, Expense
from .forms import ExpenseCategoryForm, ExpenseForm


def _parse_iso_date(value):
    if not value:
        return None
    try:
        return date_cls.fromisoformat(value)
    except ValueError:
        return None


def _get_expense_filters(request, user):
    filter_mode = request.GET.get("filter_mode", "include").strip().lower()
    if filter_mode not in {"include", "exclude"}:
        filter_mode = "include"

    selected_category_ids = []
    for raw in request.GET.getlist("category"):
        try:
            selected_category_ids.append(int(raw))
        except (TypeError, ValueError):
            continue
    selected_category_ids = list(dict.fromkeys(selected_category_ids))

    selected_year = request.GET.get("year", "").strip()
    if selected_year.isdigit():
        selected_year = int(selected_year)
    else:
        selected_year = None

    date_from = _parse_iso_date(request.GET.get("date_from", "").strip())
    date_to = _parse_iso_date(request.GET.get("date_to", "").strip())
    if date_from and date_to and date_from > date_to:
        date_from, date_to = date_to, date_from

    all_categories = user.expense_categories.all().order_by("name")
    valid_category_ids = set(all_categories.values_list("id", flat=True))
    selected_category_ids = [cid for cid in selected_category_ids if cid in valid_category_ids]

    categories_qs = all_categories
    if selected_category_ids:
        if filter_mode == "exclude":
            categories_qs = categories_qs.exclude(id__in=selected_category_ids)
        else:
            categories_qs = categories_qs.filter(id__in=selected_category_ids)

    return {
        "filter_mode": filter_mode,
        "selected_category_ids": selected_category_ids,
        "selected_year": selected_year,
        "date_from": date_from,
        "date_to": date_to,
        "all_categories": all_categories,
        "filtered_categories": categories_qs,
    }


def _apply_date_filters(qs, selected_year=None, date_from=None, date_to=None):
    if selected_year:
        qs = qs.filter(date__year=selected_year)
    if date_from:
        qs = qs.filter(date__gte=date_from)
    if date_to:
        qs = qs.filter(date__lte=date_to)
    return qs


def _apply_category_filters(qs, selected_category_ids=None, filter_mode="include"):
    selected_category_ids = selected_category_ids or []
    if not selected_category_ids:
        return qs
    if filter_mode == "exclude":
        return qs.exclude(category_id__in=selected_category_ids)
    return qs.filter(category_id__in=selected_category_ids)


def _build_pagination_window(page_obj, window=2):
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
    """Summary of all expenses for the user."""
    filters = _get_expense_filters(request, request.user)

    filtered_expenses = _apply_category_filters(
        request.user.expenses.all(),
        selected_category_ids=filters["selected_category_ids"],
        filter_mode=filters["filter_mode"],
    )
    filtered_expenses = _apply_date_filters(
        filtered_expenses,
        selected_year=filters["selected_year"],
        date_from=filters["date_from"],
        date_to=filters["date_to"],
    )

    total_spent = filtered_expenses.aggregate(
        total_spent=Coalesce(Sum("amount"), Value(0, output_field=DecimalField()))
    )["total_spent"]

    category_totals = (
        filtered_expenses.values("category__name")
        .annotate(total=Coalesce(Sum("amount"), Value(0, output_field=DecimalField())))
        .order_by("-total", "category__name")
    )
    category_labels = [row["category__name"] or "General" for row in category_totals if row["total"] > 0]
    category_data = [float(row["total"]) for row in category_totals if row["total"] > 0]

    recent_expenses = filtered_expenses.select_related("category").order_by(
        "-date", "-created_at"
    )[:10]

    year_options = (
        _apply_category_filters(
            request.user.expenses.all(),
            selected_category_ids=filters["selected_category_ids"],
            filter_mode=filters["filter_mode"],
        )
        .values_list("date__year", flat=True)
        .distinct()
        .order_by("-date__year")
    )
    
    context = {
        "total_spent": total_spent,
        "category_labels": category_labels,
        "category_data": category_data,
        "recent_expenses": recent_expenses,
        "available_categories": filters["all_categories"],
        "selected_category_ids": filters["selected_category_ids"],
        "filter_mode": filters["filter_mode"],
        "year_options": year_options,
        "selected_year": filters["selected_year"],
        "date_from": filters["date_from"].isoformat() if filters["date_from"] else "",
        "date_to": filters["date_to"].isoformat() if filters["date_to"] else "",
    }
    return render(request, "expense/dashboard.html", context)


@login_required
def expense_list_view(request):
    filters = _get_expense_filters(request, request.user)

    filtered_expenses = _apply_category_filters(
        request.user.expenses.all(),
        selected_category_ids=filters["selected_category_ids"],
        filter_mode=filters["filter_mode"],
    )
    filtered_expenses = _apply_date_filters(
        filtered_expenses,
        selected_year=filters["selected_year"],
        date_from=filters["date_from"],
        date_to=filters["date_to"],
    ).select_related("category").order_by("-date", "-created_at")

    total_spent = filtered_expenses.aggregate(
        total=Coalesce(Sum("amount"), Value(0, output_field=DecimalField()))
    )["total"]
    total_entries = filtered_expenses.count()
    avg_expense = total_spent / total_entries if total_entries > 0 else 0

    paginator = Paginator(filtered_expenses, 15)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    year_options = (
        _apply_category_filters(
            request.user.expenses.all(),
            selected_category_ids=filters["selected_category_ids"],
            filter_mode=filters["filter_mode"],
        )
        .values_list("date__year", flat=True)
        .distinct()
        .order_by("-date__year")
    )

    context = {
        "expenses": page_obj.object_list,
        "total_spent": total_spent,
        "total_entries": total_entries,
        "avg_expense": avg_expense,
        "page_obj": page_obj,
        "pagination_window": _build_pagination_window(page_obj),
        "available_categories": filters["all_categories"],
        "selected_category_ids": filters["selected_category_ids"],
        "filter_mode": filters["filter_mode"],
        "year_options": year_options,
        "selected_year": filters["selected_year"],
        "date_from": filters["date_from"].isoformat() if filters["date_from"] else "",
        "date_to": filters["date_to"].isoformat() if filters["date_to"] else "",
        "base_query": request.GET.copy(),
    }
    context["base_query"].pop("page", None)
    context["base_query_string"] = context["base_query"].urlencode()
    return render(request, "expense/expense_list.html", context)


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
