import calendar
import csv
import io
from datetime import date

from django.shortcuts import render, redirect, get_object_or_404
from django.http import Http404, HttpResponse
from django.utils import timezone
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum, Count, DecimalField, Value
from django.db.models.functions import Coalesce, TruncMonth
from django.core.paginator import Paginator
from django.utils import dateformat
from django.utils.translation import gettext as _, ngettext

from .models import HouseholdCategory, HouseholdMember, Purchase, Settlement
from .forms import HouseholdCategoryForm, HouseholdMemberForm, PurchaseForm, SettlementForm


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
    today = timezone.now().date()
    starts = []
    for i in range(11, -1, -1):
        month_index = today.month - i
        year = today.year
        while month_index <= 0:
            month_index += 12
            year -= 1
        starts.append(date(year, month_index, 1))
    return starts


def _period_label(selected_year, selected_month):
    if selected_month:
        return dateformat.format(date(2000, selected_month, 1), "F") + f" {selected_year}"
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
        "generated_at": timezone.now(),
    })

MONTH_CHOICES = [(i, date(2000, i, 1)) for i in range(1, 13)]


def _parse_year_month(request):
    raw_year = request.GET.get("year", "").strip()
    year = int(raw_year) if raw_year.isdigit() else None
    raw_month = request.GET.get("month", "").strip()
    month = int(raw_month) if raw_month.isdigit() and 1 <= int(raw_month) <= 12 else None
    return year, month


PURCHASE_LIST_SORT_OPTIONS = [
    ("-month", _("Month (Newest First)")),
    ("month", _("Month (Oldest First)")),
    ("-total", _("Total Spent (High to Low)")),
    ("total", _("Total Spent (Low to High)")),
]
PURCHASE_LIST_SORT_FIELDS = {
    "-month": ["-month"],
    "month": ["month"],
    "-total": ["-total"],
    "total": ["total"],
}

MEMBER_SORT_OPTIONS = [
    ("name", _("Name (A–Z)")),
    ("-name", _("Name (Z–A)")),
    ("-balance", _("Balance Due (High to Low)")),
    ("balance", _("Balance Due (Low to High)")),
]

CATEGORY_SORT_OPTIONS = [
    ("-total", _("Total Spent (High to Low)")),
    ("total", _("Total Spent (Low to High)")),
    ("name", _("Name (A–Z)")),
    ("-name", _("Name (Z–A)")),
]
CATEGORY_SORT_FIELDS = {
    "-total": ["-total"],
    "total": ["total"],
    "name": ["category__name"],
    "-name": ["-category__name"],
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


@login_required
def dashboard_view(request):
    purchases = request.user.household_purchases.all()

    total_spent = purchases.aggregate(
        total=Coalesce(Sum("amount"), Value(0, output_field=DecimalField()))
    )["total"]

    total_settled = Settlement.objects.filter(member__user=request.user).aggregate(
        total=Coalesce(Sum("amount"), Value(0, output_field=DecimalField()))
    )["total"]

    outstanding_to_members = sum(
        (m.balance_due for m in request.user.household_members.all() if m.balance_due > 0),
        0,
    )

    today = timezone.now().date()
    this_month_spent = purchases.filter(date__year=today.year, date__month=today.month).aggregate(
        total=Coalesce(Sum("amount"), Value(0, output_field=DecimalField()))
    )["total"]

    category_totals = (
        purchases.values("category__name")
        .annotate(total=Coalesce(Sum("amount"), Value(0, output_field=DecimalField())))
        .order_by("-total")
    )
    category_labels = [row["category__name"] or _("Uncategorized") for row in category_totals if row["total"] > 0]
    category_data = [float(row["total"]) for row in category_totals if row["total"] > 0]

    recent_purchases = purchases.select_related("buyer", "category").order_by("-date", "-created_at")[:10]

    # Rolling 12-month spending trend.
    month_starts = _last_12_month_starts()
    monthly_totals = (
        purchases.filter(date__gte=month_starts[0])
        .annotate(month=TruncMonth("date"))
        .values("month")
        .annotate(total=Sum("amount"))
    )
    total_by_month = {row["month"]: row["total"] for row in monthly_totals}
    trend_labels = month_starts
    trend_spent = [float(total_by_month.get(d, 0) or 0) for d in month_starts]

    context = {
        "total_spent": total_spent,
        "total_settled": total_settled,
        "outstanding_to_members": outstanding_to_members,
        "this_month_spent": this_month_spent,
        "category_labels": category_labels,
        "category_data": category_data,
        "trend_labels": trend_labels,
        "trend_spent": trend_spent,
        "recent_purchases": recent_purchases,
        "current_year": today.year,
        "current_month": today.month,
    }
    return render(request, "household/dashboard.html", context)


@login_required
def purchase_list_view(request):
    sort = request.GET.get("sort", "-month")
    if sort not in PURCHASE_LIST_SORT_FIELDS:
        sort = "-month"

    monthly = (
        request.user.household_purchases.annotate(month=TruncMonth("date"))
        .values("month")
        .annotate(
            total=Coalesce(Sum("amount"), Value(0, output_field=DecimalField())),
            count=Count("id"),
        )
        .order_by(*PURCHASE_LIST_SORT_FIELDS[sort])
    )

    if request.GET.get("export") == "csv":
        rows = [(row["month"].strftime("%Y-%m"), row["count"], row["total"]) for row in monthly]
        return _csv_response(
            "bazar_log.csv",
            [_("Bazar"), _("Purchases Logged"), _("Total Spent")],
            rows,
        )

    paginator = Paginator(monthly, 9)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    total_spent = request.user.household_purchases.aggregate(
        total=Coalesce(Sum("amount"), Value(0, output_field=DecimalField()))
    )["total"]
    total_settled = Settlement.objects.filter(member__user=request.user).aggregate(
        total=Coalesce(Sum("amount"), Value(0, output_field=DecimalField()))
    )["total"]
    outstanding_to_members = sum(
        (m.balance_due for m in request.user.household_members.all() if m.balance_due > 0),
        0,
    )

    today = timezone.now().date()

    base_query = request.GET.copy()
    base_query.pop("page", None)
    base_query_string = base_query.urlencode()

    context = {
        "page_obj": page_obj,
        "pagination_window": _build_pagination_window(page_obj),
        "total_spent": total_spent,
        "total_settled": total_settled,
        "outstanding_to_members": outstanding_to_members,
        "current_year": today.year,
        "current_month": today.month,
        "sort": sort,
        "sort_options": PURCHASE_LIST_SORT_OPTIONS,
        "base_query_string": base_query_string,
    }
    return render(request, "household/purchase_list.html", context)


@login_required
def month_detail_view(request, year, month):
    if not 1 <= month <= 12:
        raise Http404("Invalid month.")

    today = timezone.now().date()

    if request.method == "POST":
        form = PurchaseForm(request.POST, user=request.user)
        if form.is_valid():
            purchase = form.save(commit=False)
            purchase.user = request.user
            purchase.save()
            messages.success(request, _("Purchase of ৳%(amount)s recorded.") % {"amount": purchase.amount})
            return redirect("household_month_detail", year=purchase.date.year, month=purchase.date.month)
    else:
        if year == today.year and month == today.month:
            initial_date = today
        else:
            initial_date = date(year, month, 1)
        form = PurchaseForm(user=request.user, initial={"date": initial_date})

    purchases = (
        request.user.household_purchases.filter(date__year=year, date__month=month)
        .select_related("buyer", "category")
        .order_by("-date", "-created_at")
    )
    total_spent = purchases.aggregate(
        total=Coalesce(Sum("amount"), Value(0, output_field=DecimalField()))
    )["total"]

    month_label = date(year, month, 1)
    _first_weekday, last_day = calendar.monthrange(year, month)
    prev_month = date(year, month, 1) - timezone.timedelta(days=1)
    next_month_first = date(year, month, last_day) + timezone.timedelta(days=1)

    context = {
        "year": year,
        "month": month,
        "month_label": month_label,
        "purchases": purchases,
        "total_spent": total_spent,
        "form": form,
        "prev_year": prev_month.year,
        "prev_month": prev_month.month,
        "next_year": next_month_first.year,
        "next_month": next_month_first.month,
    }
    return render(request, "household/month_detail.html", context)


@login_required
def purchase_edit_view(request, pk):
    purchase = get_object_or_404(Purchase, pk=pk, user=request.user)
    if request.method == "POST":
        form = PurchaseForm(request.POST, instance=purchase, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, _("Purchase updated."))
            return redirect("household_month_detail", year=purchase.date.year, month=purchase.date.month)
    else:
        form = PurchaseForm(instance=purchase, user=request.user)
    return render(
        request,
        "household/household_form.html",
        {
            "form": form,
            "title": _("Edit Purchase"),
            "back_url": f"/household/purchases/{purchase.date.year}/{purchase.date.month}/",
        },
    )


@login_required
def purchase_delete_view(request, pk):
    purchase = get_object_or_404(Purchase, pk=pk, user=request.user)
    year, month, amount = purchase.date.year, purchase.date.month, purchase.amount
    purchase.delete()
    messages.success(request, _("Purchase of ৳%(amount)s deleted.") % {"amount": amount})
    return redirect("household_month_detail", year=year, month=month)


@login_required
def member_list_view(request):
    members = list(request.user.household_members.all())
    for m in members:
        spent = m.total_spent
        m.settle_percent = min(100, int((m.total_settled / spent) * 100)) if spent > 0 else 0

    if request.GET.get("export") == "csv":
        rows = [
            (
                m.name,
                m.phone,
                m.total_spent,
                m.total_settled,
                m.balance_due,
                _("Settled Up") if m.is_settled else _("Unpaid"),
            )
            for m in members
        ]
        return _csv_response(
            "household_members.csv",
            [_("Members"), _("Phone Number"), _("Fronted"), _("Given Back"), _("Balance Due"), _("Status")],
            rows,
        )

    total_owed = sum((m.balance_due for m in members if m.balance_due > 0), 0)

    sort = request.GET.get("sort", "name")
    valid_sorts = {value for value, _label in MEMBER_SORT_OPTIONS}
    if sort not in valid_sorts:
        sort = "name"
    if sort == "name":
        members.sort(key=lambda m: m.name.lower())
    elif sort == "-name":
        members.sort(key=lambda m: m.name.lower(), reverse=True)
    elif sort == "-balance":
        members.sort(key=lambda m: m.balance_due, reverse=True)
    elif sort == "balance":
        members.sort(key=lambda m: m.balance_due)

    paginator = Paginator(members, 12)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    base_query = request.GET.copy()
    base_query.pop("page", None)
    base_query_string = base_query.urlencode()

    context = {
        "page_obj": page_obj,
        "pagination_window": _build_pagination_window(page_obj),
        "total_owed": total_owed,
        "sort": sort,
        "sort_options": MEMBER_SORT_OPTIONS,
        "base_query_string": base_query_string,
    }
    return render(request, "household/member_list.html", context)


@login_required
def member_import_template_view(request):
    rows = [(_("Rahim"), "01711000000", _("Occasionally fronts bazar money"))]
    return _csv_response(
        "household_member_import_template.csv",
        [_("Name"), _("Phone"), _("Note")],
        rows,
    )


@login_required
def member_import_view(request):
    if request.method != "POST":
        return redirect("household_member_list")

    csv_file = request.FILES.get("csv_file")
    if not csv_file:
        messages.error(request, _("Please choose a CSV file to import."))
        return redirect("household_member_list")

    try:
        decoded = csv_file.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        messages.error(request, _("Could not read that file. Please upload a UTF-8 encoded CSV."))
        return redirect("household_member_list")

    reader = csv.DictReader(io.StringIO(decoded))
    if not reader.fieldnames:
        messages.error(request, _("The CSV file appears to be empty."))
        return redirect("household_member_list")

    fieldnames = {(f or "").strip().lower(): f for f in reader.fieldnames}
    if "name" not in fieldnames:
        messages.error(request, _("The CSV must have a 'Name' column."))
        return redirect("household_member_list")

    existing_names = {n.lower() for n in request.user.household_members.values_list("name", flat=True)}

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

        HouseholdMember.objects.create(user=request.user, name=name, phone=phone, note=note)

        existing_names.add(name.lower())
        created += 1

    if created:
        messages.success(request, _("Imported %(count)s member(s).") % {"count": created})
    skipped_total = skipped_duplicate + skipped_blank
    if skipped_total:
        messages.warning(
            request,
            _("Skipped %(count)s row(s): %(dup)s duplicate name(s), %(blank)s blank name(s).")
            % {"count": skipped_total, "dup": skipped_duplicate, "blank": skipped_blank},
        )
    if not created and not skipped_total:
        messages.error(request, _("No rows found to import."))

    return redirect("household_member_list")


@login_required
def member_create_view(request):
    if request.method == "POST":
        form = HouseholdMemberForm(request.POST)
        if form.is_valid():
            member = form.save(commit=False)
            member.user = request.user
            member.save()
            messages.success(request, _("'%(name)s' added.") % {"name": member.name})
            return redirect("household_member_list")
    else:
        form = HouseholdMemberForm()
    return render(
        request,
        "household/household_form.html",
        {"form": form, "title": _("Add Household Member"), "back_url": "/household/members/"},
    )


@login_required
def member_edit_view(request, pk):
    member = get_object_or_404(HouseholdMember, pk=pk, user=request.user)
    if request.method == "POST":
        form = HouseholdMemberForm(request.POST, instance=member)
        if form.is_valid():
            form.save()
            messages.success(request, _("'%(name)s' updated.") % {"name": member.name})
            return redirect("household_member_list")
    else:
        form = HouseholdMemberForm(instance=member)
    return render(
        request,
        "household/household_form.html",
        {"form": form, "title": _("Edit %(name)s") % {"name": member.name}, "back_url": f"/household/members/{member.pk}/"},
    )


@login_required
def member_detail_view(request, pk):
    member = get_object_or_404(HouseholdMember, pk=pk, user=request.user)

    if request.method == "POST":
        form = SettlementForm(request.POST)
        if form.is_valid():
            settlement = form.save(commit=False)
            settlement.member = member
            settlement.save()
            messages.success(request, _("Gave back ৳%(amount)s to %(name)s.") % {"amount": settlement.amount, "name": member.name})
            return redirect("household_member_detail", pk=pk)
    else:
        form = SettlementForm(initial={"date": timezone.now().date()})

    all_purchases = member.purchases.select_related("category")
    all_settlements = member.settlements.all()

    selected_year, selected_month = _parse_year_month(request)
    purchases_qs = all_purchases
    settlements_qs = all_settlements
    if selected_year:
        purchases_qs = purchases_qs.filter(date__year=selected_year)
        settlements_qs = settlements_qs.filter(date__year=selected_year)
    if selected_month:
        purchases_qs = purchases_qs.filter(date__month=selected_month)
        settlements_qs = settlements_qs.filter(date__month=selected_month)

    purchase_items = list(purchases_qs)
    settlement_items = list(settlements_qs)
    for p in purchase_items:
        p.kind = "purchase"
    for s in settlement_items:
        s.kind = "settlement"

    activity = sorted(
        purchase_items + settlement_items,
        key=lambda item: (item.date, item.created_at),
        reverse=True,
    )

    period_fronted = purchases_qs.aggregate(total=Coalesce(Sum("amount"), Value(0, output_field=DecimalField())))["total"]
    period_given_back = settlements_qs.aggregate(total=Coalesce(Sum("amount"), Value(0, output_field=DecimalField())))["total"]

    year_options = sorted(
        set(all_purchases.values_list("date__year", flat=True)) | set(all_settlements.values_list("date__year", flat=True)),
        reverse=True,
    )

    if request.GET.get("export") == "csv":
        rows = [
            (
                item.date.isoformat(),
                _("Fronted (Bazar)") if item.kind == "purchase" else _("Given Back"),
                item.amount,
                (item.category.name if item.kind == "purchase" and item.category else item.note or ""),
            )
            for item in activity
        ]
        return _csv_response(
            f"{member.name}_activity.csv",
            [_("Date"), _("Type"), _("Amount"), _("Note")],
            rows,
        )

    context = {
        "member": member,
        "activity": activity,
        # All-time totals (never period-filtered — balance due is a running snapshot).
        "spent": member.total_spent,
        "settled": member.total_settled,
        "balance_due": member.balance_due,
        "period_fronted": period_fronted,
        "period_given_back": period_given_back,
        "year_options": year_options,
        "month_choices": MONTH_CHOICES,
        "selected_year": selected_year,
        "selected_month": selected_month,
        "selected_month_date": date(2000, selected_month, 1) if selected_month else None,
        "form": form,
        "chart_settled": float(member.total_settled),
        "chart_due": float(member.balance_due) if member.balance_due > 0 else 0,
    }
    return render(request, "household/member_detail.html", context)


@login_required
def member_statement_view(request, pk):
    member = get_object_or_404(HouseholdMember, pk=pk, user=request.user)
    all_purchases = member.purchases.select_related("category")
    all_settlements = member.settlements.all()

    selected_year, selected_month = _parse_year_month(request)
    purchases_qs = all_purchases
    settlements_qs = all_settlements
    if selected_year:
        purchases_qs = purchases_qs.filter(date__year=selected_year)
        settlements_qs = settlements_qs.filter(date__year=selected_year)
    if selected_month:
        purchases_qs = purchases_qs.filter(date__month=selected_month)
        settlements_qs = settlements_qs.filter(date__month=selected_month)

    purchase_items = list(purchases_qs)
    settlement_items = list(settlements_qs)
    for p in purchase_items:
        p.kind = "purchase"
    for s in settlement_items:
        s.kind = "settlement"

    activity = sorted(
        purchase_items + settlement_items,
        key=lambda item: (item.date, item.created_at),
    )

    rows = [
        (
            item.date.strftime("%d %b %Y"),
            _("Fronted (Bazar)") if item.kind == "purchase" else _("Given Back"),
            (item.category.name if item.kind == "purchase" and item.category else item.note or "-"),
            f"{item.amount:,.2f}",
        )
        for item in activity
    ]

    return _render_statement(
        request,
        entity_label=_("Household Member"),
        entity_name=member.name,
        entity_meta=[(_("Phone"), member.phone)],
        period_label=_period_label(selected_year, selected_month),
        summary_rows=[
            (_("Total Fronted"), f"{member.total_spent:,.2f}", ""),
            (_("Given Back"), f"{member.total_settled:,.2f}", "positive"),
            (_("Balance Due"), f"{member.balance_due:,.2f}", "negative" if member.balance_due > 0 else "positive"),
        ],
        columns=[_("Date"), _("Type"), _("Note"), _("Amount (৳)")],
        rows=rows,
        back_url=request.META.get("HTTP_REFERER") or f"/household/members/{member.pk}/",
    )


@login_required
def settlement_edit_view(request, pk):
    settlement = get_object_or_404(Settlement, pk=pk, member__user=request.user)
    member = settlement.member
    if request.method == "POST":
        form = SettlementForm(request.POST, instance=settlement)
        if form.is_valid():
            form.save()
            messages.success(request, _("Settlement updated."))
            return redirect("household_member_detail", pk=member.pk)
    else:
        form = SettlementForm(instance=settlement)
    return render(
        request,
        "household/household_form.html",
        {"form": form, "title": _("Edit Settlement"), "back_url": f"/household/members/{member.pk}/"},
    )


@login_required
def settlement_delete_view(request, pk):
    settlement = get_object_or_404(Settlement, pk=pk, member__user=request.user)
    member = settlement.member
    amount = settlement.amount
    settlement.delete()
    messages.success(request, _("Settlement of ৳%(amount)s deleted.") % {"amount": amount})
    return redirect("household_member_detail", pk=member.pk)


@login_required
def category_list_view(request):
    all_purchases = request.user.household_purchases.all()
    has_categories = request.user.household_categories.exists()

    selected_year, selected_month = _parse_year_month(request)
    purchases = all_purchases
    if selected_year:
        purchases = purchases.filter(date__year=selected_year)
    if selected_month:
        purchases = purchases.filter(date__month=selected_month)

    total_spent = purchases.aggregate(
        total=Coalesce(Sum("amount"), Value(0, output_field=DecimalField()))
    )["total"]

    sort = request.GET.get("sort", "-total")
    if sort not in CATEGORY_SORT_FIELDS:
        sort = "-total"

    category_rows = (
        purchases.values("category_id", "category__name")
        .annotate(total=Coalesce(Sum("amount"), Value(0, output_field=DecimalField())))
        .order_by(*CATEGORY_SORT_FIELDS[sort])
    )

    categories = []
    for row in category_rows:
        if row["total"] <= 0:
            continue
        percent = round((row["total"] / total_spent) * 100, 1) if total_spent > 0 else 0
        categories.append({
            "id": row["category_id"],
            "name": row["category__name"] or _("Uncategorized"),
            "total_amt": row["total"],
            "percent": percent,
        })

    category_labels = [c["name"] for c in categories]
    category_data = [float(c["total_amt"]) for c in categories]

    year_options = list(all_purchases.values_list("date__year", flat=True).distinct().order_by("-date__year"))

    if request.GET.get("export") == "csv":
        rows = [(c["name"], c["total_amt"], c["percent"]) for c in categories]
        return _csv_response(
            "bazar_categories.csv",
            [_("Category"), _("Total Spent"), "%"],
            rows,
        )

    context = {
        "categories": categories,
        "has_categories": has_categories,
        "total_spent": total_spent,
        "category_labels": category_labels,
        "category_data": category_data,
        "year_options": year_options,
        "month_choices": MONTH_CHOICES,
        "selected_year": selected_year,
        "selected_month": selected_month,
        "selected_month_date": date(2000, selected_month, 1) if selected_month else None,
        "sort": sort,
        "sort_options": CATEGORY_SORT_OPTIONS,
    }
    return render(request, "household/category_list.html", context)


@login_required
def category_create_view(request):
    if request.method == "POST":
        form = HouseholdCategoryForm(request.POST)
        if form.is_valid():
            category = form.save(commit=False)
            category.user = request.user
            category.save()
            messages.success(request, _("Category '%(name)s' created.") % {"name": category.name})
            return redirect("household_category_list")
    else:
        form = HouseholdCategoryForm()
    return render(
        request,
        "household/household_form.html",
        {"form": form, "title": _("Add Bazar Category"), "back_url": "/household/categories/"},
    )


@login_required
def category_import_template_view(request):
    rows = [(_("Vegetables"),), (_("Fish"),)]
    return _csv_response(
        "bazar_category_import_template.csv",
        [_("Name")],
        rows,
    )


@login_required
def category_import_view(request):
    if request.method != "POST":
        return redirect("household_category_list")

    csv_file = request.FILES.get("csv_file")
    if not csv_file:
        messages.error(request, _("Please choose a CSV file to import."))
        return redirect("household_category_list")

    try:
        decoded = csv_file.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        messages.error(request, _("Could not read that file. Please upload a UTF-8 encoded CSV."))
        return redirect("household_category_list")

    reader = csv.DictReader(io.StringIO(decoded))
    if not reader.fieldnames:
        messages.error(request, _("The CSV file appears to be empty."))
        return redirect("household_category_list")

    fieldnames = {(f or "").strip().lower(): f for f in reader.fieldnames}
    if "name" not in fieldnames:
        messages.error(request, _("The CSV must have a 'Name' column."))
        return redirect("household_category_list")

    existing_names = {n.lower() for n in request.user.household_categories.values_list("name", flat=True)}

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

        HouseholdCategory.objects.create(user=request.user, name=name)

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

    return redirect("household_category_list")
