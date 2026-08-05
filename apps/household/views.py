import calendar
from datetime import date

from django.shortcuts import render, redirect, get_object_or_404
from django.http import Http404
from django.utils import timezone
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum, Count, DecimalField, Value
from django.db.models.functions import Coalesce, TruncMonth
from django.core.paginator import Paginator

from .models import HouseholdCategory, HouseholdMember, Purchase, Settlement
from .forms import HouseholdCategoryForm, HouseholdMemberForm, PurchaseForm, SettlementForm


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
    category_labels = [row["category__name"] or "Uncategorized" for row in category_totals if row["total"] > 0]
    category_data = [float(row["total"]) for row in category_totals if row["total"] > 0]

    recent_purchases = purchases.select_related("buyer", "category").order_by("-date", "-created_at")[:10]

    context = {
        "total_spent": total_spent,
        "total_settled": total_settled,
        "outstanding_to_members": outstanding_to_members,
        "this_month_spent": this_month_spent,
        "category_labels": category_labels,
        "category_data": category_data,
        "recent_purchases": recent_purchases,
        "current_year": today.year,
        "current_month": today.month,
    }
    return render(request, "household/dashboard.html", context)


@login_required
def purchase_list_view(request):
    monthly = (
        request.user.household_purchases.annotate(month=TruncMonth("date"))
        .values("month")
        .annotate(
            total=Coalesce(Sum("amount"), Value(0, output_field=DecimalField())),
            count=Count("id"),
        )
        .order_by("-month")
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

    context = {
        "page_obj": page_obj,
        "pagination_window": _build_pagination_window(page_obj),
        "total_spent": total_spent,
        "total_settled": total_settled,
        "outstanding_to_members": outstanding_to_members,
        "current_year": today.year,
        "current_month": today.month,
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
            messages.success(request, f"Purchase of ৳{purchase.amount} recorded.")
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
    _, last_day = calendar.monthrange(year, month)
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
            messages.success(request, "Purchase updated.")
            return redirect("household_month_detail", year=purchase.date.year, month=purchase.date.month)
    else:
        form = PurchaseForm(instance=purchase, user=request.user)
    return render(
        request,
        "household/household_form.html",
        {
            "form": form,
            "title": "Edit Purchase",
            "back_url": f"/household/purchases/{purchase.date.year}/{purchase.date.month}/",
        },
    )


@login_required
def purchase_delete_view(request, pk):
    purchase = get_object_or_404(Purchase, pk=pk, user=request.user)
    year, month, amount = purchase.date.year, purchase.date.month, purchase.amount
    purchase.delete()
    messages.success(request, f"Purchase of ৳{amount} deleted.")
    return redirect("household_month_detail", year=year, month=month)


@login_required
def member_list_view(request):
    members = request.user.household_members.all()
    for m in members:
        spent = m.total_spent
        m.settle_percent = min(100, int((m.total_settled / spent) * 100)) if spent > 0 else 0

    context = {
        "members": members,
        "total_owed": sum((m.balance_due for m in members if m.balance_due > 0), 0),
    }
    return render(request, "household/member_list.html", context)


@login_required
def member_create_view(request):
    if request.method == "POST":
        form = HouseholdMemberForm(request.POST)
        if form.is_valid():
            member = form.save(commit=False)
            member.user = request.user
            member.save()
            messages.success(request, f"'{member.name}' added.")
            return redirect("household_member_list")
    else:
        form = HouseholdMemberForm()
    return render(
        request,
        "household/household_form.html",
        {"form": form, "title": "Add Household Member", "back_url": "/household/members/"},
    )


@login_required
def member_edit_view(request, pk):
    member = get_object_or_404(HouseholdMember, pk=pk, user=request.user)
    if request.method == "POST":
        form = HouseholdMemberForm(request.POST, instance=member)
        if form.is_valid():
            form.save()
            messages.success(request, f"'{member.name}' updated.")
            return redirect("household_member_list")
    else:
        form = HouseholdMemberForm(instance=member)
    return render(
        request,
        "household/household_form.html",
        {"form": form, "title": f"Edit {member.name}", "back_url": f"/household/members/{member.pk}/"},
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
            messages.success(request, f"Gave back ৳{settlement.amount} to {member.name}.")
            return redirect("household_member_detail", pk=pk)
    else:
        form = SettlementForm(initial={"date": timezone.now().date()})

    purchase_items = list(member.purchases.select_related("category"))
    settlement_items = list(member.settlements.all())
    for p in purchase_items:
        p.kind = "purchase"
    for s in settlement_items:
        s.kind = "settlement"

    activity = sorted(
        purchase_items + settlement_items,
        key=lambda item: (item.date, item.created_at),
        reverse=True,
    )

    context = {
        "member": member,
        "activity": activity,
        "spent": member.total_spent,
        "settled": member.total_settled,
        "balance_due": member.balance_due,
        "form": form,
        "chart_settled": float(member.total_settled),
        "chart_due": float(member.balance_due) if member.balance_due > 0 else 0,
    }
    return render(request, "household/member_detail.html", context)


@login_required
def settlement_edit_view(request, pk):
    settlement = get_object_or_404(Settlement, pk=pk, member__user=request.user)
    member = settlement.member
    if request.method == "POST":
        form = SettlementForm(request.POST, instance=settlement)
        if form.is_valid():
            form.save()
            messages.success(request, "Settlement updated.")
            return redirect("household_member_detail", pk=member.pk)
    else:
        form = SettlementForm(instance=settlement)
    return render(
        request,
        "household/household_form.html",
        {"form": form, "title": "Edit Settlement", "back_url": f"/household/members/{member.pk}/"},
    )


@login_required
def settlement_delete_view(request, pk):
    settlement = get_object_or_404(Settlement, pk=pk, member__user=request.user)
    member = settlement.member
    amount = settlement.amount
    settlement.delete()
    messages.success(request, f"Settlement of ৳{amount} deleted.")
    return redirect("household_member_detail", pk=member.pk)


@login_required
def category_list_view(request):
    categories = request.user.household_categories.annotate(
        total_amt=Coalesce(Sum("purchases__amount"), Value(0, output_field=DecimalField()))
    ).order_by("-total_amt")
    return render(request, "household/category_list.html", {"categories": categories})


@login_required
def category_create_view(request):
    if request.method == "POST":
        form = HouseholdCategoryForm(request.POST)
        if form.is_valid():
            category = form.save(commit=False)
            category.user = request.user
            category.save()
            messages.success(request, f"Category '{category.name}' created.")
            return redirect("household_category_list")
    else:
        form = HouseholdCategoryForm()
    return render(
        request,
        "household/household_form.html",
        {"form": form, "title": "Add Bazar Category", "back_url": "/household/categories/"},
    )
