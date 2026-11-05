"""Expenses from a spreadsheet or a bank / bKash statement saved as CSV, as Wallet and Monarch
take them in. Columns are found by their usual names, dates in the usual ways, and a file
brought in twice doesn't count anything twice."""
import csv
import io
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.db import transaction

from .models import Expense, ExpenseCategory

MAX_ROWS = 5000

# column → the names banks and spreadsheets give it (lower case)
COLUMNS = {
    "date": ("date", "transaction date", "txn date", "value date", "posting date", "তারিখ"),
    "amount": ("amount", "debit", "withdrawal", "withdrawals", "spent", "paid", "dr", "টাকা", "পরিমাণ"),
    "credit": ("credit", "deposit", "deposits", "cr"),
    "category": ("category", "type", "ক্যাটাগরি", "খাত"),
    "wallet": ("wallet", "account", "ওয়ালেট"),
    "note": ("note", "notes", "description", "details", "narration", "particulars", "remarks", "memo", "বিবরণ"),
}
DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y", "%d-%m-%y", "%d %b %Y", "%d %B %Y",
                "%d-%b-%Y", "%d-%b-%y", "%b %d, %Y", "%Y/%m/%d")
BANGLA_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")


def parse_date(text):
    text = (text or "").strip().translate(BANGLA_DIGITS)
    if not text:
        return None
    text = text.split("T")[0].split(" ")[0] if len(text) > 10 and text[4:5] == "-" else text
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_amount(text):
    """'৳1,250.50', '-1250.5', '(1,250)' or '১২৫০' → 1250.50; anything else → None."""
    text = (text or "").strip().translate(BANGLA_DIGITS)
    for junk in ("৳", "Tk.", "Tk", "BDT", ",", " "):
        text = text.replace(junk, "")
    if text.startswith("(") and text.endswith(")"):
        text = text[1:-1]
    try:
        value = abs(Decimal(text))
    except InvalidOperation:
        return None
    return value.quantize(Decimal("0.01")) if value else None


def _columns(fieldnames):
    found = {}
    for raw in fieldnames:
        name = " ".join((raw or "").strip().lower().split())
        for key, names in COLUMNS.items():
            if key not in found and name in names:
                found[key] = raw
    return found


def read(user, uploaded):
    """Brings the rows in. Returns a summary: added, new categories, and what was left out and why."""
    result = {"added": 0, "categories": 0, "duplicate": 0, "bad_date": 0, "bad_amount": 0, "income": 0,
              "unknown_wallet": 0, "error": None}
    try:
        text = uploaded.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        result["error"] = "encoding"
        return result
    reader = csv.DictReader(io.StringIO(text))
    cols = _columns(reader.fieldnames or [])
    if "date" not in cols or "amount" not in cols:
        result["error"] = "columns"
        return result

    def get(row, key):
        return (row.get(cols[key]) or "").strip() if key in cols else ""

    categories = {c.name.lower(): c for c in ExpenseCategory.objects.filter(user=user)}
    wallets = {w.name.lower(): w for w in user.wallets.all()}
    seen = {(e["date"], e["amount"], e["note"], e["category_id"]) for e in
            Expense.objects.filter(user=user).values("date", "amount", "note", "category_id")}
    new = []
    with transaction.atomic():
        for n, row in enumerate(reader):
            if n >= MAX_ROWS:
                break
            raw_amount = get(row, "amount")
            if not raw_amount and get(row, "credit"):
                result["income"] += 1            # money coming in: not an expense
                continue
            day, amount = parse_date(get(row, "date")), parse_amount(raw_amount)
            if not day:
                result["bad_date"] += 1
                continue
            if amount is None:
                result["bad_amount"] += 1
                continue
            category = None
            name = " ".join(get(row, "category").split())[:100]
            if name:
                category = categories.get(name.lower())
                if category is None:
                    category = categories[name.lower()] = ExpenseCategory.objects.create(user=user, name=name)
                    result["categories"] += 1
            wallet = None
            if get(row, "wallet"):
                wallet = wallets.get(get(row, "wallet").lower())
                if wallet is None:
                    result["unknown_wallet"] += 1
            note = get(row, "note")
            key = (day, amount, note, category.pk if category else None)
            if key in seen:
                result["duplicate"] += 1
                continue
            seen.add(key)
            new.append(Expense(user=user, date=day, amount=amount, category=category, wallet=wallet, note=note))
        Expense.objects.bulk_create(new)
    result["added"] = len(new)
    return result


def template_rows(today=None):
    today = today or date.today()
    return [(today.isoformat(), "350", "Groceries", "", "Rice and lentils"),
            (today.isoformat(), "120", "Transport", "", "Rickshaw")]
