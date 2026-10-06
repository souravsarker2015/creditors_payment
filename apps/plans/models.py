"""Installment plans (কিস্তি) for money owed either way.

"Karim pays me back ৳2,000 every month from 1 April", "I repay the shop
৳500 every week". The plan only holds the agreement; the payments are the
ordinary repayments already recorded on that creditor, debtor or shop. From
them the app works out which installments are paid, whether they're behind,
and the next date — which it keeps as the ledger's due date, so the existing
reminders, badges and "needs attention" list follow the plan.
"""
from datetime import date

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _


class Frequency(models.TextChoices):
    WEEKLY = "weekly", _("Every week")
    BIWEEKLY = "biweekly", _("Every 2 weeks")
    MONTHLY = "monthly", _("Every month")


class InstallmentPlan(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="installment_plans")
    creditor = models.OneToOneField("creditors.Creditor", on_delete=models.CASCADE, null=True, blank=True, related_name="plan")
    debtor = models.OneToOneField("debtors.Debtor", on_delete=models.CASCADE, null=True, blank=True, related_name="plan")
    shop = models.OneToOneField("shops.Shop", on_delete=models.CASCADE, null=True, blank=True, related_name="plan")
    amount = models.DecimalField(_("Each installment"), max_digits=12, decimal_places=2, validators=[MinValueValidator(1)])
    frequency = models.CharField(_("How often"), max_length=10, choices=Frequency.choices, default=Frequency.MONTHLY)
    start_date = models.DateField(_("First installment on"), default=date.today)
    note = models.CharField(_("Note"), max_length=200, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.CheckConstraint(
            condition=(models.Q(creditor__isnull=False, debtor__isnull=True, shop__isnull=True)
                       | models.Q(creditor__isnull=True, debtor__isnull=False, shop__isnull=True)
                       | models.Q(creditor__isnull=True, debtor__isnull=True, shop__isnull=False)),
            name="plan_for_exactly_one_ledger")]

    def __str__(self):
        return f"{self.party} · {self.amount} {self.get_frequency_display()}"

    @property
    def party(self):
        return self.creditor or self.debtor or self.shop

    @property
    def kind(self):
        return "creditor" if self.creditor_id else "debtor" if self.debtor_id else "shop"
