"""Home (the personal start page), the "Record money" picker and the help page."""
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.creditors.models import Creditor, Transaction as CreditorTransaction
from apps.debtors.models import Debtor, Transaction as DebtorTransaction
from apps.expense.models import Expense
from apps.income.models import IncomeSource, IncomeTransaction
from apps.wallets.models import Wallet


class HomeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="home_user", password="secret123")
        self.client.force_login(self.user)

    def test_root_is_home_and_login_lands_there(self):
        self.client.logout()
        r = self.client.post(reverse("login"), {"username": "home_user", "password": "secret123"}, follow=True)
        self.assertEqual(r.redirect_chain[-1][0], reverse("home"))
        self.assertEqual(reverse("home"), "/")
        self.assertTemplateUsed(r, "overview/networth.html")
        self.assertContains(r, "Money you have now")
        for kind in ("income", "borrow", "repay", "lend", "collect"):
            self.assertContains(r, reverse("pick", args=[kind]))

    def test_creditors_overview_still_works_at_its_new_address(self):
        self.assertEqual(reverse("dashboard"), "/creditors/overview/")
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)

    def test_settled_is_wallets_plus_owed_to_you_minus_you_owe(self):
        Wallet.objects.create(user=self.user, name="Cash", opening_balance=Decimal("5000"), opening_date=date(2026, 1, 1))
        d = Debtor.objects.create(user=self.user, name="Rafi")
        DebtorTransaction.objects.create(debtor=d, transaction_type=DebtorTransaction.LEND, amount=Decimal("700"), date=date(2026, 1, 2))
        c = Creditor.objects.create(user=self.user, name="Karim")
        CreditorTransaction.objects.create(creditor=c, transaction_type=CreditorTransaction.BORROW, amount=Decimal("2000"), date=date(2026, 1, 2))
        ctx = self.client.get(reverse("home")).context
        # Lending 700 from no wallet and borrowing 2000 into none leaves the wallet at 5000.
        self.assertEqual(ctx["wallets_total"], Decimal("5000"))
        self.assertEqual(ctx["settled"], Decimal("5000") + Decimal("700") - Decimal("2000"))

    def test_start_here_guides_a_new_person_and_goes_away_when_done(self):
        starter = self.client.get(reverse("home")).context["starter"]
        self.assertEqual((starter["done"], starter["total"]), (0, 5))
        from apps.budgets.models import Budget  # noqa: F401  (a goal counts as planning too)
        from apps.goals.models import SavingsGoal

        Wallet.objects.create(user=self.user, name="Cash")
        src = IncomeSource.objects.create(user=self.user, name="Salary")
        IncomeTransaction.objects.create(source=src, amount=Decimal("100"), date=date(2026, 1, 1))
        Expense.objects.create(user=self.user, amount=Decimal("50"), date=date(2026, 1, 1))
        Creditor.objects.create(user=self.user, name="Karim")
        SavingsGoal.objects.create(user=self.user, name="Eid", target_amount=Decimal("1000"))
        self.assertIsNone(self.client.get(reverse("home")).context["starter"])

    def test_recent_entries_mix_every_ledger_newest_first(self):
        Expense.objects.create(user=self.user, amount=Decimal("50"), date=date(2026, 3, 1))
        c = Creditor.objects.create(user=self.user, name="Karim")
        CreditorTransaction.objects.create(creditor=c, transaction_type=CreditorTransaction.REPAY, amount=Decimal("80"), date=date(2026, 3, 5))
        recent = self.client.get(reverse("home")).context["recent"]
        self.assertEqual([(r["title"], r["amount"]) for r in recent], [("Karim", Decimal("-80")), ("General", Decimal("-50"))])


class PickTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="pick_user", password="secret123")
        self.client.force_login(self.user)

    def test_paying_back_lists_people_you_owe_first(self):
        paid = Creditor.objects.create(user=self.user, name="Aaron")
        owed = Creditor.objects.create(user=self.user, name="Zaman")
        CreditorTransaction.objects.create(creditor=owed, transaction_type=CreditorTransaction.BORROW, amount=Decimal("900"), date=date(2026, 1, 1))
        Creditor.objects.create(user=User.objects.create_user("other"), name="Not mine")
        r = self.client.get(reverse("pick", args=["repay"]))
        items = r.context["items"]
        self.assertEqual([i["name"] for i in items], ["Zaman", "Aaron"])
        self.assertEqual(items[0]["url"], f"{reverse('creditor_detail', args=[owed.pk])}?record=REPAY#record")
        self.assertContains(r, "You owe")
        self.assertNotContains(r, "Not mine")
        self.assertIsNotNone(paid)

    def test_unknown_kind_is_404(self):
        self.assertEqual(self.client.get(reverse("pick", args=["nope"])).status_code, 404)

    def test_detail_page_preselects_the_kind_and_opens_the_form(self):
        c = Creditor.objects.create(user=self.user, name="Karim")
        r = self.client.get(reverse("creditor_detail", args=[c.pk]) + "?record=REPAY")
        self.assertEqual(r.context["form"].initial["transaction_type"], "REPAY")
        self.assertContains(r, 'id="record"')
        # Anything else is ignored
        r = self.client.get(reverse("creditor_detail", args=[c.pk]) + "?record=HACK")
        self.assertNotIn("transaction_type", r.context["form"].initial)

    def test_adding_a_new_person_from_the_picker_opens_their_form(self):
        r = self.client.post(reverse("debtor_create") + "?record=LEND", {"name": "Rafi", "category": "OTHER"})
        d = Debtor.objects.get(user=self.user, name="Rafi")
        self.assertRedirects(r, f"{reverse('debtor_detail', args=[d.pk])}?record=LEND#record", fetch_redirect_response=False)
        # Without the picker, adding still goes back to the list
        r = self.client.post(reverse("debtor_create"), {"name": "Sumi", "category": "OTHER"})
        self.assertRedirects(r, reverse("debtor_list"), fetch_redirect_response=False)

    def test_income_picker_and_new_source(self):
        IncomeSource.objects.create(user=self.user, name="Salary")
        r = self.client.get(reverse("pick", args=["income"]))
        self.assertContains(r, "Salary")
        r = self.client.post(reverse("income_source_create") + "?record=", {"name": "Rent"})
        src = IncomeSource.objects.get(user=self.user, name="Rent")
        self.assertRedirects(r, reverse("income_source_detail", args=[src.pk]) + "#record", fetch_redirect_response=False)


class HelpAndDatesTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="help_user", password="secret123")
        self.client.force_login(self.user)

    def test_help_page_explains_the_words(self):
        r = self.client.get(reverse("help"))
        self.assertContains(r, "Someone you borrowed money from. You owe them.")
        self.assertContains(r, "I made a mistake. How do I fix it?")

    def test_bangla_forms_give_the_date_picker_an_iso_date(self):
        # Django's Bangla default (07/10/2026) was read by the date picker as another date.
        self.client.post(reverse("update_preferences"), {"language": "bn"})
        r = self.client.get(reverse("expense_create"))
        self.assertContains(r, f'value="{timezone.localdate().isoformat()}"')
        # A hand-typed dd/mm/yyyy still works
        from django import forms
        from django.utils import translation
        with translation.override("bn"):
            self.assertEqual(forms.DateField().clean("07/10/2026"), date(2026, 10, 7))
            self.assertEqual(forms.DateField().clean("2026-10-07"), date(2026, 10, 7))
