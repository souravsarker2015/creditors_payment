"""The Zakat sheet: lines worked out from the app's records, plus what you type."""
from dataclasses import dataclass, field
from decimal import Decimal

from django.db.models import DecimalField, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.utils.translation import gettext as _

from .models import GOLD_NISAB_G, RATE, SILVER_NISAB_G

ZERO = Decimal(0)


def dec(v):
    return v if isinstance(v, Decimal) else Decimal(str(v or 0))


@dataclass
class Line:
    key: str
    label: str
    amount: Decimal
    hint: str = ""
    side: str = "own"          # own | owe
    auto: bool = True
    full: Decimal | None = None  # a farm line before your share is applied


@dataclass
class Sheet:
    settings: object
    lines: list = field(default_factory=list)

    def _sum(self, side):
        return sum((l.amount for l in self.lines if l.side == side and l.key not in self.settings.skip), ZERO)

    @property
    def own(self):
        return self._sum("own")

    @property
    def owe(self):
        return self._sum("owe")

    @property
    def net(self):
        return self.own - self.owe

    @property
    def nisab(self):
        s = self.settings
        return (SILVER_NISAB_G * dec(s.silver_price) if s.basis == "silver" else GOLD_NISAB_G * dec(s.gold_price)).quantize(Decimal("1"))

    @property
    def due(self):
        return (self.net * RATE).quantize(Decimal("1")) if (self.nisab and self.net >= self.nisab) else ZERO


def _positive_balances(qs, out_type, back_type):
    rows = qs.annotate(
        out=Coalesce(Sum("transactions__amount", filter=Q(transactions__transaction_type=out_type)), Value(0, output_field=DecimalField())),
        back=Coalesce(Sum("transactions__amount", filter=Q(transactions__transaction_type=back_type)), Value(0, output_field=DecimalField())),
    )
    return sum((max(r.out - r.back, ZERO) for r in rows), ZERO)


def sheet(request, settings):
    from apps.creditors.models import Creditor, Transaction as CT
    from apps.debtors.models import Debtor, Transaction as DT
    from apps.shops.models import Shop, Transaction as ST
    from apps.wallets.models import Wallet
    from apps.wallets.services import balances

    user = request.user
    s = Sheet(settings)
    wallets = list(Wallet.objects.filter(user=user, is_active=True))
    if wallets:
        held = balances(user)
        s.lines.append(Line("wallets", _("Cash, bank & bKash (your wallets)"), sum((max(held.get(w.pk, ZERO), ZERO) for w in wallets), ZERO),
                            ", ".join(w.name for w in wallets)))
    else:
        from apps.goals.services import totals

        saved = totals(user)["saved"]
        if saved:
            s.lines.append(Line("goals", _("Saved in your goals"), saved, _("Add your wallets to count cash and bank instead.")))
    s.lines.append(Line("debtors", _("Money others owe you"), _positive_balances(Debtor.objects.filter(user=user), DT.LEND, DT.RECEIVE),
                        _("Debts you expect to get back.")))
    st = settings
    gold = (dec(st.gold_grams) * dec(st.gold_price)).quantize(Decimal("1"))
    silver = (dec(st.silver_grams) * dec(st.silver_price)).quantize(Decimal("1"))
    s.lines.append(Line("gold", _("Gold you own"), gold, _("%(g)s g × price per gram") % {"g": format(dec(st.gold_grams).normalize(), "f")}, auto=False))
    s.lines.append(Line("silver", _("Silver you own"), silver, _("%(g)s g × price per gram") % {"g": format(dec(st.silver_grams).normalize(), "f")}, auto=False))
    s.lines.append(Line("other_assets", _("Other savings & investments"), dec(st.other_assets), _("Typed in below."), auto=False))

    s.lines.append(Line("creditors", _("What you owe creditors"), _positive_balances(Creditor.objects.filter(user=user), CT.BORROW, CT.REPAY),
                        side="owe"))
    s.lines.append(Line("shops", _("Shop dues"), _positive_balances(Shop.objects.filter(user=user), ST.PURCHASE, ST.PAYMENT), side="owe"))
    household = sum((m.balance_due for m in user.household_members.with_balances() if m.balance_due > 0), ZERO)
    if household:
        s.lines.append(Line("household", _("Owed to family for bazar"), household, side="owe"))
    s.lines.append(Line("other_debts", _("Other debts due now"), dec(st.other_debts), _("Typed in below."), side="owe", auto=False))
    _farm(request, s)
    return s


def _farm(request, s):
    """The farm's cash and dues, at your share — only for someone who may see its money."""
    from apps.business.core.access import BUSINESS, active_membership, can, has_dashboard

    if not has_dashboard(request.user, BUSINESS):
        return
    m = active_membership(request)
    if m is None or not can(m, "view_finance"):
        return
    from apps.business.credit.services import totals as baki
    from apps.business.finance.services import balances

    share = Decimal(s.settings.farm_share) / 100
    name = m.business.name
    cash = sum((max(v, ZERO) for v in balances(m.business).values()), ZERO)
    dues = baki(m.business)
    note = _("%(farm)s, at your %(pct)s%% share") % {"farm": name, "pct": s.settings.farm_share}
    for key, label, full, side in (("farm_cash", _("Farm cash & bank"), cash, "own"),
                                   ("farm_receivable", _("Farm baki to collect"), dues["receivable"], "own"),
                                   ("farm_payable", _("Farm baki to pay"), dues["payable"], "owe")):
        s.lines.append(Line(key, label, (full * share).quantize(Decimal("1")), note, side=side, full=full))
