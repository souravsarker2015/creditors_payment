"""Family income (money from outside the farm), loans received into an account,
and fingerlings paid from an account."""
from datetime import date, timedelta
from decimal import Decimal as D

from django.test import TestCase
from django.urls import reverse

from apps.business.core.testing import make_farm
from apps.business.loans.models import Lender, LenderKind, Loan
from apps.business.ponds.models import CultureCycle, Pond, Stocking
from apps.business.species.models import Species

from . import services
from .models import Account, Category, CategoryType, FamilyMember, Scope, Transaction


def ago(n):
    return date.today() - timedelta(days=n)


class Base(TestCase):
    def setUp(self):
        self.b, self.owner, self.staff = make_farm()
        self.client.force_login(self.owner)
        self.cash = Account.objects.get(business=self.b, name="Cash")
        self.abroad = Category.objects.get(business=self.b, name="Money from abroad")


class FamilyIncomeTests(Base):
    def test_a_new_farm_has_family_income_sources(self):
        names = set(Category.objects.filter(business=self.b, type=CategoryType.INCOME, scope=Scope.HOUSEHOLD).values_list("name", flat=True))
        self.assertTrue({"Job / salary", "Money from abroad", "Crops & farming", "Rent received"} <= names)

    def test_saving_family_income(self):
        son = FamilyMember.objects.create(business=self.b, name="Rahim", relation="Son")
        page = self.client.get(reverse("business:family_income_add"))
        self.assertContains(page, "Add family income")
        # Only household income sources are offered, with the family member picker.
        offered = {c.name for c in page.context["form"].fields["category"].queryset}
        self.assertIn("Money from abroad", offered)
        self.assertFalse(offered & {"Groceries (bazar)", "Fish sales", "Other income"})
        self.assertContains(page, 'name="member"')
        r = self.client.post(reverse("business:family_income_add"), {
            "category": self.abroad.pk, "amount": "25000", "member": son.pk, "date": ago(1).isoformat(), "account": self.cash.pk})
        self.assertRedirects(r, reverse("business:family_income"))
        t = Transaction.objects.get(business=self.b)
        self.assertEqual((t.amount, t.member, t.category.scope), (D("25000"), son, Scope.HOUSEHOLD))
        # The money is in the cash box, but the farm's profit doesn't change.
        self.assertEqual(self.cash.balance, D("25000"))
        self.assertEqual(services.statement(self.b, ago(30), date.today()).profit, 0)
        # The next one starts with the same source and person.
        self.assertContains(self.client.get(reverse("business:family_income_add")), f'<option value="{son.pk}" selected>')

    def test_a_farm_category_cant_be_sent_as_family_income(self):
        fish = Category.objects.get(business=self.b, name="Other income", scope=Scope.BUSINESS)
        r = self.client.post(reverse("business:family_income_add"), {"category": fish.pk, "amount": "100", "date": ago(0).isoformat()})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Transaction.objects.exists())

    def test_the_family_page_adds_it_up(self):
        son = FamilyMember.objects.create(business=self.b, name="Rahim", relation="Son")
        salary = Category.objects.get(business=self.b, name="Job / salary")
        bazar = Category.objects.get(business=self.b, name="Groceries (bazar)")
        Transaction.objects.create(business=self.b, date=ago(0), category=self.abroad, amount=D("30000"), member=son, account=self.cash)
        Transaction.objects.create(business=self.b, date=ago(0), category=salary, amount=D("12000"), account=self.cash)
        Transaction.objects.create(business=self.b, date=ago(0), category=bazar, amount=D("8000"), account=self.cash)
        r = self.client.get(reverse("business:family_income") + "?period=all")
        self.assertEqual(r.context["total"], D("42000"))
        self.assertEqual(r.context["home"], D("8000"))
        self.assertEqual(r.context["left"], r.context["farm"] + D("42000") - D("8000"))
        self.assertEqual([row["label"] for row in r.context["sources"]], ["Money from abroad", "Job / salary"])
        self.assertEqual([row["label"] for row in r.context["people"]], ["Rahim", "Not one person"])
        self.assertContains(r, "Left over")
        # Household income shows on the household statement, not the farm's.
        self.assertEqual(services.statement(self.b, ago(1), date.today(), scope=Scope.HOUSEHOLD).total_income, D("42000"))

    def test_family_money_is_private_from_farm_staff(self):
        self.client.force_login(self.staff)
        for url in (reverse("business:family_income"), reverse("business:family_income_add"), reverse("business:family_members")):
            self.assertEqual(self.client.get(url).status_code, 403, url)
        r = self.client.post(reverse("business:quick_add", args=["family_member"]), {"qa_family_member-name": "Karim"})
        self.assertEqual(r.status_code, 403)

    def test_family_members_and_quick_add(self):
        r = self.client.post(reverse("business:quick_add", args=["family_member"]),
                             {"qa_family_member-name": "Karim", "qa_family_member-relation": "Brother"})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(str(FamilyMember.objects.get(business=self.b)), "Karim (Brother)")
        self.assertContains(self.client.get(reverse("business:family_members")), "Karim")
        # Household money anywhere can name the person; farm money can't.
        self.assertContains(self.client.get(reverse("business:transaction_add") + "?scope=household"), 'name="member"')
        self.assertNotContains(self.client.get(reverse("business:transaction_add")), 'name="member"')

    def test_menu_and_search(self):
        self.assertContains(self.client.get(reverse("business:home")), reverse("business:family_income"))


class LoanAccountTests(Base):
    def test_borrowed_money_goes_into_the_account(self):
        bank = Lender.objects.create(business=self.b, name="Sonali Bank", kind=LenderKind.BANK)
        r = self.client.get(reverse("business:loan_add"))
        self.assertContains(r, 'id="lender-kinds"')
        self.assertEqual(r.context["form"].initial["account"], self.cash)
        r = self.client.post(reverse("business:loan_add"), {
            "lender": bank.pk, "principal": "200000", "taken_on": ago(0).isoformat(), "account": self.cash.pk,
            "rate": "0", "rate_period": "year", "method": "reducing", "every": "1", "every_unit": "month", "repayment": "end"})
        loan = Loan.objects.get(business=self.b)
        self.assertRedirects(r, reverse("business:loan_detail", args=[loan.pk]))
        self.assertEqual(self.cash.balance, D("200000"))
        self.assertContains(self.client.get(reverse("business:loan_detail", args=[loan.pk])), "Received into")
        # Borrowed money isn't income.
        self.assertEqual(services.statement(self.b, ago(30), date.today()).total_income, 0)

    def test_a_loan_already_in_the_starting_balance_isnt_counted_twice(self):
        # An old loan entered at setup: the money is inside the balance Cash started with.
        bank = Lender.objects.create(business=self.b, name="Sonali Bank")
        self.cash.opening_date = ago(5)
        self.cash.save()
        r = self.client.post(reverse("business:loan_add"), {
            "lender": bank.pk, "principal": "50000", "taken_on": ago(400).isoformat(), "account": self.cash.pk,
            "rate": "0", "rate_period": "year", "method": "reducing", "every": "1", "every_unit": "month", "repayment": "end"}, follow=True)
        self.assertIsNone(Loan.objects.get().account)
        self.assertEqual(self.cash.balance, 0)
        self.assertContains(r, "wasn&#x27;t added again")

    def test_an_old_loan_without_an_account_changes_no_balance(self):
        bank = Lender.objects.create(business=self.b, name="Sonali Bank")
        Loan.objects.create(business=self.b, lender=bank, principal=D("90000"), taken_on=ago(100))
        self.assertEqual(self.cash.balance, 0)

    def test_a_relative_can_lend(self):
        r = self.client.post(reverse("business:lender_quick_add"), {"qa_lender-name": "Uncle Jalal", "qa_lender-kind": "family"})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()["kind"], "family")
        self.assertEqual(Lender.objects.get(name="Uncle Jalal").get_kind_display(), "Relative / family")
        self.assertContains(self.client.get(reverse("business:loan_add")), '"family"')


class StockingPaymentTests(Base):
    def setUp(self):
        super().setUp()
        pond = Pond.objects.create(business=self.b, name="East")
        self.cycle = CultureCycle.objects.create(business=self.b, pond=pond, start_date=ago(30))
        self.rui = Species.objects.filter(business=self.b).first()
        self.url = reverse("business:entry_add", args=[self.cycle.pk, "stocking"])

    def post(self, **extra):
        data = {"date": ago(1).isoformat(), "species": self.rui.pk, "count": "1000", "cost": "8000", "paid_now": "8000",
                "account": self.cash.pk}
        data.update(extra)
        return self.client.post(self.url, {f"stocking-{k}": v for k, v in data.items()})

    def test_fingerlings_paid_now_leave_the_account(self):
        self.assertEqual(self.client.get(self.url).context["form"].initial["account"], self.cash)
        self.post()
        self.assertEqual(Stocking.objects.get().account, self.cash)
        self.assertEqual(self.cash.balance, D("-8000"))

    def test_nothing_paid_means_no_money_leaves(self):
        from apps.business.parties.models import Party

        hatchery = Party.objects.create(business=self.b, name="Hatchery", is_supplier=True)
        self.post(supplier=hatchery.pk, paid_now="0")
        self.assertIsNone(Stocking.objects.get().account)
        self.assertEqual(self.cash.balance, 0)

    def test_own_fingerlings_without_an_account(self):
        self.post(account="")
        self.assertEqual(self.cash.balance, 0)
