"""Recurring expense / income and goal auto-save: starts on, ends on, and the month-end day."""
from datetime import date, timedelta
from decimal import Decimal as D

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from apps.expense.models import Expense, ExpenseCategory, RecurringExpense
from apps.goals.models import AutoSave, GoalEntry, SavingsGoal
from apps.goals.services import run_autosave
from apps.income.models import IncomeSource, IncomeTransaction, RecurringIncome

TODAY = date.today()


class ScheduleDateTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("me", password="pw12345!")
        self.client.force_login(self.user)
        self.cat = ExpenseCategory.objects.create(user=self.user, name="Rent")
        self.src = IncomeSource.objects.create(user=self.user, name="Salary")

    def test_new_schedule_starts_on_its_start_date_and_keeps_an_end(self):
        start, end = TODAY + timedelta(days=3), TODAY + timedelta(days=200)
        r = self.client.post(reverse("recurring_expense_create"), {"category": self.cat.pk, "amount": "5000", "frequency": "MONTHLY",
                                                                    "start_date": start.isoformat(), "end_date": end.isoformat()})
        self.assertEqual(r.status_code, 302)
        s = RecurringExpense.objects.get()
        self.assertEqual((s.start_date, s.next_run_date, s.end_date), (start, start, end))

    def test_older_forms_sending_only_the_next_date_still_work(self):
        nxt = TODAY + timedelta(days=5)
        self.client.post(reverse("recurring_income_create"), {"source": self.src.pk, "amount": "30000", "frequency": "MONTHLY",
                                                               "next_run_date": nxt.isoformat()})
        s = RecurringIncome.objects.get()
        self.assertEqual((s.start_date, s.next_run_date), (nxt, nxt))

    def test_end_before_start_is_refused(self):
        r = self.client.post(reverse("recurring_expense_create"), {"category": self.cat.pk, "amount": "10", "frequency": "MONTHLY",
                                                                    "start_date": TODAY.isoformat(), "end_date": (TODAY - timedelta(days=1)).isoformat()})
        self.assertContains(r, "The end date is before the start date.")
        self.assertFalse(RecurringExpense.objects.exists())

    def test_nothing_is_created_after_the_end_date(self):
        start = TODAY - timedelta(days=70)
        s = RecurringExpense.objects.create(user=self.user, category=self.cat, amount=D("100"), frequency="WEEKLY",
                                            start_date=start, next_run_date=start, end_date=start + timedelta(days=20))
        s.generate_due_transactions(today=TODAY)
        self.assertEqual(Expense.objects.count(), 3)                 # day 0, 7, 14 — not 21 and later
        s.refresh_from_db()
        self.assertTrue(s.has_ended)
        r = self.client.get(reverse("recurring_expense_list"))
        self.assertContains(r, "Ended")
        self.assertNotIn(s, list(self.client.get(reverse("expense_dashboard")).context["upcoming"]))

    def test_income_stops_at_its_end_too(self):
        start = TODAY - timedelta(days=60)
        s = RecurringIncome.objects.create(source=self.src, amount=D("1000"), frequency="BIWEEKLY", start_date=start, next_run_date=start,
                                           end_date=start + timedelta(days=14))
        s.generate_due_transactions(today=TODAY)
        self.assertEqual(IncomeTransaction.objects.count(), 2)

    def test_month_end_day_is_kept_after_a_short_month(self):
        s = RecurringExpense(user=self.user, category=self.cat, amount=D("1"), frequency="MONTHLY",
                             start_date=date(2026, 1, 31), next_run_date=date(2026, 1, 31))
        feb = s._advance(date(2026, 1, 31))
        self.assertEqual((feb, s._advance(feb)), (date(2026, 2, 28), date(2026, 3, 31)))
        s.start_date = None                                           # no start date: the old behaviour
        self.assertEqual(s._advance(date(2026, 2, 28)), date(2026, 3, 28))

    def test_editing_shows_the_next_date_and_never_before_the_start(self):
        s = RecurringExpense.objects.create(user=self.user, category=self.cat, amount=D("100"), frequency="MONTHLY",
                                            start_date=TODAY, next_run_date=TODAY + timedelta(days=30))
        r = self.client.get(reverse("recurring_expense_edit", args=[s.pk]))
        self.assertContains(r, "Next date")
        later = TODAY + timedelta(days=60)
        self.client.post(reverse("recurring_expense_edit", args=[s.pk]), {"category": self.cat.pk, "amount": "100", "frequency": "MONTHLY",
                                                                          "start_date": later.isoformat(), "next_run_date": (TODAY + timedelta(days=30)).isoformat()})
        s.refresh_from_db()
        self.assertEqual((s.start_date, s.next_run_date), (later, later))

    def test_auto_save_has_start_and_end(self):
        goal = SavingsGoal.objects.create(user=self.user, name="Bike", target_amount=D("100000"))
        r = self.client.post(reverse("goal_autosave", args=[goal.pk]), {"amount": "1000", "frequency": "WEEKLY",
                                                                        "start_date": (TODAY - timedelta(days=1)).isoformat()}, follow=True)
        self.assertContains(r, "Pick today or a later date")
        self.client.post(reverse("goal_autosave", args=[goal.pk]), {"amount": "1000", "frequency": "WEEKLY", "start_date": TODAY.isoformat(),
                                                                    "end_date": (TODAY + timedelta(days=10)).isoformat()})
        a = AutoSave.objects.get()
        # Starting today, the first deposit goes in straight away and the next is a week on.
        self.assertEqual((a.start_date, a.next_run_date, a.end_date), (TODAY, TODAY + timedelta(days=7), TODAY + timedelta(days=10)))
        GoalEntry.objects.all().delete()
        AutoSave.objects.filter(pk=a.pk).update(next_run_date=TODAY - timedelta(days=21), start_date=TODAY - timedelta(days=21),
                                                end_date=TODAY - timedelta(days=8))
        a.refresh_from_db()
        run_autosave(a, TODAY)
        self.assertEqual(GoalEntry.objects.filter(is_auto=True).count(), 2)  # day −21 and −14; −7 is past the end
