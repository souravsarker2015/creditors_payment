"""Equipment: service reminders, repairs, and their costs."""
from datetime import date, timedelta
from decimal import Decimal as D

from django.test import TestCase
from django.urls import reverse

from apps.business.core.testing import make_farm
from apps.business.finance import services as money
from apps.business.finance.models import Account

from . import services
from .models import Condition, Equipment, Service

TODAY = date.today()


class EquipmentTests(TestCase):
    def setUp(self):
        self.b, self.owner, self.staff = make_farm()
        self.client.force_login(self.owner)
        self.cash = Account.objects.get(business=self.b, name="Cash")
        self.aerator = Equipment.objects.create(business=self.b, name="Aerator 1", kind="aerator", bought_on=TODAY - timedelta(days=100),
                                                cost=D("25000"), account=self.cash, service_every_days=90)

    def test_next_service_counts_from_the_last_one(self):
        self.assertEqual(self.aerator.next_service(), TODAY - timedelta(days=10))
        Service.objects.create(business=self.b, equipment=self.aerator, date=TODAY - timedelta(days=5), cost=D("800"), account=self.cash)
        self.assertEqual(self.aerator.next_service(), TODAY + timedelta(days=85))

    def test_due_and_broken_show_on_the_farm_list(self):
        Equipment.objects.create(business=self.b, name="Pump", kind="pump", condition=Condition.REPAIR)
        r = self.client.get(reverse("business:home"))
        self.assertContains(r, "Service Aerator 1")
        self.assertContains(r, "Pump needs repair")

    def test_purchase_and_upkeep_are_costs_and_money_out(self):
        Service.objects.create(business=self.b, equipment=self.aerator, date=TODAY, cost=D("800"), account=self.cash)
        bal = money.balances(self.b)[self.cash.pk]
        self.assertEqual(bal, self.cash.opening_balance - D("25800"))
        s = money.statement(self.b, TODAY - timedelta(days=200), TODAY)
        keys = {l.key: l.amount for l in s.expense}
        self.assertEqual((keys["equipment"], keys["upkeep"]), (D("25000"), D("800")))

    def test_recording_a_repair_can_mark_it_working(self):
        self.aerator.condition = Condition.REPAIR
        self.aerator.save()
        r = self.client.post(reverse("business:equipment_service", args=[self.aerator.pk]),
                             {"date": TODAY.isoformat(), "kind": "repair", "description": "Motor rewound", "cost": "1200", "account": self.cash.pk, "fixed": "1"})
        self.assertRedirects(r, reverse("business:equipment_detail", args=[self.aerator.pk]))
        self.aerator.refresh_from_db()
        self.assertEqual(self.aerator.condition, Condition.WORKING)

    def test_list_and_detail_pages(self):
        self.assertContains(self.client.get(reverse("business:equipment")), "Aerator 1")
        r = self.client.get(reverse("business:equipment_detail", args=[self.aerator.pk]))
        self.assertContains(r, "Record a service")
        self.assertContains(r, "25,000")

    def test_data_entry_records_services_without_seeing_money(self):
        self.client.force_login(self.staff)
        r = self.client.get(reverse("business:equipment_detail", args=[self.aerator.pk]))
        self.assertContains(r, "Record a service")
        self.assertNotContains(r, "25,000")
