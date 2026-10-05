"""Pond lease khata: payments, what's due, and each cycle's share."""
from datetime import date, timedelta
from decimal import Decimal as D

from django.test import TestCase
from django.urls import reverse

from apps.business.core.testing import make_farm
from apps.business.finance import services as money
from apps.business.finance.models import Account

from . import services
from .models import CultureCycle, LeasePayment, Pond

TODAY = date.today()


class LeaseTests(TestCase):
    def setUp(self):
        self.b, self.owner, self.staff = make_farm()
        self.client.force_login(self.owner)
        self.cash = Account.objects.get(business=self.b, name="Cash")
        start = TODAY - timedelta(days=99)
        self.pond = Pond.objects.create(business=self.b, name="Leased", ownership="leased", lease_from="Mr Karim",
                                        lease_amount=D("36500"), lease_start=start, lease_end=start + timedelta(days=364))

    def test_share_by_days(self):
        self.assertEqual(self.pond.lease_per_day, D("100"))
        self.assertEqual(self.pond.lease_share(TODAY - timedelta(days=9), TODAY), D("1000"))
        self.assertEqual(self.pond.lease_share(TODAY - timedelta(days=500), TODAY - timedelta(days=200)), D("0"))

    def test_cycle_cost_includes_its_lease_share(self):
        cycle = CultureCycle.objects.create(business=self.b, pond=self.pond, name="Carp", start_date=TODAY - timedelta(days=29))
        s = services.summarize(cycle)
        self.assertEqual(s.lease_cost, D("3000"))
        self.assertEqual(s.cost, D("3000"))

    def test_payments_due_and_money_out(self):
        before = money.balances(self.b)[self.cash.pk]
        r = self.client.post(reverse("business:lease_pay", args=[self.pond.pk]), {"date": TODAY.isoformat(), "amount": "6000", "account": self.cash.pk})
        self.assertRedirects(r, reverse("business:pond_detail", args=[self.pond.pk]))
        st = services.lease_status(self.pond)
        self.assertEqual((st.paid, st.due, st.used_share, st.behind), (D("6000"), D("30500"), D("10000"), D("4000")))
        self.assertEqual(money.balances(self.b)[self.cash.pk], before - D("6000"))
        s = money.statement(self.b, TODAY.replace(day=1), TODAY)
        self.assertIn(D("6000"), [l.amount for l in s.expense if l.key == "lease"])

    def test_pond_page_shows_the_lease_to_money_people_only(self):
        LeasePayment.objects.create(business=self.b, pond=self.pond, date=TODAY, amount=D("5000"), account=self.cash)
        url = reverse("business:pond_detail", args=[self.pond.pk])
        self.assertContains(self.client.get(url), "Still to pay")
        self.client.force_login(self.staff)
        self.assertNotContains(self.client.get(url), "Still to pay")
        self.assertEqual(self.client.get(reverse("business:lease_pay", args=[self.pond.pk])).status_code, 403)

    def test_lease_ending_soon_and_unpaid_is_urgent(self):
        self.pond.lease_end = TODAY + timedelta(days=10)
        self.pond.save()
        task = next(t for t in services.farm_tasks(self.b) if t.kind == "lease")
        self.assertEqual(task.tone, "critical")
        self.assertIn("not fully paid", task.detail)
