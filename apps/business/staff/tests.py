"""Staff & wages: the khata adds up, wages are a cost once, pay leaves the
right account, and money stays hidden from data-entry staff."""
from datetime import date, timedelta
from decimal import Decimal as D

from django.test import TestCase
from django.urls import reverse

from apps.business.core.testing import make_farm
from apps.business.finance import services as money
from apps.business.finance.models import Account
from apps.business.ponds.models import CultureCycle, Pond
from apps.business.ponds.services import summarize

from . import services
from .models import Earning, EarningKind, PayType, Worker, WorkerPayment

TODAY = date.today()


class StaffBase(TestCase):
    def setUp(self):
        self.b, self.owner, self.staff = make_farm()
        self.client.force_login(self.owner)
        self.cash = Account.objects.get(business=self.b, name="Cash")
        self.guard = Worker.objects.create(business=self.b, name="Karim", job="Guard", pay_type=PayType.MONTHLY,
                                           rate=D("9000"), started_on=TODAY - timedelta(days=400))
        self.daily = Worker.objects.create(business=self.b, name="Rahim", pay_type=PayType.DAILY, rate=D("500"),
                                           started_on=TODAY - timedelta(days=60))
        self.pond = Pond.objects.create(business=self.b, name="East")
        self.cycle = CultureCycle.objects.create(business=self.b, pond=self.pond, name="Carp", start_date=TODAY - timedelta(days=50))

    def earn(self, worker, amount, kind=EarningKind.BONUS, when=TODAY, **kw):
        return Earning.objects.create(business=self.b, worker=worker, kind=kind, date=when, amount=D(amount), **kw)

    def pay(self, worker, amount, kind="wage", when=TODAY):
        return WorkerPayment.objects.create(business=self.b, worker=worker, kind=kind, date=when, amount=D(amount), account=self.cash)


class KhataTests(StaffBase):
    def test_balance_is_opening_plus_earned_minus_paid(self):
        self.guard.opening_balance = D("1000")
        self.guard.save()
        self.earn(self.guard, "9000", EarningKind.SALARY)
        self.earn(self.guard, "500", EarningKind.DEDUCTION)
        self.pay(self.guard, "6000")
        self.assertEqual(services.balance(self.guard), D("3500"))
        lines = services.khata(self.guard)
        self.assertEqual(lines[-1].balance, D("3500"))

    def test_an_advance_makes_the_balance_negative(self):
        self.pay(self.daily, "2000", "advance")
        self.assertEqual(services.balance(self.daily), D("-2000"))
        Earning.objects.create(business=self.b, worker=self.daily, kind=EarningKind.WORK, date=TODAY, days=D("3"), rate=D("500"), amount=0)
        self.assertEqual(services.balance(self.daily), D("-500"))

    def test_days_worked_are_days_times_rate(self):
        e = Earning.objects.create(business=self.b, worker=self.daily, kind=EarningKind.WORK, date=TODAY, days=D("0.5"), rate=D("500"), amount=0)
        self.assertEqual(e.amount, D("250.00"))

    def test_a_changed_rate_never_changes_past_wages(self):
        Earning.objects.create(business=self.b, worker=self.daily, kind=EarningKind.WORK, date=TODAY, days=D("1"), rate=D("500"), amount=0)
        self.daily.rate = D("700")
        self.daily.save()
        self.assertEqual(services.balance(self.daily), D("500"))

    def test_part_month_salary(self):
        w = Worker.objects.create(business=self.b, name="New", pay_type=PayType.MONTHLY, rate=D("9000"), started_on=date(2026, 9, 16))
        self.assertEqual(w.salary_for(date(2026, 9, 1)), D("4500"))
        self.assertEqual(w.salary_for(date(2026, 10, 1)), D("9000"))
        self.assertEqual(w.salary_for(date(2026, 8, 1)), D("0"))


class MoneyTests(StaffBase):
    def test_pay_leaves_the_account(self):
        before = money.balances(self.b)[self.cash.pk]
        self.pay(self.guard, "4000")
        self.assertEqual(money.balances(self.b)[self.cash.pk], before - D("4000"))

    def test_wages_are_a_cost_when_earned_not_when_paid(self):
        self.earn(self.guard, "9000", EarningKind.SALARY)
        self.pay(self.guard, "3000", "advance")
        s = money.statement(self.b, TODAY.replace(day=1), TODAY)
        wages = [l for l in s.expense if l.key == "wages"]
        self.assertEqual(wages[0].amount, D("9000"))

    def test_wages_for_a_pond_count_in_its_cycle(self):
        self.earn(self.daily, "1500", EarningKind.BONUS, cycle=self.cycle)
        self.earn(self.daily, "999", EarningKind.BONUS)       # whole farm: not this pond
        s = summarize(self.cycle)
        self.assertEqual(s.wage_cost, D("1500"))
        self.assertEqual(s.cost, D("1500"))


class PageTests(StaffBase):
    def test_list_and_khata(self):
        self.earn(self.guard, "9000", EarningKind.SALARY)
        r = self.client.get(reverse("business:staff"))
        self.assertContains(r, "Karim")
        self.assertContains(r, "you owe")
        self.assertContains(self.client.get(reverse("business:staff_worker", args=[self.guard.pk])), "9,000")

    def test_pay_form_suggests_what_is_owed(self):
        self.earn(self.guard, "9000", EarningKind.SALARY)
        r = self.client.get(reverse("business:staff_pay", args=[self.guard.pk]))
        self.assertContains(r, 'value="9000"')
        r = self.client.post(reverse("business:staff_pay", args=[self.guard.pk]),
                             {"date": TODAY.isoformat(), "kind": "wage", "amount": "9000", "account": self.cash.pk})
        self.assertRedirects(r, reverse("business:staff_worker", args=[self.guard.pk]))
        self.assertEqual(services.balance(self.guard), 0)

    def test_work_sheet_writes_and_clears_wages(self):
        url = reverse("business:staff_work")
        day = TODAY.isoformat()
        self.client.post(url, {"date": day, f"d{self.daily.pk}": "1", f"c{self.daily.pk}": self.cycle.pk})
        e = Earning.objects.get(worker=self.daily, date=TODAY)
        self.assertEqual((e.amount, e.cycle), (D("500.00"), self.cycle))
        self.client.post(url, {"date": day, f"d{self.daily.pk}": "0.5"})
        self.assertEqual(Earning.objects.get(worker=self.daily, date=TODAY).amount, D("250.00"))
        self.client.post(url, {"date": day, f"d{self.daily.pk}": "0"})
        self.assertFalse(Earning.objects.filter(worker=self.daily, date=TODAY).exists())

    def test_salary_sheet_writes_once_and_can_pay(self):
        month = (TODAY.replace(day=1) - timedelta(days=1)).replace(day=1)
        url = reverse("business:staff_salaries")
        self.pay(self.guard, "2000", "advance")
        self.client.post(url, {"month": f"{month:%Y-%m}", f"w{self.guard.pk}": "1", f"a{self.guard.pk}": "9000", "pay": "1", "account": self.cash.pk})
        self.assertEqual(Earning.objects.filter(worker=self.guard, kind=EarningKind.SALARY, month=month).count(), 1)
        self.assertEqual(services.balance(self.guard), 0)                     # 9000 − 2000 advance − 7000 paid
        self.assertEqual(WorkerPayment.objects.filter(worker=self.guard, kind="wage").get().amount, D("7000"))
        self.client.post(url, {"month": f"{month:%Y-%m}", f"w{self.guard.pk}": "1", f"a{self.guard.pk}": "9000"})
        self.assertEqual(Earning.objects.filter(worker=self.guard, kind=EarningKind.SALARY, month=month).count(), 1)

    def test_a_month_salary_cannot_be_written_twice(self):
        self.earn(self.guard, "9000", EarningKind.SALARY)
        r = self.client.post(reverse("business:staff_earn", args=[self.guard.pk]),
                             {"date": TODAY.isoformat(), "kind": "salary", "amount": "9000"})
        self.assertContains(r, "already written")

    def test_home_reminds_about_last_months_salaries(self):
        self.assertContains(self.client.get(reverse("business:home")), "salaries not written yet")

    def test_data_entry_sees_the_work_sheet_but_not_the_money(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse("business:staff")).status_code, 403)
        self.assertEqual(self.client.get(reverse("business:staff_salaries")).status_code, 403)
        r = self.client.get(reverse("business:staff_work"))
        self.assertContains(r, "Rahim")
        self.assertNotContains(r, "500 a day")
        self.assertNotContains(self.client.get(reverse("business:home")), "salaries not written yet")
