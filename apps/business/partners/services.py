from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from django.db.models import Sum

from .models import EntryKind, Partner, PartnerEntry

ZERO = Decimal(0)
HUNDRED = Decimal(100)


@dataclass
class Khata:
    partner: Partner
    put_in: Decimal = ZERO       # before the app + since
    taken_out: Decimal = ZERO

    @property
    def net(self):
        """Their money still in the business."""
        return self.put_in - self.taken_out


def khatas(business, partners=None):
    """{partner id: Khata}, with one query for all the entries."""
    partners = list(partners if partners is not None else Partner.objects.filter(business=business))
    out = {p.pk: Khata(p, p.opening_capital) for p in partners}
    rows = (PartnerEntry.objects.filter(business=business, partner_id__in=list(out))
            .values("partner_id", "kind").annotate(t=Sum("amount")))
    for r in rows:
        k = out[r["partner_id"]]
        if r["kind"] == EntryKind.IN:
            k.put_in += r["t"]
        else:
            k.taken_out += r["t"]
    return out


@dataclass
class ShareRow:
    partner: Partner
    share: Decimal       # of the period's profit (negative for a loss)
    put_in: Decimal      # in the period
    taken: Decimal       # in the period

    @property
    def left(self):
        """Still theirs to take (+), or taken beyond their share (−)."""
        return self.share - self.taken


@dataclass
class Sharing:
    start: date
    end: date
    profit: Decimal
    income: Decimal
    expense: Decimal
    rows: list = field(default_factory=list)

    @property
    def total_pct(self):
        return sum((r.partner.share_pct for r in self.rows), ZERO)

    @property
    def unshared(self):
        """Profit nobody's share covers, when the shares add up to less than 100."""
        return (self.profit * (HUNDRED - self.total_pct) / HUNDRED).quantize(Decimal("1")) if self.total_pct < HUNDRED else ZERO

    @property
    def taken(self):
        return sum((r.taken for r in self.rows), ZERO)


def sharing(business, start, end):
    """The farm's profit between two dates, split by each partner's share."""
    from apps.business.finance.services import statement

    s = statement(business, start, end)
    partners = list(Partner.objects.filter(business=business))
    moved = {}
    for r in (PartnerEntry.objects.filter(business=business, date__gte=start, date__lte=end)
              .values("partner_id", "kind").annotate(t=Sum("amount"))):
        moved[(r["partner_id"], r["kind"])] = r["t"]
    rows = [ShareRow(p, (s.profit * p.share_pct / HUNDRED).quantize(Decimal("1")),
                     moved.get((p.pk, EntryKind.IN), ZERO), moved.get((p.pk, EntryKind.OUT), ZERO)) for p in partners]
    return Sharing(start, end, s.profit, s.total_income, s.total_expense, rows)


def other_shares(business, exclude_pk=None):
    """The shares already given to other partners."""
    qs = Partner.objects.filter(business=business)
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    return qs.aggregate(t=Sum("share_pct"))["t"] or ZERO
