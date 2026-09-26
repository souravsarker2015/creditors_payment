from datetime import date
from decimal import Decimal as D

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.business.core.access import BUSINESS, create_business
from apps.business.core.models import Dashboard, Membership, Role, UserDashboardAccess

from .models import Lender, Loan, LoanRateChange, LoanTransaction
from .schedule import Terms, build


class ScheduleMathsTests(TestCase):
    """The engine against figures a lender would quote."""

    def test_monthly_rate_gives_round_interest(self):
        s = build(Terms(D(100000), date(2026, 1, 10), D(2), "month"), today=date(2026, 4, 20))
        self.assertEqual([p.interest for p in s.periods[:3]], [D("2000.00")] * 3)
        self.assertEqual(len(s.overdue_periods), 3)
        self.assertEqual(s.outstanding, D("100000"))

    def test_bank_emi_matches_the_standard_formula(self):
        t = Terms(D(500000), date(2026, 1, 1), D(12), "year", "reducing", "emi", maturity=date(2027, 1, 1))
        s = build(t, today=date(2026, 1, 1))
        self.assertEqual(len(s.periods), 12)
        self.assertEqual(s.periods[0].total, D("44424.39"))
        self.assertEqual(sum(p.principal for p in s.periods), D("500000"))

    def test_quarterly_interest_with_principal_at_the_end(self):
        t = Terms(D(200000), date(2026, 1, 1), D(10), every=3, maturity=date(2028, 1, 1))
        s = build(t, today=date(2026, 1, 1))
        self.assertEqual([p.due.month for p in s.periods[:4]], [4, 7, 10, 1])
        self.assertEqual(s.periods[0].total, D("5000.00"))
        self.assertEqual(s.periods[-1].total, D("205000.00"))

    def test_every_two_months_and_half_yearly(self):
        two = build(Terms(D(60000), date(2026, 1, 15), D(12), every=2, maturity=date(2027, 1, 15)), today=date(2026, 1, 15))
        self.assertEqual([p.due for p in two.periods[:2]], [date(2026, 3, 15), date(2026, 5, 15)])
        self.assertEqual(two.periods[0].interest, D("1200.00"))
        half = build(Terms(D(60000), date(2026, 1, 15), D(12), every=6, maturity=date(2028, 1, 15)), today=date(2026, 1, 15))
        self.assertEqual(len(half.periods), 4)
        self.assertEqual(half.periods[0].interest, D("3600.00"))

    def test_flat_interest_stays_on_the_full_amount(self):
        t = Terms(D(120000), date(2026, 1, 1), D(12), "year", "flat", "equal", maturity=date(2027, 1, 1))
        s = build(t, today=date(2026, 1, 1))
        self.assertTrue(all(p.interest == D("1200.00") for p in s.periods))

    def test_prepayment_covers_the_next_principal_and_cuts_interest(self):
        t = Terms(D(120000), date(2026, 1, 1), D(12), "year", "reducing", "equal", every=6, maturity=date(2028, 1, 1))
        s = build(t, payments=[(date(2026, 7, 1), D(30000), D(7200), D(0)), (date(2026, 9, 1), D(30000), D(0), D(0))],
                  today=date(2026, 10, 1))
        self.assertEqual(s.periods[0].status, "paid")
        self.assertEqual(s.periods[1].principal_left, D("0"))
        self.assertEqual(s.periods[1].interest, D("4206.52"))    # 90k for 62 days, 60k for 122 days
        self.assertEqual(s.outstanding, D("60000"))

    def test_rate_change_applies_from_its_date(self):
        t = Terms(D(100000), date(2026, 1, 1), D(12), maturity=date(2027, 1, 1))
        s = build(t, rate_changes=[(date(2026, 7, 1), D(24))], today=date(2026, 1, 1))
        self.assertEqual(s.periods[0].interest, D("1000.00"))
        self.assertEqual(s.periods[6].interest, D("2000.00"))

    def test_extra_borrowing_is_added_to_the_plan(self):
        t = Terms(D(100000), date(2026, 1, 1), D(12), "year", "reducing", "equal", maturity=date(2026, 11, 1))
        s = build(t, topups=[(date(2026, 6, 1), D(50000))], today=date(2026, 1, 1))
        self.assertEqual(s.borrowed, D("150000"))
        self.assertEqual(sum(p.principal for p in s.periods), D("150000"))

    def test_weekly_kisti(self):
        t = Terms(D(52000), date(2026, 1, 1), D(0), every=1, every_unit="week", repayment="equal", maturity=date(2026, 12, 31))
        s = build(t, today=date(2026, 1, 1))
        self.assertEqual(len(s.periods), 52)
        self.assertEqual(s.periods[1].due - s.periods[0].due, date(2026, 1, 15) - date(2026, 1, 8))

    def test_interest_free_open_ended_has_no_dues(self):
        s = build(Terms(D(30000), date(2026, 1, 1)), today=date(2026, 6, 1))
        self.assertEqual(s.periods, [])
        self.assertEqual(s.payoff, D("30000"))

    def test_paid_off_and_payoff(self):
        t = Terms(D(10000), date(2026, 1, 1), D(12), maturity=date(2026, 3, 1))
        s = build(t, today=date(2026, 2, 15))
        self.assertGreater(s.payoff, D("10000"))
        done = build(t, payments=[(date(2026, 3, 1), D(10000), D(200), D(0))], today=date(2026, 3, 2))
        self.assertTrue(done.is_paid_off)


class LoanPagesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.owner = User.objects.create_user("owner", password="x")
        cls.staff = User.objects.create_user("staff", password="x")
        dash = Dashboard.objects.get(code=BUSINESS)
        for u in (cls.owner, cls.staff):
            UserDashboardAccess.objects.create(user=u, dashboard=dash)
        cls.biz = create_business(cls.owner, "Farm")
        Membership.objects.create(business=cls.biz, user=cls.staff, role=Role.DATA_ENTRY)
        cls.lender = Lender.objects.create(business=cls.biz, name="Sonali Bank")
        cls.loan = Loan.objects.create(business=cls.biz, lender=cls.lender, principal=D(100000), taken_on=date(2026, 1, 1),
                                       rate=D(2), rate_period="month")

    def setUp(self):
        self.client.force_login(self.owner)

    def test_pages_render(self):
        for url in [reverse("business:loans"), reverse("business:loan_add"), reverse("business:lenders"),
                    reverse("business:loan_detail", args=[self.loan.pk]), reverse("business:loan_edit", args=[self.loan.pk]),
                    reverse("business:loan_csv", args=[self.loan.pk]), reverse("business:home")]:
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_data_entry_staff_cannot_see_loans(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse("business:loans")).status_code, 403)

    def test_create_loan(self):
        r = self.client.post(reverse("business:loan_add"), {
            "lender": self.lender.pk, "principal": "300000", "taken_on": "2026-02-01", "rate": "12", "rate_period": "year",
            "method": "reducing", "every": "3", "every_unit": "month", "repayment": "emi", "maturity": "2028-02-01"})
        loan = Loan.objects.latest("id")
        self.assertRedirects(r, reverse("business:loan_detail", args=[loan.pk]))
        self.assertEqual(len(loan.schedule(today=date(2026, 2, 1)).periods), 8)

    def test_emi_needs_an_end_date(self):
        r = self.client.post(reverse("business:loan_add"), {
            "lender": self.lender.pk, "principal": "1000", "taken_on": "2026-02-01", "rate": "12", "rate_period": "year",
            "method": "reducing", "every": "1", "every_unit": "month", "repayment": "emi"})
        self.assertFormError(r.context["form"], "maturity", "Pick an end date so the loan can be split into payments.")

    def test_record_payment_and_delete_it(self):
        url = reverse("business:loan_pay", args=[self.loan.pk])
        self.client.post(url, {"pay-date": "2026-02-01", "pay-interest": "2000", "pay-principal": "10000", "pay-paid_via": "cash"})
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.schedule().outstanding, D("90000"))
        txn = LoanTransaction.objects.get()
        self.client.post(reverse("business:loan_txn_delete", args=[txn.pk]))
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.schedule().outstanding, D("100000"))
        self.assertTrue(LoanTransaction.all_objects.get().is_deleted)

    def test_already_paid_marks_past_dues(self):
        self.client.post(reverse("business:loan_pay_past", args=[self.loan.pk]))
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.schedule().overdue_periods, [])

    def test_preview(self):
        r = self.client.post(reverse("business:loan_preview"), {
            "principal": "500000", "taken_on": "2026-01-01", "rate": "12", "rate_period": "year", "method": "reducing",
            "every": "1", "every_unit": "month", "repayment": "emi", "maturity": "2027-01-01"})
        data = r.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["count"], 12)
        self.assertEqual(data["instalment"], "৳44,424.40")

    def test_quick_add_lender(self):
        r = self.client.post(reverse("business:lender_quick_add"), {"qa_lender-name": "BRAC", "qa_lender-kind": "ngo"})
        self.assertEqual(r.status_code, 201)
        r = self.client.post(reverse("business:lender_quick_add"), {"qa_lender-name": "brac", "qa_lender-kind": "ngo"})
        self.assertEqual(r.status_code, 400)

    def test_lender_with_loans_cannot_be_deleted(self):
        self.client.post(reverse("business:lender_delete", args=[self.lender.pk]))
        self.assertFalse(Lender.all_objects.get(pk=self.lender.pk).is_deleted)

    def test_close_and_reopen(self):
        self.client.post(reverse("business:loan_close", args=[self.loan.pk]), {"closed_on": "2026-05-01"})
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.closed_on, date(2026, 5, 1))
        self.client.post(reverse("business:loan_close", args=[self.loan.pk]))
        self.loan.refresh_from_db()
        self.assertIsNone(self.loan.closed_on)

    def test_rate_change(self):
        self.client.post(reverse("business:loan_rate", args=[self.loan.pk]), {"rate-effective_from": "2026-06-01", "rate-rate": "3"})
        self.assertEqual(LoanRateChange.objects.get().rate, D("3"))

    def test_other_business_loans_are_hidden(self):
        other = create_business(self.staff, "Other farm")
        lender = Lender.objects.create(business=other, name="X")
        loan = Loan.objects.create(business=other, lender=lender, principal=D(1), taken_on=date(2026, 1, 1))
        self.assertEqual(self.client.get(reverse("business:loan_detail", args=[loan.pk])).status_code, 404)
