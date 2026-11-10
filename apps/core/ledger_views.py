"""Helpers shared by the list, detail, statement and CSV pages of the personal
ledgers (creditors, debtors, shop dues, contributors, income, household,
expense). Each of those apps used to carry its own identical copy; a fix made
here now reaches every one of them.

The "party" helpers further down are for the three ledgers kept per person or
shop with a running balance: creditors, debtors and shop dues.
"""
import csv
import io
from datetime import date
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import dateformat, timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _, ngettext

from .csvsafe import safe_writer


# ── Lists, statements and CSV ───────────────────────────────────────────────

def _build_pagination_window(page_obj, window=2):
    """Compact list of page numbers around the current page, with None as a '…' gap."""
    total_pages = page_obj.paginator.num_pages
    current = page_obj.number
    pages = {1, total_pages}

    for page_number in range(current - window, current + window + 1):
        if 1 <= page_number <= total_pages:
            pages.add(page_number)

    compact_pages = []
    previous = None
    for page_number in sorted(pages):
        if previous is not None and page_number - previous > 1:
            compact_pages.append(None)
        compact_pages.append(page_number)
        previous = page_number
    return compact_pages


def _csv_response(filename, header, rows):
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.write("﻿")  # UTF-8 BOM so Excel renders Bangla text correctly
    writer = safe_writer(response)
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
    """List of 12 date(y, m, 1), oldest first, ending at the first of this month."""
    today = timezone.localdate()
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


def _parse_year_month(request):
    """Reads `year`/`month` GET params. Returns (year_or_None, month_or_None)."""
    raw_year = request.GET.get("year", "").strip()
    year = int(raw_year) if raw_year.isdigit() else None
    raw_month = request.GET.get("month", "").strip()
    month = int(raw_month) if raw_month.isdigit() and 1 <= int(raw_month) <= 12 else None
    return year, month


def _parse_iso_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


# ── People and shops with a running balance ─────────────────────────────────

def party_search(qs, query):
    """Narrow a list of people/shops by a search word: the name, the phone
    number (typed with or without spaces/dashes) or anything in the note."""
    query = (query or "").strip()
    if not query:
        return qs
    condition = Q(name__icontains=query) | Q(note__icontains=query)
    digits = "".join(ch for ch in query if ch.isdigit())
    if digits:
        condition |= Q(phone__icontains=digits) | Q(phone__icontains=query)
    return qs.filter(condition)


def running_balances(transactions, out_type):
    """{entry pk: what was owed right after it}, counted over every entry in
    date order — so a filtered page still shows the true balance on each row.
    `out_type` is the kind that makes the balance grow (borrowed, lent, bought
    on credit)."""
    balance, after = Decimal(0), {}
    for pk, kind, amount in transactions.order_by("date", "created_at", "pk").values_list("pk", "transaction_type", "amount"):
        balance += amount if kind == out_type else -amount
        after[pk] = balance
    return after


def attach_running_balance(transactions, all_transactions, out_type):
    """The page's entries as a list, each with `.balance_after` set (and
    `.balance_size`, the same without its sign, for "paid ৳500 too much")."""
    after = running_balances(all_transactions, out_type)
    rows = list(transactions)
    for tx in rows:
        tx.balance_after = after.get(tx.pk)
        tx.balance_size = abs(tx.balance_after) if tx.balance_after is not None else None
    return rows


def duplicate_name_error(qs, name, instance=None):
    """The error to show when the person already has a record with this name
    (case and spacing ignored), else None. Two records for one person split
    the balance in two, which is hard to notice later."""
    name = " ".join((name or "").split())
    if not name:
        return None
    others = qs.filter(name__iexact=name)
    if instance is not None and instance.pk:
        others = others.exclude(pk=instance.pk)
    if others.exists():
        return _("You already have “%(name)s”. Open that one to add to it, or make the name different (for example add the area or surname).") % {"name": name}
    return None


class UniqueNameMixin:
    """For the person/shop/source forms: refuses a second record with the same
    name as one the person already has (ignoring case and spacing), and tidies
    the spacing of the name.

    The owner is the record's own user when editing, else the signed-in person
    (set by the dashboard middleware, as WalletFieldMixin does). The quick-add
    popup turns the check off with `allow_same_name = True`, because it picks
    the existing record instead of complaining.
    """

    owner_related_name = ""        # e.g. "creditors": user.<this> lists the person's records
    allow_same_name = False

    def clean_name(self):
        name = " ".join((self.cleaned_data.get("name") or "").split())
        if self.allow_same_name or not self.owner_related_name:
            return name
        owner = self.instance.user if getattr(self.instance, "user_id", None) else None
        if owner is None:
            from apps.business.core.audit import current_user

            owner = current_user()
        if owner is None or not owner.is_authenticated:
            return name
        error = duplicate_name_error(getattr(owner, self.owner_related_name).all(), name, self.instance)
        if error:
            from django.core.exceptions import ValidationError

            raise ValidationError(error, code="duplicate_name")
        return name


def safe_next(request, fallback):
    """The `next` page on this site to return to, else `fallback`."""
    target = request.POST.get("next") or request.GET.get("next") or ""
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return target
    return fallback


# ── Importing people/shops from a CSV file ──────────────────────────────────

class ImportRows:
    """Reads an uploaded people/shops CSV and keeps count of what was taken
    and why rows were left out, so the summary can say exactly what happened.

    Usage:
        rows = ImportRows.open(request)        # None (with a message) when unreadable
        for row in rows: ...
            amount = rows.amount(row, line)    # Decimal, or None after noting a problem
            when = rows.date(row, line, "date") or today
        rows.report(request, created, noun)
    """

    def __init__(self, reader, fieldnames):
        self.reader = reader
        self.fieldnames = fieldnames
        self.duplicates = 0
        self.blanks = 0
        self.problems = []          # "Row 4: ..." lines, shown (first few) in the summary

    @classmethod
    def open(cls, request, required="name"):
        csv_file = request.FILES.get("csv_file")
        if not csv_file:
            messages.error(request, _("Please choose a CSV file to import."))
            return None
        try:
            decoded = csv_file.read().decode("utf-8-sig")
        except UnicodeDecodeError:
            messages.error(request, _("Could not read that file. Please upload a UTF-8 encoded CSV."))
            return None
        reader = csv.DictReader(io.StringIO(decoded))
        if not reader.fieldnames:
            messages.error(request, _("The CSV file appears to be empty."))
            return None
        fieldnames = {(f or "").strip().lower(): f for f in reader.fieldnames}
        if required not in fieldnames:
            messages.error(request, _("The CSV must have a 'Name' column."))
            return None
        return cls(reader, fieldnames)

    def __iter__(self):
        # Line 1 is the header, so the first record is on line 2 — the number a
        # spreadsheet shows next to it.
        for line, row in enumerate(self.reader, start=2):
            yield line, row

    def value(self, row, *keys):
        for key in keys:
            found = _row_value(row, self.fieldnames, key)
            if found:
                return found
        return ""

    def amount(self, row, line, *keys):
        """The opening balance in the row: Decimal (0 when the cell is empty), or
        None when it can't be read — the person is still added, without it."""
        raw = self.value(row, *keys).replace(",", "").replace("৳", "").strip()
        if not raw:
            return Decimal(0)
        try:
            value = Decimal(raw)
        except InvalidOperation:
            value = None
        if value is None or not value.is_finite() or value < 0:
            self.problems.append(_("Row %(line)s: “%(value)s” isn't an amount, so no opening balance was added.") % {"line": line, "value": raw})
            return None
        return value

    def date(self, row, line, *keys):
        """A date from the row (2025-01-31 or 31/01/2025), None when empty or unreadable."""
        raw = self.value(row, *keys)
        if not raw:
            return None
        parsed = _parse_iso_date(raw)
        if parsed is None:
            for sep in ("/", "-", "."):
                parts = raw.split(sep)
                if len(parts) == 3 and all(p.isdigit() for p in parts) and len(parts[2]) == 4:
                    try:
                        parsed = date(int(parts[2]), int(parts[1]), int(parts[0]))
                    except ValueError:
                        parsed = None
                    break
        if parsed is None:
            self.problems.append(_("Row %(line)s: “%(value)s” isn't a date (use 2025-01-31 or 31/01/2025), so it was left empty.") % {"line": line, "value": raw})
        return parsed

    def report(self, request, created, done_message):
        """Flash the summary: how many were added, what was skipped, and the first
        few rows that had something the app couldn't read."""
        if created:
            messages.success(request, done_message % {"count": created})
        skipped = self.duplicates + self.blanks
        if skipped:
            messages.warning(
                request,
                _("Skipped %(count)s row(s): %(dup)s duplicate name(s), %(blank)s blank name(s).")
                % {"count": skipped, "dup": self.duplicates, "blank": self.blanks},
            )
        if self.problems:
            shown = self.problems[:5]
            more = len(self.problems) - len(shown)
            text = " ".join(shown)
            if more:
                text += " " + ngettext("…and %(count)s more row like this.", "…and %(count)s more rows like this.", more) % {"count": more}
            messages.warning(request, text)
        if not created and not skipped:
            messages.error(request, _("No rows found to import."))
