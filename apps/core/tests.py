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


class CalculatorTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("owner", password="pw12345!")

    def test_available_on_every_signed_in_page(self):
        self.client.login(username="owner", password="pw12345!")
        for name in ["dashboard", "expense_dashboard", "household_dashboard", "shop_list"]:
            with self.subTest(name):
                response = self.client.get(reverse(name))
                self.assertContains(response, 'class="calc-trigger"')
                self.assertContains(response, 'x-data="calculator(window.FTCalcConfig)"')
                self.assertContains(response, f'user: "{self.user.pk}"')

    def test_not_rendered_for_anonymous_visitors(self):
        response = self.client.get(reverse("login"))
        self.assertNotContains(response, "calc-trigger")
        self.assertNotContains(response, "FTCalcConfig")

    def test_labels_follow_bangla(self):
        self.client.login(username="owner", password="pw12345!")
        self.client.post(reverse("update_preferences"), {"language": "bn"})
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "ব্যবসার টুল")
        self.assertContains(response, "ছাড় %")  # literal % in a translated label
        self.assertContains(response, "৳{value} বসানো হয়েছে: {field}")


class StatsHelperTests(TestCase):
    def test_month_start_crosses_years(self):
        from datetime import date
        from apps.core.stats import last_n_month_starts, month_start
        self.assertEqual(month_start(date(2026, 1, 15), -1), date(2025, 12, 1))
        months = last_n_month_starts(12, today=date(2026, 3, 10))
        self.assertEqual((months[0], months[-1], len(months)), (date(2025, 4, 1), date(2026, 3, 1), 12))

    def test_change_directions_and_multiplier(self):
        from apps.core.stats import change
        self.assertIsNone(change(0, 0))
        self.assertEqual(change(50, 0), {"pct": None, "direction": "up"})
        self.assertEqual(change(90, 100)["direction"], "down")
        self.assertEqual(change(100, 100)["direction"], "flat")
        self.assertEqual(change(4100, 100)["times"], Decimal("41"))
        self.assertIsNone(change(150, 100)["times"])

    def test_month_compare_uses_same_days_of_last_month(self):
        from datetime import date
        from apps.core.stats import month_compare
        user = User.objects.create_user("owner", password="pw12345!")
        cat = ExpenseCategory.objects.create(user=user, name="Food")
        for d, amt in [("2026-08-05", 100), ("2026-08-25", 900), ("2026-09-03", 200), ("2026-09-20", 999)]:
            Expense.objects.create(user=user, category=cat, amount=amt, date=d)
        m = month_compare(Expense.objects.filter(user=user), today=date(2026, 9, 10))
        self.assertEqual(m["this_month"], 200)          # the 20th is still in the future
        self.assertEqual(m["last_month"], 1000)         # the whole of August
        self.assertEqual(m["change"]["pct"], 100)       # 200 vs 100 by 10 Aug
        self.assertEqual(m["daily_avg"], 20)

    def test_ranked_folds_the_tail_into_other(self):
        from apps.core.stats import ranked
        rows = ranked([(f"c{i}", 10 * (i + 1), None) for i in range(8)] + [("zero", 0, None)])
        self.assertEqual(len(rows), 6)
        self.assertEqual(rows[0]["label"], "c7")
        self.assertEqual(rows[0]["bar"], 100)
        self.assertTrue(rows[-1]["label"].endswith("(3)"))
        self.assertEqual(rows[-1]["value"], 10 + 20 + 30)
        self.assertAlmostEqual(float(sum(r["pct"] for r in rows)), 100.0)

    def test_trend_summary_ignores_empty_months(self):
        from datetime import date
        from apps.core.stats import trend_summary
        months = [date(2026, m, 1) for m in range(1, 5)]
        s = trend_summary([0, 100.0, 0, 300.0], months)
        self.assertEqual((s["average"], s["peak_value"], s["peak_month"], s["total"]), (200, 300, months[3], 400))
        self.assertIsNone(trend_summary([0, 0], months[:2]))


class DashboardTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("owner", password="pw12345!")
        self.client.login(username="owner", password="pw12345!")

    def test_every_statistics_page_renders_empty_and_with_data(self):
        names = ["networth", "dashboard", "debtor_dashboard", "shop_dashboard", "income_dashboard",
                 "expense_dashboard", "household_dashboard", "contributor_dashboard"]
        for name in names:
            with self.subTest(name, data=False):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)
        c = Creditor.objects.create(user=self.user, name="Bank")
        c.transactions.create(transaction_type="BORROW", amount=1000, date="2026-01-01")
        c.transactions.create(transaction_type="REPAY", amount=250, date="2026-02-01")
        Expense.objects.create(user=self.user, amount=40, date="2026-02-01")
        for name in names:
            with self.subTest(name, data=True):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)

    def test_creditor_dashboard_progress_and_ranked_balances(self):
        a = Creditor.objects.create(user=self.user, name="Bank")
        a.transactions.create(transaction_type="BORROW", amount=1000, date="2026-01-01")
        a.transactions.create(transaction_type="REPAY", amount=250, date="2026-02-01")
        Creditor.objects.create(user=self.user, name="Paid off").transactions.create(transaction_type="BORROW", amount=0.01, date="2026-01-01")
        ctx = self.client.get(reverse("dashboard")).context
        self.assertEqual(ctx["progress_pct"], 24)  # 250 of 1000.01
        self.assertEqual([r["label"] for r in ctx["rank_remaining"]], ["Bank", "Paid off"])
        self.assertEqual(ctx["open_count"], 2)
        self.assertContains(self.client.get(reverse("dashboard")), 'data-i="0"')

    def test_attention_badge_counts_overdue_and_due_soon(self):
        from datetime import timedelta
        from django.utils import timezone
        today = timezone.localdate()
        for name, due in [("Late", today - timedelta(days=3)), ("Soon", today + timedelta(days=2))]:
            c = Creditor.objects.create(user=self.user, name=name, due_date=due)
            c.transactions.create(transaction_type="BORROW", amount=100, date=today)
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, '<span class="badge" data-tone="critical">2</span>', html=False)

    def test_networth_attention_spans_ledgers_and_sorts_by_due_date(self):
        from datetime import timedelta
        from django.utils import timezone
        today = timezone.localdate()
        d = Debtor.objects.create(user=self.user, name="Owes me", due_date=today - timedelta(days=1))
        d.transactions.create(transaction_type="LEND", amount=500, date=today)
        s = Shop.objects.create(user=self.user, name="Store", due_date=today - timedelta(days=4))
        s.transactions.create(transaction_type="PURCHASE", amount=80, date=today)
        settled = Creditor.objects.create(user=self.user, name="Settled", due_date=today)
        settled.transactions.create(transaction_type="BORROW", amount=10, date=today)
        settled.transactions.create(transaction_type="REPAY", amount=10, date=today)
        items = self.client.get(reverse("networth")).context["attention"]
        self.assertEqual([(i["name"], i["kind"], i["late"]) for i in items], [("Store", "pay", 4), ("Owes me", "collect", 1)])

    def test_expense_dashboard_links_categories_to_the_filtered_list(self):
        cat = ExpenseCategory.objects.create(user=self.user, name="Rent")
        Expense.objects.create(user=self.user, category=cat, amount=500, date="2026-01-01")
        Expense.objects.create(user=self.user, amount=50, date="2026-01-02")
        rows = self.client.get(reverse("expense_dashboard")).context["category_rank"]
        self.assertEqual(rows[0]["url"], f"{reverse('expense_list')}?category={cat.pk}")
        self.assertIsNone(rows[1]["url"])  # "General" has no category to filter by
