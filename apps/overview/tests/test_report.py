"""Money report: a month or a year of money in and out."""
from datetime import date
from decimal import Decimal as D

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.contributors.models import Contribution, Contributor
from apps.creditors.models import Creditor, Transaction as CreditorTx
from apps.expense.models import Expense, ExpenseCategory
from apps.household.models import HouseholdMember, Purchase
from apps.income.models import IncomeSource, IncomeTransaction

User = get_user_model()


class MoneyReportTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("rahim", password="pw")
        self.client.force_login(self.user)
        job = IncomeSource.objects.create(user=self.user, name="Salary")
        IncomeTransaction.objects.create(source=job, amount=D("50000"), date=date(2025, 3, 1))
        IncomeTransaction.objects.create(source=job, amount=D("50000"), date=date(2025, 4, 1))
        brother = Contributor.objects.create(user=self.user, name="Brother")
        Contribution.objects.create(contributor=brother, amount=D("5000"), date=date(2025, 3, 10))
        rent = ExpenseCategory.objects.create(user=self.user, name="Rent")
        Expense.objects.create(user=self.user, category=rent, amount=D("15000"), date=date(2025, 3, 5))
        Expense.objects.create(user=self.user, amount=D("700"), date=date(2025, 3, 20))
        Purchase.objects.create(user=self.user, amount=D("3000"), date=date(2025, 3, 7))
        mother = HouseholdMember.objects.create(user=self.user, name="Mother")
        Purchase.objects.create(user=self.user, buyer=mother, amount=D("999"), date=date(2025, 3, 8))   # her money, not mine
        bank = Creditor.objects.create(user=self.user, name="Bank")
        CreditorTx.objects.create(creditor=bank, transaction_type=CreditorTx.BORROW, amount=D("20000"), date=date(2025, 3, 2))
        other = User.objects.create_user("karim", password="pw")
        Expense.objects.create(user=other, amount=D("123456"), date=date(2025, 3, 5))

    def test_a_month(self):
        r = self.client.get(reverse("money_report"), {"month": "2025-03"})
        self.assertEqual(r.status_code, 200)
        c = r.context
        self.assertEqual(c["in_total"], D("55000"))
        self.assertEqual(c["out_total"], D("18700"))
        self.assertEqual(c["net"], D("36300"))
        self.assertEqual(c["savings_rate"], 66)
        self.assertEqual([row["label"] for row in c["out_rank"]], ["Rent", "Bazar (household)", "No category"])
        self.assertEqual(c["loans"]["borrowed"], D("20000"))
        self.assertEqual(c["biggest"][0]["amount"], D("15000"))
        self.assertContains(r, "March 2025")
        self.assertNotContains(r, "1,23,456")

    def test_compares_with_the_month_before(self):
        c = self.client.get(reverse("money_report"), {"month": "2025-04"}).context
        self.assertEqual(c["in_total"], D("50000"))
        self.assertEqual(c["prev_in"], D("55000"))
        self.assertEqual(c["prev_out"], D("18700"))

    def test_a_year_has_twelve_months(self):
        c = self.client.get(reverse("money_report"), {"year": "2025"}).context
        self.assertEqual(len(c["months"]), 12)
        self.assertEqual(c["months"][2]["in"], D("55000"))
        self.assertEqual(c["months"][3]["net"], D("50000"))
        self.assertEqual(c["in_total"], D("105000"))

    def test_csv(self):
        r = self.client.get(reverse("money_report"), {"month": "2025-03", "format": "csv"})
        self.assertEqual(r["Content-Type"], "text/csv; charset=utf-8")
        body = r.content.decode("utf-8-sig")
        self.assertIn("Rent,15000", body)
        self.assertIn("Salary,50000", body)

    def test_bad_period_falls_back_to_this_month_and_empty_is_friendly(self):
        r = self.client.get(reverse("money_report"), {"month": "junk", "year": "99"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["kind"], "month")
        self.assertContains(r, "Nothing was written down for this month")

    def test_needs_sign_in(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("money_report")).status_code, 302)


class BiggestSpendsIncludeCardsTests(TestCase):
    """Something bought on a credit card is spending ("Where it went" counts it), so a big one shows in "Biggest spends"."""

    def test_card_purchase_is_among_the_biggest(self):
        from apps.cards.models import Card, CardBank, CardEntry

        user = User.objects.create_user("rina", password="pw")
        self.client.force_login(user)
        card = Card.objects.create(user=user, name="UCB Visa", bank=CardBank.objects.create(user=user, name="UCB"),
                                   statement_day=5, due_day=25, limit=D("100000"), opening_date=date(2026, 1, 1))
        Expense.objects.create(user=user, amount=D("500"), date=date(2026, 3, 4))
        tv = CardEntry.objects.create(card=card, kind="spend", amount=D("42000"), date=date(2026, 3, 9), note="TV")
        CardEntry.objects.create(card=card, kind="pay", amount=D("90000"), date=date(2026, 3, 10))   # a bill paid isn't spending
        r = self.client.get(reverse("money_report"), {"month": "2026-03"})
        top = r.context["biggest"]
        self.assertEqual([row["amount"] for row in top], [D("42000"), D("500")])
        self.assertEqual(top[0]["url"], reverse("card_entry_detail", args=[tv.pk]))
        self.assertContains(r, "UCB Visa")
