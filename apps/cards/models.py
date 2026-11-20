"""Credit cards: what you owe on each card, its bills (statements), the money
you take out of it to bKash/Nagad/Rocket, how you pay it back, and every fee
on the way.

    Card          one credit card (UCB, EBL, DBBL… any bank). The number is
                  never stored — at most its last 4 digits, and only if you want.
    MfsFees       the charges of one mobile-banking wallet (bKash, Nagad,
                  Rocket… they are ordinary Wallets): paying a card bill
                  straight from it, or sending money to a bank account /
                  debit card first.
    CardEntry     one thing that happened on a card: money taken out to a
                  wallet (+ the card's fee), something bought, a bank charge,
                  a bill payment (+ the wallet's fee), a refund, a correction.
    EmiPlan       part of a card's balance turned into monthly installments.

What you owe on a card is never typed in after the start; it is worked out
(services.py) from the opening balance and the entries, the same way a
wallet's balance is. Money taken out to a wallet adds to that wallet, a bill
paid from a wallet takes the payment and its fee out of it.
"""
from datetime import date

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.utils.dates import MONTHS as MONTH_NAMES
from django.utils.translation import gettext_lazy as _

MONTHS = list(MONTH_NAMES.items())
DAY = [MinValueValidator(1), MaxValueValidator(31)]
RATE = [MinValueValidator(0), MaxValueValidator(100)]


class _Named(models.Model):
    """A name you pick from a list you keep yourself, with a + beside the dropdown to add one."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    name = models.CharField(_("Name"), max_length=80)
    is_active = models.BooleanField(_("In use"), default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True
        ordering = ["name"]

    def __str__(self):
        return self.name


class CardBank(_Named):
    """UCB, EBL, DBBL, City Bank… — the banks your cards are from."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="card_banks")

    class Meta(_Named.Meta):
        constraints = [models.UniqueConstraint(fields=["user", "name"], name="card_bank_unique_per_user")]


class CardNetwork(_Named):
    """Visa, Mastercard, American Express… — the kinds of card."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="card_networks")

    class Meta(_Named.Meta):
        constraints = [models.UniqueConstraint(fields=["user", "name"], name="card_network_unique_per_user")]


DEFAULT_NETWORKS = ("Visa", "Mastercard", "American Express", "UnionPay", "JCB", "Diners Club")


class CardColor(models.TextChoices):
    BLUE = "blue", _("Blue")
    GREEN = "green", _("Green")
    PURPLE = "purple", _("Purple")
    RED = "red", _("Red")
    GOLD = "gold", _("Gold")
    TEAL = "teal", _("Teal")
    SLATE = "slate", _("Silver")
    BLACK = "black", _("Black")


class Card(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="cards")
    name = models.CharField(_("Card name"), max_length=80)
    bank = models.ForeignKey(CardBank, on_delete=models.SET_NULL, null=True, blank=True, related_name="cards", verbose_name=_("Bank"))
    network = models.ForeignKey(CardNetwork, on_delete=models.SET_NULL, null=True, blank=True, related_name="cards", verbose_name=_("Card type"))
    last4 = models.CharField(_("Last 4 digits"), max_length=4, blank=True, default="",
                             validators=[RegexValidator(r"^\d{4}$", _("Enter the last 4 digits only."))])
    expiry = models.CharField(_("Expires (MM/YY)"), max_length=5, blank=True, default="",
                              validators=[RegexValidator(r"^(0[1-9]|1[0-2])/\d{2}$", _("Write it like 08/28."))])
    limit = models.DecimalField(_("Credit limit"), max_digits=12, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)])
    cash_limit = models.DecimalField(_("Cash / transfer limit"), max_digits=12, decimal_places=2, null=True, blank=True,
                                     validators=[MinValueValidator(0)])
    statement_day = models.PositiveSmallIntegerField(_("Bill (statement) day"), validators=DAY)
    due_day = models.PositiveSmallIntegerField(_("Pay-by day"), validators=DAY)
    transfer_fee_rate = models.DecimalField(_("Fee to send money to bKash / Nagad"), max_digits=5, decimal_places=2, default=0, validators=RATE)
    interest_rate = models.DecimalField(_("Interest a year"), max_digits=5, decimal_places=2, null=True, blank=True, validators=RATE)
    min_due_rate = models.DecimalField(_("Minimum payment"), max_digits=5, decimal_places=2, default=5, validators=RATE)
    min_due_floor = models.DecimalField(_("…but at least"), max_digits=12, decimal_places=2, default=500, validators=[MinValueValidator(0)])
    late_fee = models.DecimalField(_("Late fee"), max_digits=12, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)])
    annual_fee = models.DecimalField(_("Annual fee"), max_digits=12, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)])
    annual_fee_month = models.PositiveSmallIntegerField(_("Annual fee month"), choices=MONTHS, null=True, blank=True)
    opening_balance = models.DecimalField(_("Already owed when you start"), max_digits=12, decimal_places=2, default=0)
    opening_date = models.DateField(_("As of"), default=date.today)
    color = models.CharField(_("Colour"), max_length=8, choices=CardColor.choices, default=CardColor.BLUE)
    is_active = models.BooleanField(_("In use"), default=True)
    note = models.TextField(_("Note"), blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-is_active", "name"]
        constraints = [models.UniqueConstraint(fields=["user", "name"], name="card_name_unique_per_user")]

    def __str__(self):
        return self.name

    @property
    def masked(self):
        return f"•••• {self.last4}" if self.last4 else ""


class MfsFees(models.Model):
    """The charges of one mobile-banking wallet when it is used for a card."""

    wallet = models.OneToOneField("wallets.Wallet", on_delete=models.CASCADE, related_name="card_fees")
    bill_rate = models.DecimalField(_("Pay a card bill straight from it"), max_digits=5, decimal_places=2, default=0, validators=RATE)
    pays_bills = models.BooleanField(_("Can pay card bills"), default=True)
    bank_rate = models.DecimalField(_("Send to a bank account / debit card"), max_digits=5, decimal_places=2, default=0, validators=RATE)
    note = models.CharField(_("Note"), max_length=200, blank=True, default="")

    def __str__(self):
        return str(self.wallet)


class EntryKind(models.TextChoices):
    CASH = "cash", _("Money taken out")
    SPEND = "spend", _("Bought with the card")
    CHARGE = "charge", _("Bank charge")
    PAY = "pay", _("Bill paid")
    REFUND = "refund", _("Refund / cashback")
    ADJUST = "adjust", _("Balance corrected")


class ChargeType(models.TextChoices):
    INTEREST = "interest", _("Interest")
    LATE = "late", _("Late fee")
    ANNUAL = "annual", _("Annual fee")
    VAT = "vat", _("VAT / tax")
    OTHER = "other", _("Other charge")


class PayRoute(models.TextChoices):
    DIRECT = "direct", _("Straight from the bank or cash")
    MFS_BILL = "mfs_bill", _("Bill pay in bKash / Nagad / Rocket")
    MFS_BANK = "mfs_bank", _("Mobile banking → bank / debit card → card")


class CardEntry(models.Model):
    card = models.ForeignKey(Card, on_delete=models.CASCADE, related_name="entries")
    kind = models.CharField(_("What happened"), max_length=8, choices=EntryKind.choices)
    charge_type = models.CharField(_("Charge"), max_length=10, choices=ChargeType.choices, blank=True, default="")
    route = models.CharField(_("How you paid"), max_length=10, choices=PayRoute.choices, blank=True, default="")
    amount = models.DecimalField(_("Amount"), max_digits=12, decimal_places=2)
    fee_rate = models.DecimalField(_("Fee"), max_digits=5, decimal_places=2, null=True, blank=True, validators=RATE)
    fee = models.DecimalField(_("Fee amount"), max_digits=12, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    wallet = models.ForeignKey("wallets.Wallet", on_delete=models.SET_NULL, null=True, blank=True, related_name="+", verbose_name=_("Wallet"))
    date = models.DateField(_("Date"), default=date.today)
    note = models.CharField(_("Note"), max_length=200, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]
        indexes = [models.Index(fields=["card", "date"])]

    def __str__(self):
        return f"{self.card} · {self.get_kind_display()} · {self.amount}"

    @property
    def debt(self):
        """How much this adds to (+) or takes off (−) what you owe on the card."""
        if self.kind == EntryKind.CASH:
            return self.amount + self.fee          # the card's own fee is billed on the card
        if self.kind in (EntryKind.PAY, EntryKind.REFUND):
            return -self.amount                    # a payment's fee is the wallet's, not the card's
        return self.amount                         # spend, charge, adjust (signed)

    @property
    def total(self):
        """Amount plus fee: what reached the card from a wallet (a payment), or what the card owes (money taken out)."""
        return self.amount + self.fee

    @property
    def title(self):
        if self.kind == EntryKind.CHARGE and self.charge_type:
            return self.get_charge_type_display()
        return self.get_kind_display()


class EmiPlan(models.Model):
    """Part of a card's balance paid in equal monthly installments, one on each bill."""

    card = models.ForeignKey(Card, on_delete=models.CASCADE, related_name="emis")
    title = models.CharField(_("What for"), max_length=120)
    amount = models.DecimalField(_("Amount turned into EMI"), max_digits=12, decimal_places=2, validators=[MinValueValidator(1)])
    months = models.PositiveSmallIntegerField(_("Months"), validators=[MinValueValidator(2), MaxValueValidator(60)])
    rate = models.DecimalField(_("Interest a year"), max_digits=5, decimal_places=2, default=0, validators=RATE)
    fee = models.DecimalField(_("Processing fee"), max_digits=12, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    start = models.DateField(_("Started on"), default=date.today)
    closed_on = models.DateField(_("Paid off early on"), null=True, blank=True)
    note = models.CharField(_("Note"), max_length=200, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-start", "-id"]

    def __str__(self):
        return f"{self.card} · {self.title}"
