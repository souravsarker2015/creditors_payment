from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import (
    IncomeSource,
    IncomeTransaction,
    RecurringIncome,
    RecurringFrequency,
    RECURRING_CATCHUP_LIMIT,
    generate_due_recurring_income,
)


class IncomeFilterTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="income_user", password="secret123")
        self.client.force_login(self.user)

        self.salary = IncomeSource.objects.create(user=self.user, name="Salary")
        self.freelance = IncomeSource.objects.create(user=self.user, name="Freelance")

        IncomeTransaction.objects.create(
            source=self.salary,
            amount=Decimal("1000.00"),
            date=date(2025, 1, 10),
        )
        IncomeTransaction.objects.create(
            source=self.salary,
            amount=Decimal("1500.00"),
            date=date(2026, 2, 10),
        )
        IncomeTransaction.objects.create(
            source=self.freelance,
            amount=Decimal("700.00"),
            date=date(2026, 3, 15),
        )

    def test_dashboard_filters_by_source_include(self):
        response = self.client.get(
            reverse("income_dashboard"),
            {"filter_mode": "include", "source": str(self.salary.id)},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_income"], Decimal("2500.00"))
        self.assertEqual(response.context["source_labels"], ["Salary"])

    def test_dashboard_filters_by_source_exclude(self):
        response = self.client.get(
            reverse("income_dashboard"),
            {"filter_mode": "exclude", "source": str(self.salary.id)},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_income"], Decimal("700.00"))
        self.assertEqual(response.context["source_labels"], ["Freelance"])

    def test_dashboard_filters_by_year_and_date_range(self):
        response = self.client.get(
            reverse("income_dashboard"),
            {"year": "2026", "date_from": "2026-02-01", "date_to": "2026-02-28"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_income"], Decimal("1500.00"))
        self.assertEqual(response.context["source_labels"], ["Salary"])

    def test_source_list_filters_and_stats(self):
        response = self.client.get(reverse("income_source_list"), {"year": "2026"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_sources"], 2)
        self.assertEqual(response.context["total_income"], Decimal("2200.00"))
        self.assertEqual(response.context["avg_income"], Decimal("1100.00"))

    def test_source_detail_filters_transactions(self):
        response = self.client.get(
            reverse("income_source_detail", kwargs={"pk": self.salary.pk}),
            {"year": "2026"},
        )
        self.assertEqual(response.status_code, 200)
        # total_source_income is always the true all-time running total, unaffected by
        # the year filter (1000 from 2025 + 1500 from 2026); period_income is the
        # filtered figure for the selected year.
        self.assertEqual(response.context["total_source_income"], Decimal("2500.00"))
        self.assertEqual(response.context["period_income"], Decimal("1500.00"))
        self.assertEqual(response.context["transactions"].count(), 1)


class RecurringIncomeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="recurring_income_user", password="secret123")
        self.other_user = User.objects.create_user(username="recurring_income_other", password="secret123")
        self.source = IncomeSource.objects.create(user=self.user, name="Salary")
        self.today = timezone.now().date()

    def test_catches_up_all_missed_monthly_occurrences(self):
        schedule = RecurringIncome.objects.create(
            source=self.source, amount=Decimal("50000.00"), frequency=RecurringFrequency.MONTHLY,
            next_run_date=self.today - timedelta(days=95),
        )
        created = schedule.generate_due_transactions(today=self.today)
        self.assertEqual(created, 4)
        self.assertEqual(self.source.transactions.count(), 4)
        self.assertTrue(all(tx.recurring_source_id == schedule.pk for tx in self.source.transactions.all()))
        schedule.refresh_from_db()
        self.assertGreater(schedule.next_run_date, self.today)

    def test_idempotent_on_repeated_calls_same_day(self):
        schedule = RecurringIncome.objects.create(
            source=self.source, amount=Decimal("1000.00"), frequency=RecurringFrequency.MONTHLY,
            next_run_date=self.today - timedelta(days=1),
        )
        schedule.generate_due_transactions(today=self.today)
        created_again = schedule.generate_due_transactions(today=self.today)
        self.assertEqual(created_again, 0)
        self.assertEqual(self.source.transactions.count(), 1)

    def test_paused_schedule_does_not_generate(self):
        schedule = RecurringIncome.objects.create(
            source=self.source, amount=Decimal("1000.00"), frequency=RecurringFrequency.MONTHLY,
            next_run_date=self.today - timedelta(days=1), is_active=False,
        )
        created = schedule.generate_due_transactions(today=self.today)
        self.assertEqual(created, 0)
        self.assertEqual(self.source.transactions.count(), 0)

    def test_future_dated_schedule_generates_nothing_yet(self):
        schedule = RecurringIncome.objects.create(
            source=self.source, amount=Decimal("1000.00"), frequency=RecurringFrequency.YEARLY,
            next_run_date=self.today + timedelta(days=30),
        )
        created = schedule.generate_due_transactions(today=self.today)
        self.assertEqual(created, 0)

    def test_catchup_capped_per_call_and_continues_next_call(self):
        schedule = RecurringIncome.objects.create(
            source=self.source, amount=Decimal("100.00"), frequency=RecurringFrequency.WEEKLY,
            next_run_date=self.today - timedelta(days=3 * 365),
        )
        first = schedule.generate_due_transactions(today=self.today)
        self.assertEqual(first, RECURRING_CATCHUP_LIMIT)
        self.assertLessEqual(schedule.next_run_date, self.today)
        second = schedule.generate_due_transactions(today=self.today)
        self.assertGreater(second, 0)

    def test_manager_function_respects_cross_user_isolation(self):
        other_source = IncomeSource.objects.create(user=self.other_user, name="Other Salary")
        RecurringIncome.objects.create(
            source=other_source, amount=Decimal("1000.00"), frequency=RecurringFrequency.MONTHLY,
            next_run_date=self.today - timedelta(days=1),
        )
        created_for_user = generate_due_recurring_income(self.user)
        self.assertEqual(created_for_user, 0)
        created_for_other = generate_due_recurring_income(self.other_user)
        self.assertEqual(created_for_other, 1)

    def test_month_end_clamps_correctly_across_leap_and_non_leap_february(self):
        schedule = RecurringIncome.objects.create(
            source=self.source, amount=Decimal("1.00"), frequency=RecurringFrequency.MONTHLY,
            next_run_date=date(2024, 1, 31), is_active=False,
        )
        self.assertEqual(schedule._advance(date(2024, 1, 31)), date(2024, 2, 29))  # leap year
        self.assertEqual(schedule._advance(date(2025, 1, 31)), date(2025, 2, 28))  # non-leap year

    def test_skip_weekend_off_by_default_and_leaves_date_untouched(self):
        friday = self.today
        while friday.weekday() != 4:
            friday += timedelta(days=1)
        schedule = RecurringIncome.objects.create(
            source=self.source, amount=Decimal("1000.00"), frequency=RecurringFrequency.MONTHLY,
            next_run_date=friday,
        )
        self.assertFalse(schedule.skip_weekend)
        schedule.generate_due_transactions(today=friday)
        tx = self.source.transactions.first()
        self.assertEqual(tx.date, friday)

    def test_skip_weekend_shifts_friday_and_saturday_to_thursday_without_drifting_anchor(self):
        friday = self.today
        while friday.weekday() != 4:
            friday += timedelta(days=1)
        saturday = friday + timedelta(days=1)
        thursday = friday - timedelta(days=1)

        friday_schedule = RecurringIncome.objects.create(
            source=self.source, amount=Decimal("1000.00"), frequency=RecurringFrequency.MONTHLY,
            next_run_date=friday, skip_weekend=True,
        )
        friday_schedule.generate_due_transactions(today=friday)
        self.assertEqual(self.source.transactions.first().date, thursday)
        # The anchor itself advances from the true scheduled date (the Friday), not the
        # shifted Thursday, so the schedule doesn't creep earlier month over month.
        from .models import _add_months
        friday_schedule.refresh_from_db()
        self.assertEqual(friday_schedule.next_run_date, _add_months(friday, 1))

        other_source = IncomeSource.objects.create(user=self.user, name="Saturday Payer")
        saturday_schedule = RecurringIncome.objects.create(
            source=other_source, amount=Decimal("1000.00"), frequency=RecurringFrequency.MONTHLY,
            next_run_date=saturday, skip_weekend=True,
        )
        saturday_schedule.generate_due_transactions(today=saturday)
        self.assertEqual(other_source.transactions.first().date, thursday)

    def test_next_effective_date_previews_the_shift(self):
        friday = self.today + timedelta(days=10)
        while friday.weekday() != 4:
            friday += timedelta(days=1)
        schedule = RecurringIncome.objects.create(
            source=self.source, amount=Decimal("1000.00"), frequency=RecurringFrequency.MONTHLY,
            next_run_date=friday, skip_weekend=True,
        )
        self.assertEqual(schedule.next_effective_date, friday - timedelta(days=1))

    def test_dashboard_visit_triggers_catchup_and_shows_message(self):
        self.client.force_login(self.user)
        RecurringIncome.objects.create(
            source=self.source, amount=Decimal("2000.00"), frequency=RecurringFrequency.MONTHLY,
            next_run_date=self.today - timedelta(days=1),
        )
        response = self.client.get(reverse("income_dashboard"), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.source.transactions.count(), 1)

    def test_toggle_pause_and_resume_via_view(self):
        self.client.force_login(self.user)
        schedule = RecurringIncome.objects.create(
            source=self.source, amount=Decimal("1000.00"), frequency=RecurringFrequency.MONTHLY,
            next_run_date=self.today + timedelta(days=30),
        )
        self.client.post(reverse("recurring_income_toggle", args=[schedule.pk]))
        schedule.refresh_from_db()
        self.assertFalse(schedule.is_active)
        self.client.post(reverse("recurring_income_toggle", args=[schedule.pk]))
        schedule.refresh_from_db()
        self.assertTrue(schedule.is_active)

    def test_delete_schedule_keeps_past_generated_transactions(self):
        schedule = RecurringIncome.objects.create(
            source=self.source, amount=Decimal("1000.00"), frequency=RecurringFrequency.MONTHLY,
            next_run_date=self.today - timedelta(days=1),
        )
        schedule.generate_due_transactions(today=self.today)
        self.assertEqual(self.source.transactions.count(), 1)
        schedule.delete()
        self.assertEqual(self.source.transactions.count(), 1)
        self.assertIsNone(self.source.transactions.first().recurring_source)
