from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from apps.contributors.models import Contributor
from apps.core.templatetags.ui import money, signed_money
from apps.creditors.models import Creditor
from apps.debtors.models import Debtor
from apps.expense.forms import ExpenseForm
from apps.expense.models import Expense, ExpenseCategory
from apps.household.forms import PurchaseForm
from apps.household.models import HouseholdCategory, HouseholdMember
from apps.income.forms import RecurringIncomeForm
from apps.income.models import IncomeSource
from apps.shops.models import Shop


class MoneyFilterTests(TestCase):
    def test_groups_thousands_and_keeps_cents(self):
        self.assertEqual(money(Decimal("1234567.5")), "৳1,234,567.50")

    def test_drops_zero_cents(self):
        self.assertEqual(money(Decimal("12450000.00")), "৳12,450,000")

    def test_negative_uses_minus_sign(self):
        self.assertEqual(money(Decimal("-500")), "−৳500")

    def test_signed_money_adds_plus(self):
        self.assertEqual(signed_money(Decimal("10")), "+৳10")
        self.assertEqual(signed_money(0), "৳0")

    def test_non_numeric_passes_through(self):
        self.assertEqual(money("n/a"), "n/a")


class ActiveStatusTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("owner", password="pw12345!")
        self.other = User.objects.create_user("other", password="pw12345!")
        self.client.login(username="owner", password="pw12345!")

    def test_new_records_are_active_by_default(self):
        creditor = Creditor.objects.create(user=self.user, name="Rahim")
        self.assertTrue(creditor.is_active)

    def test_toggle_marks_inactive_then_active_again(self):
        creditor = Creditor.objects.create(user=self.user, name="Rahim")
        url = reverse("creditor_toggle_active", args=[creditor.pk])

        self.client.post(url)
        creditor.refresh_from_db()
        self.assertFalse(creditor.is_active)

        self.client.post(url)
        creditor.refresh_from_db()
        self.assertTrue(creditor.is_active)

    def test_toggle_requires_post(self):
        creditor = Creditor.objects.create(user=self.user, name="Rahim")
        response = self.client.get(reverse("creditor_toggle_active", args=[creditor.pk]))
        self.assertEqual(response.status_code, 405)
        creditor.refresh_from_db()
        self.assertTrue(creditor.is_active)

    def test_cannot_toggle_another_users_record(self):
        foreign = Debtor.objects.create(user=self.other, name="Not yours")
        response = self.client.post(reverse("debtor_toggle_active", args=[foreign.pk]))
        self.assertEqual(response.status_code, 404)
        foreign.refresh_from_db()
        self.assertTrue(foreign.is_active)

    def test_toggle_redirects_to_safe_next_only(self):
        shop = Shop.objects.create(user=self.user, name="Store")
        url = reverse("shop_toggle_active", args=[shop.pk])

        response = self.client.post(url, {"next": "/shops/list/?status=all"})
        self.assertRedirects(response, "/shops/list/?status=all", fetch_redirect_response=False)

        response = self.client.post(url, {"next": "https://evil.example.com/"})
        self.assertRedirects(response, reverse("shop_list"), fetch_redirect_response=False)

    def test_every_toggle_endpoint_flips_the_flag(self):
        records = [
            ("creditor_toggle_active", Creditor.objects.create(user=self.user, name="C")),
            ("debtor_toggle_active", Debtor.objects.create(user=self.user, name="D")),
            ("shop_toggle_active", Shop.objects.create(user=self.user, name="S")),
            ("contributor_toggle_active", Contributor.objects.create(user=self.user, name="K")),
            ("income_source_toggle_active", IncomeSource.objects.create(user=self.user, name="I")),
            ("category_toggle_active", ExpenseCategory.objects.create(user=self.user, name="E")),
            ("household_member_toggle_active", HouseholdMember.objects.create(user=self.user, name="M")),
            ("household_category_toggle_active", HouseholdCategory.objects.create(user=self.user, name="H")),
        ]
        for url_name, obj in records:
            with self.subTest(url_name):
                self.client.post(reverse(url_name, args=[obj.pk]))
                obj.refresh_from_db()
                self.assertFalse(obj.is_active)

    def test_list_defaults_to_active_and_counts_each_status(self):
        Creditor.objects.create(user=self.user, name="Active One")
        Creditor.objects.create(user=self.user, name="Archived One", is_active=False)

        response = self.client.get(reverse("creditor_list"))
        names = [c.name for c in response.context["page_obj"]]
        self.assertEqual(names, ["Active One"])
        self.assertEqual(response.context["status_counts"], {"active": 1, "inactive": 1, "all": 2})

        response = self.client.get(reverse("creditor_list"), {"status": "inactive"})
        self.assertEqual([c.name for c in response.context["page_obj"]], ["Archived One"])

        response = self.client.get(reverse("creditor_list"), {"status": "all"})
        self.assertEqual(len(response.context["page_obj"]), 2)

    def test_unknown_status_falls_back_to_active(self):
        Contributor.objects.create(user=self.user, name="Archived", is_active=False)
        response = self.client.get(reverse("contributor_list"), {"status": "bogus"})
        self.assertEqual(response.context["status"], "active")
        self.assertEqual(len(response.context["page_obj"]), 0)

    def test_expense_category_list_filters_by_status(self):
        ExpenseCategory.objects.create(user=self.user, name="Rent")
        ExpenseCategory.objects.create(user=self.user, name="Old", is_active=False)
        response = self.client.get(reverse("category_list"))
        self.assertEqual([c.name for c in response.context["categories"]], ["Rent"])


class PickerTests(TestCase):
    """Inactive records disappear from form dropdowns, except the one an
    existing entry already points at."""

    def setUp(self):
        self.user = User.objects.create_user("owner", password="pw12345!")

    def test_expense_form_hides_inactive_categories(self):
        ExpenseCategory.objects.create(user=self.user, name="Rent")
        ExpenseCategory.objects.create(user=self.user, name="Old", is_active=False)
        form = ExpenseForm(user=self.user)
        self.assertEqual([c.name for c in form.fields["category"].queryset], ["Rent"])

    def test_editing_keeps_current_inactive_category(self):
        old = ExpenseCategory.objects.create(user=self.user, name="Old", is_active=False)
        expense = Expense.objects.create(user=self.user, category=old, amount=10, date="2026-01-01")
        form = ExpenseForm(instance=expense, user=self.user)
        self.assertIn(old, form.fields["category"].queryset)

    def test_recurring_income_form_hides_inactive_sources(self):
        IncomeSource.objects.create(user=self.user, name="Salary")
        IncomeSource.objects.create(user=self.user, name="Old job", is_active=False)
        form = RecurringIncomeForm(user=self.user)
        self.assertEqual([s.name for s in form.fields["source"].queryset], ["Salary"])

    def test_purchase_form_hides_inactive_members_and_categories(self):
        HouseholdMember.objects.create(user=self.user, name="Here")
        HouseholdMember.objects.create(user=self.user, name="Moved out", is_active=False)
        HouseholdCategory.objects.create(user=self.user, name="Fish", is_active=False)
        form = PurchaseForm(user=self.user)
        self.assertEqual([m.name for m in form.fields["buyer"].queryset], ["Here"])
        self.assertEqual(list(form.fields["category"].queryset), [])


class InactiveRecordsStillCountTests(TestCase):
    def test_inactive_creditor_still_counts_on_dashboard(self):
        user = User.objects.create_user("owner", password="pw12345!")
        self.client.login(username="owner", password="pw12345!")
        creditor = Creditor.objects.create(user=user, name="Archived", is_active=False)
        creditor.transactions.create(transaction_type="BORROW", amount=500, date="2026-01-01")
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.context["remaining"], 500)


class QuickCreateTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("owner", password="pw12345!")
        self.other = User.objects.create_user("other", password="pw12345!")
        self.client.login(username="owner", password="pw12345!")

    def post(self, kind, **data):
        payload = {f"qa_{kind}-{k}": v for k, v in data.items()}
        return self.client.post(reverse("quick_create", args=[kind]), payload)

    def test_creates_and_returns_json(self):
        response = self.post("expense_category", name="  Fuel ")
        self.assertEqual(response.status_code, 201)
        data = response.json()
        category = ExpenseCategory.objects.get(user=self.user, name="Fuel")
        self.assertEqual((data["ok"], data["id"], data["name"]), (True, category.pk, "Fuel"))

    def test_every_kind_creates_for_the_current_user(self):
        for kind, model in [
            ("expense_category", ExpenseCategory),
            ("income_source", IncomeSource),
            ("household_category", HouseholdCategory),
            ("household_member", HouseholdMember),
        ]:
            with self.subTest(kind):
                self.assertEqual(self.post(kind, name="New thing").status_code, 201)
                self.assertTrue(model.objects.filter(user=self.user, name="New thing").exists())

    def test_existing_active_name_is_reused_not_duplicated(self):
        existing = ExpenseCategory.objects.create(user=self.user, name="Rent")
        response = self.post("expense_category", name="rent")
        self.assertEqual(response.json()["id"], existing.pk)
        self.assertEqual(ExpenseCategory.objects.filter(user=self.user).count(), 1)

    def test_existing_inactive_name_offers_reactivation(self):
        old = HouseholdMember.objects.create(user=self.user, name="Salma", is_active=False)
        response = self.post("household_member", name="Salma")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["reactivate"]["id"], old.pk)

        response = self.client.post(reverse("quick_create", args=["household_member"]), {"reactivate": old.pk})
        self.assertTrue(response.json()["ok"])
        old.refresh_from_db()
        self.assertTrue(old.is_active)

    def test_validation_errors_come_back_per_field(self):
        response = self.post("income_source", name="")
        self.assertEqual(response.status_code, 400)
        self.assertIn("name", response.json()["errors"])

    def test_same_name_for_another_user_does_not_leak(self):
        ExpenseCategory.objects.create(user=self.other, name="Fuel")
        response = self.post("expense_category", name="Fuel")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(ExpenseCategory.objects.get(pk=response.json()["id"]).user, self.user)

    def test_cannot_reactivate_another_users_record(self):
        foreign = ExpenseCategory.objects.create(user=self.other, name="X", is_active=False)
        response = self.client.post(reverse("quick_create", args=["expense_category"]), {"reactivate": foreign.pk})
        self.assertEqual(response.status_code, 404)

    def test_unknown_kind_and_get_are_rejected(self):
        self.assertEqual(self.client.post(reverse("quick_create", args=["nope"])).status_code, 404)
        self.assertEqual(self.client.get(reverse("quick_create", args=["expense_category"])).status_code, 405)

    def test_expense_form_renders_the_add_button_and_popup(self):
        response = self.client.get(reverse("expense_create"))
        self.assertContains(response, 'class="input-addon-btn"')
        self.assertContains(response, 'name="qa_expense_category-name"')
