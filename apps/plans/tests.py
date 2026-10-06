"""Installment plans: schedule, what's paid, what's late, and the due date that follows."""
from datetime import date, timedelta
from decimal import Decimal as D

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from apps.creditors.models import Creditor, Transaction as CT
from apps.debtors.models import Debtor, Transaction as DT

from . import services
from .models import InstallmentPlan

TODAY = date.today()


class PlanTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("me", password="pw12345!")
        self.client.force_login(self.user)
        self.rahim = Debtor.objects.create(user=self.user, name="Rahim", phone="01711000000")
        DT.objects.create(debtor=self.rahim, transaction_type=DT.LEND, amount=D("10000"), date=TODAY - timedelta(days=120))

    def plan(self, **kw):
        kw.setdefault("amount", D("2000"))
        kw.setdefault("start_date", services.add_months(TODAY, -2))       # 3 dates are due by today
        return InstallmentPlan.objects.create(user=self.user, debtor=self.rahim, **kw)

    def receive(self, amount, days_ago=0):
        DT.objects.create(debtor=self.rahim, transaction_type=DT.RECEIVE, amount=D(amount), date=TODAY - timedelta(days=days_ago))

    def test_schedule_and_behind(self):
        p = self.plan()
        self.receive("2000", 50)
        st = services.status(p)
        self.assertEqual((st.count, st.paid_count, st.due_so_far, st.behind, st.missed), (5, 1, D("6000"), D("4000"), 2))
        self.assertEqual(st.next_date, services.add_months(TODAY, -1))
        self.assertEqual(st.next_amount, D("4000"))
        self.assertEqual(st.last_date, services.add_months(TODAY, 2))

    def test_payments_move_the_due_date(self):
        p = self.plan()
        services.sync_due_date(p)
        self.rahim.refresh_from_db()
        self.assertEqual(self.rahim.due_date, services.add_months(TODAY, -2))
        self.receive("6000")
        self.rahim.refresh_from_db()
        self.assertEqual(self.rahim.due_date, services.add_months(TODAY, 1))   # the 4th installment
        self.receive("4000")
        self.rahim.refresh_from_db()
        self.assertIsNone(self.rahim.due_date)
        self.assertTrue(services.status(p).done)

    def test_an_early_first_payment_counts(self):
        p = self.plan(start_date=TODAY + timedelta(days=10))
        self.receive("2000", 5)
        st = services.status(p)
        self.assertEqual((st.paid_count, st.behind), (1, D("0")))

    def test_form_splits_by_number_of_installments(self):
        r = self.client.post(reverse("plan_form", args=["debtor", self.rahim.pk]),
                             {"installments": "4", "frequency": "monthly", "start_date": TODAY.isoformat()})
        self.assertRedirects(r, reverse("debtor_detail", args=[self.rahim.pk]))
        p = InstallmentPlan.objects.get()
        self.assertEqual(p.amount, D("2500"))
        self.rahim.refresh_from_db()
        self.assertEqual(self.rahim.due_date, TODAY)

    def test_detail_page_card_reminder_and_attention(self):
        self.plan()
        services.sync_due_date(self.rahim.plan)
        r = self.client.get(reverse("debtor_detail", args=[self.rahim.pk]))
        self.assertContains(r, "Installment plan")
        self.assertContains(r, "3 installments missed")
        self.assertContains(r, "৳6,000 is still due")                      # the reminder asks for what's late, not all ৳10,000
        r = self.client.get(reverse("networth"))
        self.assertContains(r, "installment")

    def test_offer_on_ledgers_without_a_plan_and_removal(self):
        k = Creditor.objects.create(user=self.user, name="Karim")
        CT.objects.create(creditor=k, transaction_type=CT.BORROW, amount=D("3000"), date=TODAY)
        self.assertContains(self.client.get(reverse("creditor_detail", args=[k.pk])), "Paying in installments")
        self.client.post(reverse("plan_form", args=["creditor", k.pk]), {"amount": "1000", "frequency": "weekly", "start_date": TODAY.isoformat()})
        self.assertEqual(services.status(InstallmentPlan.objects.get(creditor=k)).count, 3)
        self.client.post(reverse("plan_delete", args=["creditor", k.pk]))
        self.assertFalse(InstallmentPlan.objects.exists())

    def test_others_cannot_touch_your_plans(self):
        other = User.objects.create_user("them", password="pw12345!")
        self.client.force_login(other)
        self.assertEqual(self.client.get(reverse("plan_form", args=["debtor", self.rahim.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("plan_form", args=["nonsense", 1])).status_code, 404)
