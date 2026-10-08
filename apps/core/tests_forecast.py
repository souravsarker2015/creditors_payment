"""Upcoming money: the forecast engine, the personal page and the farm page."""
from datetime import date, timedelta
from decimal import Decimal as D

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.core.forecast import Item, build


class EngineTests(TestCase):
    def test_balance_day_by_day_and_the_first_short_day(self):
        t = date(2026, 10, 8)
        f = build(D("1000"), [
            Item(t + timedelta(days=2), D("-1500"), "Rent"),
            Item(t + timedelta(days=5), D("2000"), "Salary"),
            Item(t - timedelta(days=3), D("-200"), "Shop"),          # late: counted today
            Item(t + timedelta(days=40), D("-9999"), "Far away"),    # after the window
        ], today=t, days=30)
        self.assertEqual([d.date for d in f.days], [t, t + timedelta(days=2), t + timedelta(days=5)])
        self.assertEqual([d.balance for d in f.days], [D("800"), D("-700"), D("1300")])
        self.assertTrue(f.days[0].items[0].late)
        self.assertEqual((f.coming_in, f.going_out, f.end_balance), (D("2000"), D("1700"), D("1300")))
        day, short = f.short
        self.assertEqual((day.date, short), (t + timedelta(days=2), D("700")))
        self.assertEqual(f.lowest, D("-700"))

    def test_nothing_coming(self):
        f = build(D("50"), [], today=date(2026, 1, 1))
        self.assertEqual((f.days, f.short, f.end_balance), ([], None, D("50")))


class PersonalUpcomingTests(TestCase):
    def setUp(self):
        from apps.wallets.models import Wallet

        self.user = User.objects.create_user("fc_user", password="x")
        self.client.force_login(self.user)
        self.today = timezone.localdate()
        self.cash = Wallet.objects.create(user=self.user, name="Cash", opening_balance=D("10000"), opening_date=self.today - timedelta(days=30))

    def test_dues_plans_and_regular_money(self):
        from apps.creditors.models import Creditor, Transaction as CT
        from apps.debtors.models import Debtor, Transaction as DT
        from apps.income.models import IncomeSource, RecurringIncome
        from apps.plans.models import InstallmentPlan

        t = self.today
        rahim = Creditor.objects.create(user=self.user, name="Rahim", due_date=t + timedelta(days=3))
        CT.objects.create(creditor=rahim, transaction_type="BORROW", amount=D("15000"), date=t - timedelta(days=60))
        karim = Debtor.objects.create(user=self.user, name="Karim")
        DT.objects.create(debtor=karim, transaction_type="LEND", amount=D("6000"), date=t - timedelta(days=60))
        InstallmentPlan.objects.create(user=self.user, debtor=karim, amount=D("2000"), frequency="weekly", start_date=t + timedelta(days=1))
        nodate = Debtor.objects.create(user=self.user, name="No date")
        DT.objects.create(debtor=nodate, transaction_type="LEND", amount=D("700"), date=t - timedelta(days=9))
        src = IncomeSource.objects.create(user=self.user, name="Job")
        RecurringIncome.objects.create(source=src, amount=D("30000"), frequency="MONTHLY", next_run_date=t + timedelta(days=10), start_date=t + timedelta(days=10))

        r = self.client.get(reverse("upcoming"))
        f = r.context["f"]
        titles = [(i.title, i.amount) for i in f.items]
        self.assertIn(("Rahim", D("-15000")), titles)
        self.assertEqual([a for n, a in titles if n == "Karim"], [D("2000")] * 3)   # three weekly installments, ৳6,000 in all
        self.assertIn(("Job", D("30000")), titles)
        self.assertEqual(f.now, D("10000"))
        # Rahim (৳15,000) comes before Karim has paid enough: short on that day.
        self.assertEqual(f.short[0].date, t + timedelta(days=3))
        self.assertContains(r, "Money may run short")
        self.assertEqual(f.undated["count"], 1)
        self.assertContains(r, "1 balance has no date")
        # Home shows it in one line.
        self.assertContains(self.client.get(reverse("home")), "Money may run short on")

    def test_regular_income_due_today_is_written_down_not_counted_late(self):
        from apps.income.models import IncomeSource, IncomeTransaction, RecurringIncome

        src = IncomeSource.objects.create(user=self.user, name="Job")
        RecurringIncome.objects.create(source=src, amount=D("500"), frequency="MONTHLY", next_run_date=self.today, start_date=self.today, wallet=self.cash)
        f = self.client.get(reverse("upcoming") + "?days=7").context["f"]
        self.assertTrue(IncomeTransaction.objects.filter(source=src, date=self.today).exists())
        self.assertFalse(f.late)
        self.assertEqual(f.now, D("10500"))   # it's in the wallet now

    def test_period_choices(self):
        self.assertEqual(self.client.get(reverse("upcoming") + "?days=90").context["days"], 90)
        self.assertEqual(self.client.get(reverse("upcoming") + "?days=5").context["days"], 30)


class FarmUpcomingTests(TestCase):
    def setUp(self):
        from apps.business.core.testing import make_farm
        from apps.business.finance.models import Account

        self.b, self.owner, self.staff = make_farm()
        self.client.force_login(self.owner)
        cash = Account.objects.get(business=self.b, name="Cash")
        cash.opening_balance = D("20000")
        cash.save()

    def test_loans_bills_baki_and_wages(self):
        from apps.business.finance.models import Category, RecurringTransaction
        from apps.business.loans.models import Lender, Loan
        from apps.business.parties.models import Party
        from apps.business.staff.models import Worker

        t = date.today()
        Loan.objects.create(business=self.b, lender=Lender.objects.create(business=self.b, name="Sonali"), principal=D("120000"),
                            taken_on=t - timedelta(days=20), rate=D("12"), repayment="emi", maturity=t + timedelta(days=345))
        RecurringTransaction.objects.create(business=self.b, name="Electricity", category=Category.objects.get(business=self.b, name="Electricity"),
                                            amount=D("3000"), repeat="monthly", start_date=t + timedelta(days=5), next_due=t + timedelta(days=5))
        buyer = Party.objects.create(business=self.b, name="Aratdar", is_buyer=True, opening_balance=D("9000"), opening_type="receivable",
                                     follow_up_on=t + timedelta(days=2), follow_up_note="After the auction")
        Worker.objects.create(business=self.b, name="Kamal", pay_type="monthly", rate=D("12000"), started_on=t - timedelta(days=100))

        r = self.client.get(reverse("business:upcoming"))
        f = r.context["f"]
        kinds = {i.kind for i in f.items}
        self.assertTrue({"loan", "bill", "baki", "wages"} <= kinds, kinds)
        baki = next(i for i in f.items if i.kind == "baki")
        self.assertEqual((baki.title, baki.amount, baki.date), ("Aratdar", D("9000"), buyer.follow_up_on))
        self.assertIn("After the auction", baki.detail)
        self.assertEqual(f.now, D("20000"))
        self.assertContains(r, "Upcoming money")
        self.assertContains(self.client.get(reverse("business:home")), reverse("business:upcoming"))

    def test_staff_cant_see_it(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse("business:upcoming")).status_code, 403)
