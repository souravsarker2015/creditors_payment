import csv
import io
from decimal import Decimal, InvalidOperation
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.http import HttpResponse
import django.utils.timezone
from datetime import date as date_cls, timedelta
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib import messages

from apps.core.csvsafe import safe_writer
from apps.core.flow import record_initial, record_next, warn_if_overpaid
from django.db.models import Sum, Q, F, DecimalField, Value
from django.db.models.functions import Coalesce, TruncMonth
from django.core.paginator import Paginator
from django.utils import dateformat
from django.utils.translation import gettext as _, gettext_lazy

from apps.core.templatetags.ui import bd_number, money
from apps.core.ledger_views import ImportRows, attach_running_balance, party_search
from apps.overview.people import pairs
from apps.wallets.services import warn_if_short
from apps.trash.undo import delete_with_undo
from .models import Creditor, CreditorCategory, Transaction, DUE_SOON_DAYS
from apps.core.stats import ledger_extras
from apps.core.status import apply_status_filter, delete_record, toggle_active
from apps.core.ledger_views import _build_pagination_window, _csv_response, _last_12_month_starts, _parse_year_month, _period_label, _render_statement, _row_value  # shared by every ledger app

MONTH_CHOICES = [(i, date_cls(2000, i, 1)) for i in range(1, 13)]

SORT_OPTIONS = [
    ("name", gettext_lazy("Name (A–Z)")),
    ("-name", gettext_lazy("Name (Z–A)")),
    ("-remaining", gettext_lazy("Remaining (High to Low)")),
    ("remaining", gettext_lazy("Remaining (Low to High)")),
]
SORT_FIELDS = {
    "name": ["name"],
    "-name": ["-name"],
    "remaining": ["remaining_amt", "name"],
    "-remaining": ["-remaining_amt", "name"],
}


@login_required
def dashboard_view(request):
    valid_filter_types = {"include", "exclude"}
    filter_type = request.GET.get("filter_type", "include").strip().lower()
    if filter_type not in valid_filter_types:
        filter_type = "include"

    selected_categories = [
        category
        for category in request.GET.getlist("category")
        if category in CreditorCategory.values
    ]

    creditors_base_qs = request.user.creditors.all()
    if selected_categories:
        if filter_type == "exclude":
            creditors_base_qs = creditors_base_qs.exclude(category__in=selected_categories)
        else:
            creditors_base_qs = creditors_base_qs.filter(category__in=selected_categories)

    # Global summary stats for the current user
    stats = creditors_base_qs.aggregate(
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
    creditors_qs = creditors_base_qs.annotate(
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

    # Creditors needing attention: an unpaid balance with a due date that has
    # passed or is coming up within DUE_SOON_DAYS.
    today = django.utils.timezone.localdate()
    due_soon_cutoff = today + timedelta(days=DUE_SOON_DAYS)
    overdue_creditors = []
    due_soon_creditors = []
    for c in creditors_qs:
        rem = c.c_borrowed - c.c_paid
        if c.due_date and rem > 0:
            c.remaining_amt = rem
            if c.due_date < today:
                overdue_creditors.append(c)
            elif c.due_date <= due_soon_cutoff:
                due_soon_creditors.append(c)
    overdue_creditors.sort(key=lambda c: c.due_date)
    due_soon_creditors.sort(key=lambda c: c.due_date)

    # Recent activity
    recent_transactions = Transaction.objects.filter(creditor__user=request.user)
    if selected_categories:
        if filter_type == "exclude":
            recent_transactions = recent_transactions.exclude(
                creditor__category__in=selected_categories
            )
        else:
            recent_transactions = recent_transactions.filter(
                creditor__category__in=selected_categories
            )
    recent_transactions = recent_transactions.select_related("creditor").order_by(
        "-date", "-created_at"
    )[:10]

    # Rolling 12-month Borrowed vs Repaid trend.
    month_starts = _last_12_month_starts()
    monthly_totals = (
        Transaction.objects.filter(creditor__in=creditors_base_qs, date__gte=month_starts[0])
        .annotate(month=TruncMonth("date"))
        .values("month", "transaction_type")
        .annotate(total=Sum("amount"))
    )
    borrowed_by_month = {row["month"]: row["total"] for row in monthly_totals if row["transaction_type"] == Transaction.BORROW}
    paid_by_month = {row["month"]: row["total"] for row in monthly_totals if row["transaction_type"] == Transaction.REPAY}
    trend_labels = month_starts
    trend_borrowed = [float(borrowed_by_month.get(d, 0) or 0) for d in month_starts]
    trend_paid = [float(paid_by_month.get(d, 0) or 0) for d in month_starts]

    context = {
        "total_borrowed": total_borrowed,
        "total_paid": total_paid,
        "remaining": remaining,
        "creditor_labels": creditor_labels,
        "creditor_remaining": creditor_remaining,
        "creditor_paid": creditor_paid,
        "trend_labels": trend_labels,
        "trend_borrowed": trend_borrowed,
        "trend_paid": trend_paid,
        "recent_transactions": recent_transactions,
        "overdue_creditors": overdue_creditors,
        "due_soon_creditors": due_soon_creditors,
        "selected_category": selected_categories[0] if len(selected_categories) == 1 else "",
        "selected_categories": selected_categories,
        "category_choices": CreditorCategory.choices,
        "filter_type": filter_type,
    }
    context.update(ledger_extras(
        entities=creditors_qs,
        transactions=Transaction.objects.filter(creditor__in=creditors_base_qs),
        out_type=Transaction.BORROW, in_type=Transaction.REPAY, out_attr="c_borrowed", in_attr="c_paid",
        detail_urlname="creditor_detail", overdue=overdue_creditors,
        trend_out=trend_borrowed, trend_in=trend_paid,
    ))
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
            messages.success(request, _("Creditor '%(name)s' added successfully.") % {"name": creditor.name})
            return record_next(request, "creditor_detail", creditor.pk) or redirect("creditor_list")
    else:
        form = CreditorForm()
    return render(request, "creditors/creditor_form.html", {"form": form, "title": _("Add New Creditor")})


@login_required
def creditor_edit_view(request, pk):
    creditor = get_object_or_404(Creditor, pk=pk, user=request.user)
    if request.method == "POST":
        form = CreditorForm(request.POST, instance=creditor)
        if form.is_valid():
            form.save()
            messages.success(request, _("Creditor '%(name)s' updated successfully.") % {"name": creditor.name})
            if form.posted_old_interest:
                messages.info(request, _("Posted %(amount)s of interest that had built up under the old terms.") % {
                    "amount": money(form.posted_old_interest.amount)})
            return redirect("creditor_detail", pk=creditor.pk)
    else:
        form = CreditorForm(instance=creditor)
    return render(request, "creditors/creditor_form.html", {
        "form": form, "title": _("Edit %(name)s") % {"name": creditor.name}, "back_url": reverse("creditor_detail", args=[creditor.pk])})


@login_required
def creditor_detail_view(request, pk):
    creditor = get_object_or_404(Creditor, pk=pk, user=request.user)
    all_transactions = creditor.transactions.all()

    if request.method == "POST":
        form = TransactionForm(request.POST, request.FILES, instance=Transaction(creditor=creditor))
        if form.is_valid():
            transaction = form.save()
            messages.success(request, _("Transaction of ৳%(amount)s added.") % {"amount": transaction.amount})
            warn_if_overpaid(request, creditor.name, creditor.remaining)
            if transaction.transaction_type == Transaction.REPAY:
                warn_if_short(request, transaction.wallet_id)
            return redirect("creditor_detail", pk=pk)
    else:
        form = TransactionForm(initial=record_initial(request, Transaction.TYPE_CHOICES, {"date": django.utils.timezone.localdate()}))

    # Calculate all-time totals for this specific creditor (never period-filtered —
    # outstanding balance only makes sense as a current, running snapshot).
    stats = all_transactions.aggregate(
        borrowed=Coalesce(Sum("amount", filter=Q(transaction_type=Transaction.BORROW)), Value(0, output_field=DecimalField())),
        paid=Coalesce(Sum("amount", filter=Q(transaction_type=Transaction.REPAY)), Value(0, output_field=DecimalField())),
    )
    remaining = stats["borrowed"] - stats["paid"]

    # Year/month filter narrows the transaction list and the "this period" figures below.
    selected_year, selected_month = _parse_year_month(request)
    transactions = all_transactions
    if selected_year:
        transactions = transactions.filter(date__year=selected_year)
    if selected_month:
        transactions = transactions.filter(date__month=selected_month)
    transactions = transactions.order_by("-date", "-created_at")

    period_stats = transactions.aggregate(
        borrowed=Coalesce(Sum("amount", filter=Q(transaction_type=Transaction.BORROW)), Value(0, output_field=DecimalField())),
        paid=Coalesce(Sum("amount", filter=Q(transaction_type=Transaction.REPAY)), Value(0, output_field=DecimalField())),
    )

    year_options = list(all_transactions.values_list("date__year", flat=True).distinct().order_by("-date__year"))

    transactions = attach_running_balance(transactions.select_related("wallet"), all_transactions, Transaction.BORROW)

    if request.GET.get("export") == "csv":
        rows = [
            (tx.date.isoformat(), tx.get_transaction_type_display(), tx.amount, tx.note, tx.wallet.name if tx.wallet else "", tx.balance_after)
            for tx in transactions
        ]
        return _csv_response(
            f"{creditor.name}_transactions.csv",
            [_("Date"), _("Type"), _("Amount"), _("Note"), _("Wallet"), _("Balance after")],
            rows,
        )

    due_status = None
    if creditor.due_date and remaining > 0:
        today = django.utils.timezone.localdate()
        if creditor.due_date < today:
            due_status = "overdue"
        elif creditor.due_date <= today + timedelta(days=DUE_SOON_DAYS):
            due_status = "due_soon"

    # Interest is opt-in per creditor (interest_rate is optional) and is a
    # live estimate — see Creditor.accrued_interest for the day-count
    # assumptions. It's never folded into `remaining` used elsewhere on this
    # page or across the app; it's only surfaced here, clearly labeled.
    accrued_interest = creditor.accrued_interest if creditor.interest_type else None

    context = {
        "creditor": creditor,
        "transactions": transactions,
        "form": form,
        "borrowed": stats["borrowed"],
        "paid": stats["paid"],
        "remaining": remaining,
        "period_borrowed": period_stats["borrowed"],
        "period_paid": period_stats["paid"],
        "year_options": year_options,
        "month_choices": MONTH_CHOICES,
        "selected_year": selected_year,
        "selected_month": selected_month,
        "selected_month_date": date_cls(2000, selected_month, 1) if selected_month else None,
        "chart_paid": float(stats["paid"]),
        "chart_remaining": float(remaining) if remaining > 0 else 0,
        "due_status": due_status,
        "accrued_interest": accrued_interest,
        "both_ways": pairs(request.user, creditor=creditor),
    }
    return render(request, "creditors/creditor_detail.html", context)


@login_required
def creditor_post_interest_view(request, pk):
    """Capitalizes a creditor's currently accrued interest into the ledger
    as a new BORROW transaction. POST-only, and the amount is recomputed
    server-side from the ledger at the moment of the request — never taken
    from the submitted form — so there's nothing for a stale page or a
    tampered request to get wrong.
    """
    if request.method != "POST":
        return redirect("creditor_detail", pk=pk)

    creditor = get_object_or_404(Creditor, pk=pk, user=request.user)
    transaction = creditor.post_accrued_interest()
    if transaction:
        messages.success(
            request,
            _("Posted ৳%(amount)s of accrued interest to %(name)s's balance.")
            % {"amount": transaction.amount, "name": creditor.name},
        )
    else:
        messages.info(request, _("There's no accrued interest to post right now."))
    return redirect("creditor_detail", pk=pk)


@login_required
def creditor_statement_view(request, pk):
    creditor = get_object_or_404(Creditor, pk=pk, user=request.user)
    all_transactions = creditor.transactions.all()

    selected_year, selected_month = _parse_year_month(request)
    transactions = all_transactions
    if selected_year:
        transactions = transactions.filter(date__year=selected_year)
    if selected_month:
        transactions = transactions.filter(date__month=selected_month)
    transactions = transactions.order_by("date", "created_at")

    stats = all_transactions.aggregate(
        borrowed=Coalesce(Sum("amount", filter=Q(transaction_type=Transaction.BORROW)), Value(0, output_field=DecimalField())),
        paid=Coalesce(Sum("amount", filter=Q(transaction_type=Transaction.REPAY)), Value(0, output_field=DecimalField())),
    )
    remaining = stats["borrowed"] - stats["paid"]

    period_label = _period_label(selected_year, selected_month)

    rows = [
        (tx.date.strftime("%d %b %Y"), tx.get_transaction_type_display(), tx.note or "-", bd_number(tx.amount))
        for tx in transactions
    ]

    return _render_statement(
        request,
        entity_label=_("Creditor"),
        entity_name=creditor.name,
        entity_meta=[(_("Phone"), creditor.phone), (_("Category"), creditor.get_category_display())],
        period_label=period_label,
        summary_rows=[
            (_("Total Borrowed"), bd_number(stats['borrowed']), ""),
            (_("Total Repaid"), bd_number(stats['paid']), "positive"),
            (_("Outstanding Balance"), bd_number(remaining), "negative" if remaining > 0 else "positive"),
        ],
        columns=[_("Date"), _("Type"), _("Note"), _("Amount (৳)")],
        rows=rows,
        back_url=request.META.get("HTTP_REFERER") or f"/creditors/{creditor.pk}/",
    )


@login_required
def creditor_list_view(request):
    valid_filter_types = {"include", "exclude"}
    filter_type = request.GET.get("filter_type", "include").strip().lower()
    if filter_type not in valid_filter_types:
        filter_type = "include"

    selected_categories = [
        category
        for category in request.GET.getlist("category")
        if category in CreditorCategory.values
    ]

    valid_payment_statuses = {"ALL", "PAID", "UNPAID"}
    payment_status = request.GET.get("payment_status", "ALL").strip().upper()
    if payment_status not in valid_payment_statuses:
        payment_status = "ALL"

    search_query = request.GET.get("q", "").strip()

    creditors_base_qs = request.user.creditors.all()
    if selected_categories:
        if filter_type == "exclude":
            creditors_base_qs = creditors_base_qs.exclude(category__in=selected_categories)
        else:
            creditors_base_qs = creditors_base_qs.filter(category__in=selected_categories)

    creditors_base_qs = party_search(creditors_base_qs, search_query)

    status, creditors_base_qs, status_counts = apply_status_filter(request, creditors_base_qs)

    creditors_qs = creditors_base_qs.annotate(
        total_borrowed_amt=Coalesce(
            Sum("transactions__amount", filter=Q(transactions__transaction_type=Transaction.BORROW)),
            Value(0, output_field=DecimalField()),
        ),
        total_paid_amt=Coalesce(
            Sum("transactions__amount", filter=Q(transactions__transaction_type=Transaction.REPAY)),
            Value(0, output_field=DecimalField()),
        ),
    )

    if payment_status == "PAID":
        creditors_qs = creditors_qs.filter(total_borrowed_amt__lte=F("total_paid_amt"))
    elif payment_status == "UNPAID":
        creditors_qs = creditors_qs.filter(total_borrowed_amt__gt=F("total_paid_amt"))

    sort = request.GET.get("sort", "name")
    if sort not in SORT_FIELDS:
        sort = "name"
    creditors_qs = creditors_qs.annotate(
        remaining_amt=F("total_borrowed_amt") - F("total_paid_amt")
    ).order_by(*SORT_FIELDS[sort])

    stats = creditors_qs.aggregate(
        total_borrowed=Coalesce(Sum("total_borrowed_amt"), Value(0, output_field=DecimalField())),
        total_paid=Coalesce(Sum("total_paid_amt"), Value(0, output_field=DecimalField())),
    )
    remaining = stats["total_borrowed"] - stats["total_paid"]

    if request.GET.get("export") == "csv":
        rows = [
            (
                cr.name,
                cr.get_category_display(),
                cr.phone,
                cr.due_date.isoformat() if cr.due_date else "",
                cr.total_borrowed_amt,
                cr.total_paid_amt,
                cr.total_borrowed_amt - cr.total_paid_amt,
                _("Paid Completely") if cr.total_borrowed_amt <= cr.total_paid_amt else _("Unpaid"),
            )
            for cr in creditors_qs
        ]
        return _csv_response(
            "creditors.csv",
            [_("Creditor"), _("Category"), _("Phone"), _("Due date"), _("Total Borrowed"), _("Total Paid"), _("Remaining Debt"), _("Status")],
            rows,
        )

    paginator = Paginator(creditors_qs, 9)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    # Calculate progress percentage manually to avoid complex template logic
    today = django.utils.timezone.localdate()
    due_soon_cutoff = today + timedelta(days=DUE_SOON_DAYS)
    for cr in page_obj:
        if cr.total_borrowed_amt > 0:
            cr.payment_percent = min(100, int((cr.total_paid_amt / cr.total_borrowed_amt) * 100))
        else:
            cr.payment_percent = 0

        cr.due_status = None
        if cr.due_date and cr.remaining_amt > 0:
            if cr.due_date < today:
                cr.due_status = "overdue"
            elif cr.due_date <= due_soon_cutoff:
                cr.due_status = "due_soon"

    base_query = request.GET.copy()
    base_query.pop("page", None)
    base_query_string = base_query.urlencode()

    context = {
        "page_obj": page_obj,
        "pagination_window": _build_pagination_window(page_obj),
        "total_borrowed": stats["total_borrowed"],
        "total_paid": stats["total_paid"],
        "remaining": remaining,
        "selected_categories": selected_categories,
        "category_choices": CreditorCategory.choices,
        "filter_type": filter_type,
        "payment_status": payment_status,
        "search_query": search_query,
        "status": status,
        "status_counts": status_counts,
        "sort": sort,
        "sort_options": SORT_OPTIONS,
        "base_query_string": base_query_string,
    }
    return render(request, "creditors/creditor_list.html", context)


@login_required
def creditor_import_template_view(request):
    rows = [(_("Karim Uddin"), "01711000000", _("Friend"), _("Borrowed for shop setup"), "5000", "2025-01-15", "")]
    return _csv_response(
        "creditor_import_template.csv",
        [_("Name"), _("Phone"), _("Category"), _("Note"), _("Opening Balance"), _("Date"), _("Due date")],
        rows,
    )


@login_required
def creditor_import_view(request):
    if request.method != "POST":
        return redirect("creditor_list")
    rows = ImportRows.open(request)
    if rows is None:
        return redirect("creditor_list")

    category_lookup = {}
    for value, label in CreditorCategory.choices:
        category_lookup[value.lower()] = value
        category_lookup[str(label).lower()] = value

    existing_names = {" ".join(n.split()).lower() for n in request.user.creditors.values_list("name", flat=True)}
    today = django.utils.timezone.localdate()
    created = 0

    for line, row in rows:
        name = " ".join(rows.value(row, "name").split())
        if not name:
            rows.blanks += 1
            continue
        if name.lower() in existing_names:
            rows.duplicates += 1
            continue

        category = category_lookup.get(rows.value(row, "category").lower(), CreditorCategory.OTHER)
        opening_balance = rows.amount(row, line, "opening balance", "opening_balance")
        since = rows.date(row, line, "date", "opening date")
        creditor = Creditor.objects.create(
            user=request.user, name=name, phone=rows.value(row, "phone"), note=rows.value(row, "note"), category=category,
            due_date=rows.date(row, line, "due date", "due_date"),
        )
        if opening_balance:
            Transaction.objects.create(
                creditor=creditor,
                transaction_type=Transaction.BORROW,
                amount=opening_balance,
                date=min(since or today, today),
                note=_("Opening balance (imported)"),
            )

        existing_names.add(name.lower())
        created += 1

    rows.report(request, created, _("Imported %(count)s creditor(s)."))
    return redirect("creditor_list")


@login_required
def transaction_edit_view(request, pk):
    transaction = get_object_or_404(Transaction, pk=pk, creditor__user=request.user)
    creditor = transaction.creditor
    if request.method == "POST":
        form = TransactionForm(request.POST, request.FILES, instance=transaction)
        if form.is_valid():
            form.save()
            messages.success(request, _("Transaction updated."))
            warn_if_overpaid(request, creditor.name, creditor.remaining)
            if transaction.transaction_type == Transaction.REPAY:
                warn_if_short(request, transaction.wallet_id)
            return redirect("creditor_detail", pk=creditor.pk)
    else:
        form = TransactionForm(instance=transaction)
    return render(request, "creditors/creditor_form.html", {"form": form, "title": _("Edit Transaction"), "back_url": reverse("creditor_detail", args=[creditor.pk])})


@login_required
@require_POST
def transaction_delete_view(request, pk):
    transaction = get_object_or_404(Transaction, pk=pk, creditor__user=request.user)
    creditor = transaction.creditor
    amount = transaction.amount
    delete_with_undo(request, transaction, _("Transaction of ৳%(amount)s deleted.") % {"amount": amount},
                     label=f"{creditor.name} · {money(amount)} · {transaction.get_transaction_type_display()}", back_url=reverse("creditor_detail", args=[creditor.pk]))
    return redirect("creditor_detail", pk=creditor.pk)


@login_required
@require_POST
def creditor_toggle_active_view(request, pk):
    obj = get_object_or_404(Creditor, pk=pk, user=request.user)
    return toggle_active(request, obj, "creditor_list")


@login_required
@require_POST
def creditor_delete_view(request, pk):
    obj = get_object_or_404(Creditor, pk=pk, user=request.user)
    return delete_record(request, obj, "creditor_list", reverse("creditor_detail", args=[pk]))
