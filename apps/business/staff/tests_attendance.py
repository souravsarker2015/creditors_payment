"""Monthly staff on the work sheet, days off on the salary sheet, and the month's attendance."""
import calendar
from datetime import date, timedelta
from decimal import Decimal as D

from django.test import TestCase
from django.urls import reverse

from apps.business.core.testing import make_farm

from . import services
from .models import Absence, Earning, EarningKind, PayType, Worker


def month_day(n):
    """Day n of last month — a whole month in the past, whatever today is."""
    first = (date.today().replace(day=1) - timedelta(days=1)).replace(day=1)
    return first.replace(day=n)


class AttendanceTests(TestCase):
    def setUp(self):
        self.b, self.owner, self.staff = make_farm()
        self.client.force_login(self.owner)
        self.month = month_day(1)
        self.guard = Worker.objects.create(business=self.b, name="Karim", pay_type=PayType.MONTHLY, rate=D("9000"), started_on=self.month - timedelta(days=300))
        self.daily = Worker.objects.create(business=self.b, name="Rahim", pay_type=PayType.DAILY, rate=D("500"), started_on=self.month - timedelta(days=60))

    def sheet(self, day, **marks):
        return self.client.post(reverse("business:staff_work"), {"date": day.isoformat(), **marks})

    def test_marks_on_the_work_sheet(self):
        day = month_day(5)
        r = self.client.get(reverse("business:staff_work") + f"?date={day.isoformat()}")
        self.assertContains(r, f'name="m{self.guard.pk}"')
        self.sheet(day, **{f"m{self.guard.pk}": "0", f"d{self.daily.pk}": "1"})
        a = Absence.objects.get(worker=self.guard)
        self.assertEqual((a.date, a.days, a.paid), (day, D("1"), False))
        self.assertTrue(Earning.objects.filter(worker=self.daily, date=day, kind=EarningKind.WORK).exists())
        self.sheet(day, **{f"m{self.guard.pk}": "leave"})
        a.refresh_from_db()
        self.assertTrue(a.paid)
        self.sheet(day, **{f"m{self.guard.pk}": "1"})                       # here after all
        self.assertFalse(Absence.objects.exists())

    def test_staff_can_mark_attendance_too(self):
        self.client.force_login(self.staff)
        self.sheet(month_day(6), **{f"m{self.guard.pk}": "0.5"})
        self.assertEqual(Absence.objects.get().days, D("0.5"))

    def test_days_off_without_pay_come_off_the_salary(self):
        self.sheet(month_day(3), **{f"m{self.guard.pk}": "0"})
        self.sheet(month_day(4), **{f"m{self.guard.pk}": "0.5"})
        self.sheet(month_day(5), **{f"m{self.guard.pk}": "leave"})          # paid: not cut
        row = services.salary_sheet(self.b, self.month)[0]
        per_day = D("9000") / calendar.monthrange(self.month.year, self.month.month)[1]
        self.assertEqual(row.days_off, D("1.5"))
        self.assertEqual(row.leave, D("1"))
        self.assertEqual(row.cut, (per_day * D("1.5")).quantize(D("1")))
        self.assertEqual(row.amount, D("9000") - row.cut)
        self.assertFalse(row.is_partial)
        r = self.client.get(reverse("business:staff_salaries") + f"?month={self.month:%Y-%m}")
        self.assertContains(r, "data-salary-off")
        self.assertContains(r, f'value="{row.amount}"')

    def test_warns_when_the_salary_is_already_written(self):
        Earning.objects.create(business=self.b, worker=self.guard, kind=EarningKind.SALARY, date=month_day(28), amount=D("9000"))
        r = self.sheet(month_day(7), **{f"m{self.guard.pk}": "0"})
        msgs = [str(m) for m in r.wsgi_request._messages]
        self.assertTrue(any("already written" in m for m in msgs))

    def test_month_view(self):
        Earning.objects.create(business=self.b, worker=self.daily, kind=EarningKind.WORK, date=month_day(2), days=1, rate=D("500"), amount=D("500"))
        Earning.objects.create(business=self.b, worker=self.daily, kind=EarningKind.WORK, date=month_day(3), days=D("0.5"), rate=D("500"), amount=D("250"))
        Absence.objects.create(business=self.b, worker=self.guard, date=month_day(2))
        days, rows = services.attendance(self.b, self.month)
        by = {r.worker: dict(r.cells) for r in rows}
        self.assertEqual(by[self.daily][month_day(2)], "full")
        self.assertEqual(by[self.daily][month_day(3)], "half")
        self.assertEqual(by[self.daily][month_day(4)], "off")
        self.assertEqual(by[self.guard][month_day(2)], "off")
        self.assertEqual(by[self.guard][month_day(3)], "full")
        guard = next(r for r in rows if r.worker == self.guard)
        self.assertEqual((guard.worked, guard.off), (D(len(days) - 1), D("1")))
        r = self.client.get(reverse("business:staff_attendance") + f"?month={self.month:%Y-%m}")
        self.assertContains(r, 'data-state="half"')
        self.assertContains(r, reverse("business:staff_work") + f"?date={month_day(2).isoformat()}")

    def test_not_here_yet_or_after_leaving(self):
        Worker.objects.filter(pk=self.guard.pk).update(started_on=month_day(10))
        _days, rows = services.attendance(self.b, self.month)
        cells = dict(next(r for r in rows if r.worker.pk == self.guard.pk).cells)
        self.assertEqual((cells[month_day(9)], cells[month_day(10)]), ("none", "full"))
