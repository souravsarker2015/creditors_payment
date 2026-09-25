import csv
import io
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse
import django.utils.timezone
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.db.models import Count, Sum, Q, DecimalField, Value
from django.db.models.functions import Coalesce, TruncMonth
from django.core.paginator import Paginator
from django.utils.translation import gettext as _, gettext_lazy, ngettext
from datetime import date as date_cls

from .models import ExpenseCategory, Expense, RecurringExpense, generate_due_recurring_expense
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from apps.core.stats import month_compare, ranked, trend_summary
from apps.core.status import apply_status_filter, active_or_current, toggle_active
from .forms import ExpenseCategoryForm, ExpenseForm, RecurringExpenseForm

SORT_OPTIONS = [
    ("-date", gettext_lazy("Date (Newest First)")),
    ("date", gettext_lazy("Date (Oldest First)")),
    ("-amount", gettext_lazy("Amount (High to Low)")),
    ("amount", gettext_lazy("Amount (Low to High)")),
]
SORT_FIELDS = {
    "-date": ["-date", "-created_at"],
    "date": ["date", "created_at"],
    "-amount": ["-amount"],
    "amount": ["amount"],
}


def _csv_response(filename, header, rows):
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.write("\ufeff")  # UTF-8 BOM so Excel renders Bangla text correctly
    writer = csv.writer(response)
    writer.writerow(header)
    writer.writerows(rows)
    return response


def _row_value(row, fieldnames, key):
    """Reads a value from a csv.DictReader row by lowercased column name."""
    col = fieldnames.get(key)
    if col is None:
        return ""
    return (row.get(col) or "").strip()


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
    generated = generate_due_recurring_expense(request.user)
    if generated:
        messages.info(request, ngettext(
            "%(count)s recurring expense entry was generated automatically.",
            "%(count)s recurring expense entries were generated automatically.",
            generated,
        ) % {"count": generated})

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
    category_labels = [row["category__name"] or _("General") for row in category_totals if row["total"] > 0]
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

    # Rolling 12-month expense trend (respects the current category filter).
    month_starts = _last_12_month_starts()
    trend_base = _apply_category_filters(
        request.user.expenses.all(),
        selected_category_ids=filters["selected_category_ids"],
        filter_mode=filters["filter_mode"],
    ).filter(date__gte=month_starts[0])
    monthly_totals = (
        trend_base.annotate(month=TruncMonth("date"))
        .values("month")
        .annotate(total=Sum("amount"))
    )
    total_by_month = {row["month"]: row["total"] for row in monthly_totals}
    trend_labels = month_starts
    trend_spent = [float(total_by_month.get(d, 0) or 0) for d in month_starts]

    # Category-filtered (but not date-filtered) base for the month figures,
    # so "this month" always means the calendar month.
    category_base = _apply_category_filters(
        request.user.expenses.all(),
        selected_category_ids=filters["selected_category_ids"],
        filter_mode=filters["filter_mode"],
    )
    list_url = reverse("expense_list")
    category_rank = ranked([
        (row["category__name"] or _("General"), row["total"],
         f"{list_url}?category={row['category__id']}" if row["category__id"] else None)
        for row in filtered_expenses.values("category__id", "category__name").annotate(total=Sum("amount"))
    ])
    entry_count = filtered_expenses.count()
    today = timezone.localdate()

    context = {
        "total_spent": total_spent,
        "entry_count": entry_count,
        "avg_entry": total_spent / entry_count if entry_count else 0,
        "month": month_compare(category_base),
        "largest": filtered_expenses.select_related("category").order_by("-amount", "-date").first(),
        "category_rank": category_rank,
        "trend_summary": trend_summary(trend_spent, month_starts),
        "today": today,
        "upcoming": request.user.recurring_expenses.filter(
            is_active=True, next_run_date__lte=today + timedelta(days=30)
        ).select_related("category").order_by("next_run_date")[:5],
        "is_filtered": bool(filters["selected_category_ids"] or filters["selected_year"] or filters["date_from"] or filters["date_to"]),
        "category_labels": category_labels,
        "category_data": category_data,
        "trend_labels": trend_labels,
        "trend_spent": trend_spent,
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
    generate_due_recurring_expense(request.user)

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

    sort = request.GET.get("sort", "-date")
    if sort not in SORT_FIELDS:
        sort = "-date"
    filtered_expenses = filtered_expenses.select_related("category").order_by(*SORT_FIELDS[sort])

    total_spent = filtered_expenses.aggregate(
        total=Coalesce(Sum("amount"), Value(0, output_field=DecimalField()))
    )["total"]
    total_entries = filtered_expenses.count()
    avg_expense = total_spent / total_entries if total_entries > 0 else 0

    if request.GET.get("export") == "csv":
        rows = [
            (ex.date.isoformat(), ex.category.name if ex.category else _("General"), ex.amount, ex.note)
            for ex in filtered_expenses
        ]
        return _csv_response(
            "expenses.csv",
            [_("Date"), _("Category"), _("Amount"), _("Note")],
            rows,
        )

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
        "sort": sort,
        "sort_options": SORT_OPTIONS,
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
            messages.success(request, _("Expense of ৳%(amount)s recorded.") % {"amount": expense.amount})
            return redirect("expense_list")
    else:
        form = ExpenseForm(user=request.user, initial={"date": django.utils.timezone.now().date()})
    return render(request, "expense/expense_form.html", {"form": form, "title": _("Add New Expense")})


@login_required
def expense_edit_view(request, pk):
    expense = get_object_or_404(Expense, pk=pk, user=request.user)
    if request.method == "POST":
        form = ExpenseForm(request.POST, instance=expense, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, _("Expense updated."))
            return redirect("expense_list")
    else:
        form = ExpenseForm(instance=expense, user=request.user)
    return render(request, "expense/expense_form.html", {"form": form, "title": _("Edit Expense")})


@login_required
@require_POST
def expense_delete_view(request, pk):
    expense = get_object_or_404(Expense, pk=pk, user=request.user)
    amt = expense.amount
    expense.delete()
    messages.success(request, _("Expense of ৳%(amount)s deleted.") % {"amount": amt})
    return redirect("expense_list")


@login_required
def category_list_view(request):
    search_query = request.GET.get("q", "").strip()
    categories = request.user.expense_categories.all()
    if search_query:
        categories = categories.filter(name__icontains=search_query)
    status, categories, status_counts = apply_status_filter(request, categories)
    categories = list(categories.annotate(
        total_amt=Coalesce(Sum("expenses__amount"), Value(0, output_field=DecimalField())),
        entry_count=Count("expenses"),
    ).order_by("-total_amt", "name"))
    top_total = max((c.total_amt for c in categories), default=0)
    for c in categories:
        c.share_percent = int((c.total_amt / top_total) * 100) if top_total else 0
    return render(request, "expense/category_list.html", {
        "categories": categories,
        "search_query": search_query,
        "status": status,
        "status_counts": status_counts,
    })


@login_required
def category_create_view(request):
    if request.method == "POST":
        form = ExpenseCategoryForm(request.POST)
        if form.is_valid():
            cat = form.save(commit=False)
            cat.user = request.user
            cat.save()
            messages.success(request, _("Category '%(name)s' created.") % {"name": cat.name})
            return redirect("category_list")
    else:
        form = ExpenseCategoryForm()
    return render(request, "expense/expense_form.html", {"form": form, "title": _("Add Category")})


@login_required
def category_import_template_view(request):
    rows = [(_("Groceries"),), (_("Transport"),)]
    return _csv_response(
        "expense_category_import_template.csv",
        [_("Name")],
        rows,
    )


@login_required
def category_import_view(request):
    if request.method != "POST":
        return redirect("category_list")

    csv_file = request.FILES.get("csv_file")
    if not csv_file:
        messages.error(request, _("Please choose a CSV file to import."))
        return redirect("category_list")

    try:
        decoded = csv_file.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        messages.error(request, _("Could not read that file. Please upload a UTF-8 encoded CSV."))
        return redirect("category_list")

    reader = csv.DictReader(io.StringIO(decoded))
    if not reader.fieldnames:
        messages.error(request, _("The CSV file appears to be empty."))
        return redirect("category_list")

    fieldnames = {(f or "").strip().lower(): f for f in reader.fieldnames}
    if "name" not in fieldnames:
        messages.error(request, _("The CSV must have a 'Name' column."))
        return redirect("category_list")

    existing_names = {n.lower() for n in request.user.expense_categories.values_list("name", flat=True)}

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

        ExpenseCategory.objects.create(user=request.user, name=name)

        existing_names.add(name.lower())
        created += 1

    if created:
        messages.success(
            request,
            ngettext("Imported %(count)s category.", "Imported %(count)s categories.", created)
            % {"count": created},
        )
    skipped_total = skipped_duplicate + skipped_blank
    if skipped_total:
        messages.warning(
            request,
            _("Skipped %(count)s row(s): %(dup)s duplicate name(s), %(blank)s blank name(s).")
            % {"count": skipped_total, "dup": skipped_duplicate, "blank": skipped_blank},
        )
    if not created and not skipped_total:
        messages.error(request, _("No rows found to import."))

    return redirect("category_list")


@login_required
def recurring_expense_list_view(request):
    generated = generate_due_recurring_expense(request.user)
    if generated:
        messages.info(request, ngettext(
            "%(count)s recurring expense entry was generated automatically.",
            "%(count)s recurring expense entries were generated automatically.",
            generated,
        ) % {"count": generated})

    schedules = request.user.recurring_expenses.select_related("category").all()
    return render(request, "expense/recurring_list.html", {"schedules": schedules})


@login_required
def recurring_expense_create_view(request):
    if request.method == "POST":
        form = RecurringExpenseForm(request.POST, user=request.user)
        if form.is_valid():
            schedule = form.save(commit=False)
            schedule.user = request.user
            schedule.save()
            messages.success(request, _("Recurring expense scheduled."))
            return redirect("recurring_expense_list")
    else:
        form = RecurringExpenseForm(user=request.user, initial={"next_run_date": django.utils.timezone.now().date()})
    return render(request, "expense/expense_form.html", {
        "form": form,
        "title": _("New Recurring Expense"),
        "back_url": "/expense/recurring/",
    })


@login_required
def recurring_expense_edit_view(request, pk):
    schedule = get_object_or_404(RecurringExpense, pk=pk, user=request.user)
    if request.method == "POST":
        form = RecurringExpenseForm(request.POST, instance=schedule, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, _("Recurring expense schedule updated."))
            return redirect("recurring_expense_list")
    else:
        form = RecurringExpenseForm(instance=schedule, user=request.user)
    return render(request, "expense/expense_form.html", {
        "form": form,
        "title": _("Edit Recurring Expense"),
        "back_url": "/expense/recurring/",
    })


@login_required
@require_POST
def recurring_expense_toggle_view(request, pk):
    schedule = get_object_or_404(RecurringExpense, pk=pk, user=request.user)
    schedule.is_active = not schedule.is_active
    schedule.save(update_fields=["is_active", "updated_at"])
    if schedule.is_active:
        messages.success(request, _("Recurring expense resumed."))
    else:
        messages.success(request, _("Recurring expense paused."))
    return redirect("recurring_expense_list")


@login_required
@require_POST
def recurring_expense_delete_view(request, pk):
    schedule = get_object_or_404(RecurringExpense, pk=pk, user=request.user)
    schedule.delete()
    messages.success(request, _("Recurring expense deleted."))
    return redirect("recurring_expense_list")


@login_required
@require_POST
def category_toggle_active_view(request, pk):
    obj = get_object_or_404(ExpenseCategory, pk=pk, user=request.user)
    return toggle_active(request, obj, "category_list")
