"""Where your own money is kept: cash in hand, bank, bKash/Nagad.

A wallet's balance is never typed in after the start. It is worked out:

    balance = opening balance + money in − money out

from the entries that say which wallet they used (an expense, an income, a
creditor/debtor/shop payment, a bazar purchase, a settlement, a contribution),
transfers between wallets, and balance corrections. Entries with no wallet
still count everywhere else; they just don't move a wallet.
"""
from datetime import date

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class WalletKind(models.TextChoices):
    CASH = "cash", _("Cash in hand")
    BANK = "bank", _("Bank account")
    MOBILE = "mobile", _("Mobile banking (bKash, Nagad…)")
    OTHER = "other", _("Other")


class Wallet(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="wallets")
    name = models.CharField(_("Name"), max_length=80)
    kind = models.CharField(_("Type"), max_length=8, choices=WalletKind.choices, default=WalletKind.CASH)
    number = models.CharField(_("Account / wallet number"), max_length=40, blank=True)
    opening_balance = models.DecimalField(_("Balance when you start"), max_digits=12, decimal_places=2, default=0)
    opening_date = models.DateField(_("As of"), default=date.today)
    is_default = models.BooleanField(_("Use by default"), default=False, help_text=_("Picked first when you record money in or out."))
    is_active = models.BooleanField(_("In use"), default=True)
    note = models.TextField(_("Note"), blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-is_default", "name"]
        constraints = [models.UniqueConstraint(fields=["user", "name"], name="wallet_name_unique_per_user")]

    def __str__(self):
        return self.name


class Transfer(models.Model):
    """Money moved between two of your wallets, e.g. cash out from bKash."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="wallet_transfers")
    from_wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE, related_name="transfers_out", verbose_name=_("From"))
    to_wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE, related_name="transfers_in", verbose_name=_("To"))
    amount = models.DecimalField(_("Amount"), max_digits=12, decimal_places=2)
    fee = models.DecimalField(_("Fee / charge"), max_digits=12, decimal_places=2, default=0,
                              help_text=_("e.g. the bKash cash-out charge. It comes out of the “From” wallet."))
    date = models.DateField(_("Date"), default=date.today)
    note = models.TextField(_("Note"), blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"{self.from_wallet} → {self.to_wallet} · {self.amount}"


class Adjustment(models.Model):
    """A balance correction: the app said one thing, the wallet really holds another."""

    wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE, related_name="adjustments")
    amount = models.DecimalField(_("Amount"), max_digits=12, decimal_places=2, help_text="Signed: + adds to the balance, − takes away.")
    date = models.DateField(_("Date"), default=date.today)
    note = models.TextField(_("Note"), blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"{self.wallet} {self.amount:+}"
