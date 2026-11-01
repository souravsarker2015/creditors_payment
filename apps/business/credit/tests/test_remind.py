"""Reminding people about baki: SMS links, the reminder round, and "reminded today"."""
from datetime import date, timedelta
from decimal import Decimal as D
from urllib.parse import unquote

from django.test import TestCase
from django.urls import reverse

from apps.business.core.testing import make_farm
from apps.business.parties.models import Party
from apps.business.sales.models import FishSale


class RemindTests(TestCase):
    def setUp(self):
        self.b, self.owner, self.staff = make_farm()
        self.client.force_login(self.owner)
        self.karim = Party.objects.create(business=self.b, name="Karim", phone="01711-000111", is_buyer=True,
                                          opening_balance=D("5000"), opening_type="receivable", opening_date=date.today() - timedelta(days=40))
        self.habib = Party.objects.create(business=self.b, name="Habib", is_buyer=True,          # no phone
                                          opening_balance=D("2000"), opening_type="receivable", opening_date=date.today() - timedelta(days=10))
        self.dealer = Party.objects.create(business=self.b, name="Dealer", phone="01811000222", is_supplier=True,
                                           opening_balance=D("9000"), opening_type="payable")     # we owe them: no reminder

    def test_sms_link_on_the_list_and_the_statement(self):
        r = self.client.get(reverse("business:dues"))
        self.assertContains(r, "Remind 1 person")
        self.assertContains(r, "sms:+8801711000111?&amp;body=")
        body = unquote(r.content.decode().split("sms:+8801711000111?&amp;body=")[1].split('"')[0])
        self.assertIn("৳5,000", body)
        self.assertIn(self.b.name, body)
        self.assertLessEqual(len(body), 140)
        r = self.client.get(reverse("business:party_statement", args=[self.karim.pk]))
        self.assertContains(r, "sms:+8801711000111")
        self.assertNotContains(self.client.get(reverse("business:party_statement", args=[self.dealer.pk])), "sms:")

    def test_reminder_round_and_marking_reminded(self):
        url = reverse("business:dues_remind")
        r = self.client.get(url)
        self.assertEqual([led.party for led in r.context["rows"]], [self.karim, self.habib])   # longest waiting first
        self.assertContains(r, "Add a phone number")
        self.assertNotContains(r, "Dealer")
        self.assertEqual(self.client.post(reverse("business:party_reminded", args=[self.karim.pk])).status_code, 204)
        self.karim.refresh_from_db()
        self.assertEqual(self.karim.reminded_on, date.today())
        r = self.client.get(url)
        self.assertEqual(r.context["done_today"], 1)
        self.assertEqual(r.context["rows"][-1].party, self.karim)                              # done: to the bottom
        self.assertContains(self.client.get(reverse("business:dues")), "reminded ")

    def test_only_this_farm_and_only_people_who_see_money(self):
        _b, stranger, _s = make_farm("other")
        self.client.force_login(stranger)
        self.client.post(reverse("business:party_reminded", args=[self.karim.pk]))
        self.karim.refresh_from_db()
        self.assertIsNone(self.karim.reminded_on)
        self.client.force_login(self.staff)                      # data entry can't see baki
        self.assertNotEqual(self.client.get(reverse("business:dues_remind")).status_code, 200)

    def test_sale_on_baki_shows_up_to_remind(self):
        FishSale.objects.create(business=self.b, date=date.today(), buyer=self.habib, net=D("1000"), gross=D("1000"))
        r = self.client.get(reverse("business:dues_remind"))
        self.assertEqual(next(led for led in r.context["rows"] if led.party == self.habib).amount, D("3000"))
