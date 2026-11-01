"""Download my data, the stocking guide and the fish health guide."""
import io
import zipfile
from datetime import date, timedelta
from decimal import Decimal as D

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from apps.business.core.models import Unit
from apps.business.core.testing import make_farm
from apps.business.ponds.models import CultureCycle, Pond, Stocking
from apps.business.species.models import Species
from apps.creditors.models import Creditor

TODAY = date.today()


class MyDataTests(TestCase):
    def test_only_my_records(self):
        me = User.objects.create_user("me", password="pw12345!")
        other = User.objects.create_user("other", password="pw12345!")
        Creditor.objects.create(user=me, name="Karim Uddin")
        Creditor.objects.create(user=other, name="Secret Person")
        self.client.force_login(me)
        r = self.client.get(reverse("my_data"))
        self.assertEqual(r["Content-Type"], "application/zip")
        z = zipfile.ZipFile(io.BytesIO(r.content))
        text = z.read("creditors-creditor.csv").decode("utf-8-sig")
        self.assertIn("Karim Uddin", text)
        self.assertNotIn("Secret Person", text)
        self.assertIn("README.txt", z.namelist())

    def test_needs_login(self):
        self.assertEqual(self.client.get(reverse("my_data")).status_code, 302)


class StockingGuideTests(TestCase):
    def setUp(self):
        self.b, self.owner, _ = make_farm()
        self.client.force_login(self.owner)
        dec = Unit.objects.get(business=self.b, symbol="dec")
        self.rui = Species.objects.get(business=self.b, name="Rui")
        self.pond = Pond.objects.create(business=self.b, name="East", area=D("50"), area_unit=dec)
        self.cycle = CultureCycle.objects.create(business=self.b, pond=self.pond, start_date=TODAY - timedelta(days=10))

    def test_seeded_guide(self):
        self.assertEqual(self.rui.stock_per_decimal, 10)
        self.assertEqual(Species.objects.get(business=self.b, name="Pangas").stock_per_decimal, 120)

    def test_form_suggests_and_page_warns_when_crowded(self):
        r = self.client.get(reverse("business:cycle_detail", args=[self.cycle.pk]))
        self.assertContains(r, "data-stock-hint")
        self.assertContains(r, "about 500 Rui")               # 50 decimal × 10
        Stocking.objects.create(business=self.b, cycle=self.cycle, date=TODAY, species=self.rui, count=2000)   # 40 per decimal
        r = self.client.get(reverse("business:cycle_detail", args=[self.cycle.pk]))
        self.assertContains(r, "40 per decimal")
        self.assertContains(r, "Crowded ponds run short of oxygen")

    def test_species_form_has_the_field(self):
        self.assertContains(self.client.get(reverse("business:species_edit", args=[self.rui.pk])), "stock_per_decimal")


class HealthGuideTests(TestCase):
    def test_page_and_links(self):
        b, owner, staff = make_farm()
        self.client.force_login(staff)
        r = self.client.get(reverse("business:fish_health") + "?p=oxygen")
        self.assertContains(r, "Low oxygen")
        self.assertContains(r, 'id="oxygen" open')
        self.assertContains(r, "not a prescription")
        pond = Pond.objects.create(business=b, name="East")
        cycle = CultureCycle.objects.create(business=b, pond=pond, start_date=TODAY)
        self.assertContains(self.client.get(reverse("business:cycle_detail", args=[cycle.pk])), reverse("business:fish_health"))
