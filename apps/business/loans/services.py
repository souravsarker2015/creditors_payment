from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import Prefetch

from . import schedule as engine
from .models import Lender, Loan, LoanRateChange, LoanTransaction, LoanTxnKind

ZERO = Decimal("0")


def loans_for(business, *, closed=None, deleted=False, lender=None):
    manager = Loan.all_objects if deleted else Loan.objects
    qs = manager.filter(business=business, is_deleted=deleted).select_related("lender").prefetch_related(
        Prefetch("transactions", queryset=LoanTransaction.objects.all()),
        Prefetch("rate_changes", queryset=LoanRateChange.objects.all()),
    )
    if closed is not None:
        qs = qs.filter(closed_on__isnull=not closed)
    if lender:
        qs = qs.filter(lender=lender)
    return qs


def overview(business, today=None):
    """Totals across the open loans, for the Loans page and the business home."""
    today = today or date.today()
    loans = list(loans_for(business, closed=False))
    rows = [(loan, loan.schedule(today)) for loan in loans]
    upcoming = sorted(((s.next_due, loan) for loan, s in rows if s.next_due), key=lambda x: x[0].due)
    year_start = date(today.year, 1, 1)
    interest_year = sum((t.interest for loan in loans for t in loan.transactions.all()
                         if t.kind == LoanTxnKind.PAYMENT and t.date >= year_start), ZERO)
    return {
        "rows": rows,
        "count": len(loans),
        "outstanding": sum((s.outstanding for _, s in rows), ZERO),
        "borrowed": sum((s.borrowed for _, s in rows), ZERO),
        "overdue": sum((s.overdue for _, s in rows), ZERO),
        "overdue_loans": sum(1 for _, s in rows if s.overdue_periods),
        "payoff": sum((s.payoff for _, s in rows), ZERO),
        "interest_year": interest_year,
        "next": upcoming[0] if upcoming else None,   # (period, loan)
        "due_soon": [(p, loan) for p, loan in upcoming if (p.due - today).days <= 30][:5],
    }


def preview(terms, today=None):
    """Summary of a loan that hasn't been saved yet (the form's live preview)."""
    s = engine.build(terms, today=terms.taken_on)
    periods = s.periods
    return {
        "count": len(periods),
        "instalment": s.instalment,
        "first": periods[0] if periods else None,
        "last": periods[-1] if periods else None,
        "interest": s.interest_planned,
        "total": s.borrowed + s.interest_planned,
        "open_ended": not terms.maturity,
        "periods": periods[:4],
    }


@transaction.atomic
def pay_past_dues(loan, today=None, paid_via="cash"):
    """For a loan entered after the fact: record every overdue payment as paid
    on its due date. Returns how many payments were added."""
    s = loan.schedule(today)
    added = 0
    for p in s.overdue_periods:
        LoanTransaction.objects.create(
            business=loan.business, loan=loan, kind=LoanTxnKind.PAYMENT, date=p.due,
            principal=p.principal_left, interest=p.interest_left, paid_via=paid_via,
        )
        added += 1
    loan.refresh_from_db()
    return added


def lender_totals(business):
    """Outstanding and loan count per lender id."""
    out = {}
    for loan in loans_for(business, closed=False):
        row = out.setdefault(loan.lender_id, {"count": 0, "outstanding": ZERO})
        row["count"] += 1
        row["outstanding"] += loan.schedule().outstanding
    return out


def lenders_for(business, deleted=False):
    manager = Lender.all_objects if deleted else Lender.objects
    return manager.filter(business=business, is_deleted=deleted)
