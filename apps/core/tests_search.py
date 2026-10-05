"""Search everything: personal and farm records, only what the person may see."""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from apps.business.core.testing import make_farm
from apps.business.partners.models import Partner
from apps.business.ponds.models import Pond
from apps.creditors.models import Creditor


class SearchTests(TestCase):
    def setUp(self):
        self.b, self.owner, self.staff = make_farm()
        self.client.force_login(self.owner)

    def find(self, q, **headers):
        return self.client.get(reverse("search"), {"q": q}, **headers)

    def test_personal_people_by_name_and_bangla_digits(self):
        Creditor.objects.create(user=self.owner, name="Karim Uddin", phone="01711223344")
        self.assertContains(self.find("karim"), "Karim Uddin")
        self.assertContains(self.find("০১৭১১২২"), "Karim Uddin")

    def test_only_your_own_records(self):
        other = User.objects.create_user("them", password="pw12345!")
        Creditor.objects.create(user=other, name="Secret Lender")
        self.assertNotContains(self.find("secret"), "Secret Lender")

    def test_farm_records_and_pages(self):
        Pond.objects.create(business=self.b, name="East pond")
        r = self.find("east")
        self.assertContains(r, "East pond")
        self.assertContains(r, reverse("business:pond_detail", args=[Pond.objects.get().pk]))
        self.assertContains(self.find("feed plan"), reverse("business:feed_plan"))

    def test_staff_do_not_find_money_records(self):
        Partner.objects.create(business=self.b, name="Halim Partner", share_pct=50)
        self.assertContains(self.find("halim"), "Halim Partner")
        self.client.force_login(self.staff)
        r = self.find("halim")
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, "Halim Partner")
        self.assertNotContains(self.find("profit sharing"), reverse("business:partner_sharing"))

    def test_live_results_and_short_queries(self):
        Creditor.objects.create(user=self.owner, name="Karim")
        r = self.find("kar", HTTP_HX_REQUEST="true")
        self.assertContains(r, 'id="search-results"')
        self.assertNotContains(r, "<html")
        self.assertContains(self.find("k"), "at least 2 letters")

    def test_search_box_is_on_every_page(self):
        self.assertContains(self.client.get(reverse("networth")), 'id="global-search-q"')
        self.assertContains(self.client.get(reverse("business:home")), 'id="global-search-q"')
