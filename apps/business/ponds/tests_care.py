"""Lime, medicine & pond care: dose calculator, costs, and the medicine waiting period."""
from datetime import date, timedelta
from decimal import Decimal as D

from django.test import TestCase
from django.urls import reverse

from apps.business.core.models import Unit
from apps.business.core.testing import make_farm
from apps.business.finance import services as money
from apps.business.finance.models import Account

from . import services
from .models import CultureCycle, Pond, Treatment

TODAY = date.today()


class CareTests(TestCase):
    def setUp(self):
        self.b, self.owner, self.staff = make_farm()
        self.client.force_login(self.owner)
        self.dec = Unit.objects.get(business=self.b, symbol="dec")
        self.kg = Unit.objects.get(business=self.b, symbol="kg")
        self.cash = Account.objects.get(business=self.b, name="Cash")
        self.pond = Pond.objects.create(business=self.b, name="East", area=D("60"), area_unit=self.dec)
        self.cycle = CultureCycle.objects.create(business=self.b, pond=self.pond, name="Carp", start_date=TODAY - timedelta(days=40))

    def add(self, **data):
        base = {"treatment-date": TODAY.isoformat(), "treatment-kind": "lime", "treatment-product": "Dolomite",
                "treatment-unit": self.kg.pk, "treatment-cost": "", "treatment-account": ""}
        base.update({f"treatment-{k}": v for k, v in data.items()})
        return self.client.post(reverse("business:entry_add", args=[self.cycle.pk, "treatment"]), base)

    def test_dose_per_decimal_times_pond_size(self):
        self.add(dose="1.5")
        self.assertEqual(Treatment.objects.get().quantity, D("90.000"))

    def test_cost_is_a_pond_cost_and_money_out(self):
        before = money.balances(self.b)[self.cash.pk]
        self.add(cost="1800", account=self.cash.pk, quantity="60")
        self.assertEqual(services.summarize(self.cycle).care_cost, D("1800"))
        self.assertEqual(money.balances(self.b)[self.cash.pk], before - D("1800"))
        s = money.statement(self.b, TODAY - timedelta(days=1), TODAY)
        self.assertIn(D("1800"), [l.amount for l in s.expense if l.key == "care"])

    def test_bought_earlier_counts_for_the_pond_but_moves_no_money(self):
        before = money.balances(self.b)[self.cash.pk]
        self.add(cost="500", quantity="10")
        self.assertEqual(services.summarize(self.cycle).care_cost, D("500"))
        self.assertEqual(money.balances(self.b)[self.cash.pk], before)

    def test_medicine_waiting_period_warns_everywhere(self):
        self.add(kind="medicine", product="Oxytetracycline", quantity="2", withdrawal_days="21")
        t = Treatment.objects.get()
        self.assertEqual(services.withdrawal(self.cycle), t)
        self.assertContains(self.client.get(reverse("business:cycle_detail", args=[self.cycle.pk])), "Don't sell fish from this pond before")
        self.assertIn("Don't sell fish from East yet", [x.title for x in services.farm_tasks(self.b)])
        r = self.client.get(reverse("business:sale_add"))
        self.assertContains(r, "Oxytetracycline")
        self.assertIsNone(services.withdrawal(self.cycle, today=TODAY + timedelta(days=21)))

    def test_shows_in_the_water_and_care_tab(self):
        self.add(product="Zeolite", quantity="20", reason="Gas at the bottom")
        r = self.client.get(reverse("business:cycle_detail", args=[self.cycle.pk]) + "?tab=water")
        self.assertContains(r, "Zeolite")
        self.assertContains(r, "Gas at the bottom")
