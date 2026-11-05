"""Categories with an icon and a colour that can be renamed and merged (Money Lover), and a ledger
by day that can be searched, filtered by wallet, copied from and filled from a CSV (Wallet, Monarch)."""
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.budgets.models import Budget
from apps.expense.importing import parse_amount, parse_date
from apps.expense.models import Expense, ExpenseCategory, RecurringExpense
from apps.wallets.models import Wallet


class CategoryTests(TestCase):
    def setUp(self):
        self.me = User.objects.create_user("me", password="pw12345!")
        self.client.force_login(self.me)
        self.food = ExpenseCategory.objects.create(user=self.me, name="Food")

    def test_add_and_edit_with_an_icon_and_colour(self):
        r = self.client.post(reverse("category_create"), {"name": "  Rent  ", "icon": "🏠", "color": "teal"})
        self.assertEqual(r.status_code, 302)
        rent = ExpenseCategory.objects.get(name="Rent")
        self.assertEqual((rent.icon, rent.color, rent.label, rent.badge), ("🏠", "teal", "🏠 Rent", "🏠"))
        self.client.post(reverse("category_edit", args=[rent.pk]), {"name": "House rent", "icon": "", "color": ""})
        rent.refresh_from_db()
        self.assertEqual((rent.name, rent.badge), ("House rent", "H"))
        r = self.client.post(reverse("category_edit", args=[rent.pk]), {"name": "food", "icon": "", "color": ""})
        self.assertEqual(r.status_code, 200)                                     # the name is taken
        html = self.client.get(reverse("category_list")).content.decode()
        self.assertIn(reverse("category_edit", args=[rent.pk]), html)

    def test_the_pickers_show_the_icon(self):
        self.food.icon = "🍚"
        self.food.save()
        self.assertIn("🍚 Food", self.client.get(reverse("expense_create")).content.decode())
        self.assertIn("🍚 Food", self.client.get(reverse("budget_create")).content.decode())

    def test_merge_moves_everything_and_removes_the_category(self):
        snacks = ExpenseCategory.objects.create(user=self.me, name="Snacks")
        Expense.objects.create(user=self.me, category=snacks, amount=50, date=date(2026, 9, 1))
        Expense.objects.create(user=self.me, category=snacks, amount=70, date=date(2026, 9, 2))
        RecurringExpense.objects.create(user=self.me, category=snacks, amount=10, frequency="MONTHLY",
                                        next_run_date=date(2026, 10, 1), start_date=date(2026, 9, 1))
        Budget.objects.create(user=self.me, category=snacks, amount=500)
        r = self.client.post(reverse("category_merge", args=[snacks.pk]), {"into": self.food.pk})
        self.assertEqual(r.status_code, 302)
        self.assertFalse(ExpenseCategory.objects.filter(pk=snacks.pk).exists())
        self.assertEqual(Expense.objects.filter(category=self.food).count(), 2)
        self.assertEqual(RecurringExpense.objects.get().category, self.food)
        self.assertEqual(Budget.objects.get().category, self.food)               # Food had none: it takes this one

    def test_merge_into_general_and_into_a_category_with_a_budget(self):
        Budget.objects.create(user=self.me, category=self.food, amount=900)
        snacks = ExpenseCategory.objects.create(user=self.me, name="Snacks")
        Budget.objects.create(user=self.me, category=snacks, amount=500)
        self.client.post(reverse("category_merge", args=[snacks.pk]), {"into": self.food.pk})
        self.assertEqual(list(Budget.objects.values_list("amount", flat=True)), [Decimal("900")])
        Expense.objects.create(user=self.me, category=self.food, amount=5, date=date(2026, 9, 1))
        self.client.post(reverse("category_merge", args=[self.food.pk]), {"into": ""})
        self.assertIsNone(Expense.objects.get().category)
        self.assertFalse(Budget.objects.exists())

    def test_someone_elses_category_is_out_of_reach(self):
        other = User.objects.create_user("other", password="pw12345!")
        theirs = ExpenseCategory.objects.create(user=other, name="Theirs")
        self.assertEqual(self.client.get(reverse("category_edit", args=[theirs.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("category_merge", args=[self.food.pk]), {"into": theirs.pk}).status_code, 404)
        self.assertEqual(self.client.post(reverse("category_merge", args=[theirs.pk]), {"into": ""}).status_code, 404)


class LedgerTests(TestCase):
    def setUp(self):
        self.me = User.objects.create_user("me", password="pw12345!")
        self.client.force_login(self.me)
        self.food = ExpenseCategory.objects.create(user=self.me, name="Food", icon="🍚", color="green")
        self.bkash = Wallet.objects.create(user=self.me, name="bKash", kind="mobile")
        self.today = timezone.localdate()

    def add(self, amount, days_ago=0, **fields):
        return Expense.objects.create(user=self.me, category=fields.pop("category", self.food), amount=amount,
                                      date=self.today - timedelta(days=days_ago), **fields)

    def test_by_day_with_each_days_total(self):
        self.add(100, note="rice")
        self.add(50, note="eggs")
        self.add(30, days_ago=1)
        r = self.client.get(reverse("expense_list"))
        self.assertEqual([(d["date"], d["total"], len(d["rows"])) for d in r.context["days"]],
                         [(self.today, Decimal("150"), 2), (self.today - timedelta(days=1), Decimal("30"), 1)])
        self.assertIn("Today", r.content.decode())
        self.assertEqual(self.client.get(reverse("expense_list"), {"sort": "-amount"}).context["days"], [])

    def test_search_and_wallet(self):
        self.add(100, note="Fresh hilsa", wallet=self.bkash)
        self.add(45, note="bus fare")
        found = lambda **q: sorted(e.note for e in self.client.get(reverse("expense_list"), q).context["page_obj"])
        self.assertEqual(found(q="HILSA"), ["Fresh hilsa"])
        self.assertEqual(found(q="food"), ["Fresh hilsa", "bus fare"])         # the category's name
        self.assertEqual(found(q="৳45"), ["bus fare"])                          # an amount
        self.assertEqual(found(wallet=self.bkash.pk), ["Fresh hilsa"])
        self.assertEqual(found(wallet="none"), ["bus fare"])
        self.assertEqual(len(found(wallet="99999")), 2)                         # not theirs: ignored
        csv = self.client.get(reverse("expense_list"), {"export": "csv", "wallet": self.bkash.pk}).content.decode()
        self.assertIn("bKash", csv)
        self.assertNotIn("bus fare", csv)

    def test_copy_starts_a_new_one_filled_in(self):
        ex = self.add(250, days_ago=5, note="Gas cylinder", wallet=self.bkash)
        r = self.client.get(reverse("expense_copy", args=[ex.pk]))
        form = r.context["form"]
        self.assertEqual((form["amount"].value(), form["note"].value(), form["date"].value()), (Decimal("250"), "Gas cylinder", self.today))
        self.client.post(reverse("expense_copy", args=[ex.pk]), {"category": self.food.pk, "amount": "260", "date": self.today.isoformat(), "note": "Gas cylinder"})
        self.assertEqual(Expense.objects.count(), 2)
        other = User.objects.create_user("other", password="pw12345!")
        theirs = Expense.objects.create(user=other, amount=1, date=self.today)
        self.assertEqual(self.client.get(reverse("expense_copy", args=[theirs.pk])).status_code, 404)


class ImportTests(TestCase):
    def setUp(self):
        self.me = User.objects.create_user("me", password="pw12345!")
        self.client.force_login(self.me)
        Wallet.objects.create(user=self.me, name="bKash", kind="mobile")

    def upload(self, text):
        f = SimpleUploadedFile("statement.csv", text.encode("utf-8-sig"), content_type="text/csv")
        return self.client.post(reverse("expense_import"), {"csv_file": f}, follow=True)

    def test_parsing(self):
        self.assertEqual(parse_date("05/11/2026"), date(2026, 11, 5))
        self.assertEqual(parse_date("2026-11-05 10:30:00"), date(2026, 11, 5))
        self.assertEqual(parse_date("5 Nov 2026"), date(2026, 11, 5))
        self.assertEqual(parse_date("০৫-১১-২০২৬"), date(2026, 11, 5))
        self.assertIsNone(parse_date("soon"))
        self.assertEqual(parse_amount("৳1,250.5"), Decimal("1250.50"))
        self.assertEqual(parse_amount("-300"), Decimal("300"))
        self.assertEqual(parse_amount("(1,000)"), Decimal("1000.00"))
        self.assertEqual(parse_amount("১২০"), Decimal("120.00"))
        self.assertIsNone(parse_amount("0"))
        self.assertIsNone(parse_amount("abc"))

    def test_a_spreadsheet(self):
        r = self.upload("Date,Amount,Category,Wallet,Note\n2026-11-01,350,Groceries,bKash,Rice\n"
                        "2026-11-02,120,transport,Cash box,Rickshaw\nsomeday,5,,,\n2026-11-03,,Food,,\n")
        rows = list(Expense.objects.order_by("date").values_list("amount", "category__name", "wallet__name", "note"))
        self.assertEqual(rows, [(Decimal("350.00"), "Groceries", "bKash", "Rice"), (Decimal("120.00"), "transport", None, "Rickshaw")])
        text = r.content.decode()
        self.assertIn("Imported 2 expenses", text)
        self.assertIn("without a date", text)
        self.assertIn("wallet you don", text)
        self.upload("Date,Amount,Category,Wallet,Note\n2026-11-01,350,groceries,bKash,Rice\n")
        self.assertEqual(Expense.objects.count(), 2)                              # brought in twice: once
        self.assertEqual(ExpenseCategory.objects.filter(user=self.me).count(), 2)

    def test_a_bank_statement(self):
        self.upload("Txn Date,Particulars,Debit,Credit,Balance\n05/11/2026,ATM withdrawal,\"2,000.00\",,8000\n"
                    "06/11/2026,Salary,,50000,58000\n")
        e = Expense.objects.get()
        self.assertEqual((e.date, e.amount, e.note, e.category), (date(2026, 11, 5), Decimal("2000.00"), "ATM withdrawal", None))

    def test_without_the_columns(self):
        r = self.upload("Name,Price\nx,1\n")
        self.assertIn("needs a Date and an Amount", r.content.decode())
        self.assertFalse(Expense.objects.exists())
        self.assertIn("Date,Amount,Category", self.client.get(reverse("expense_import_template")).content.decode())
