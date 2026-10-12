"""Sending a sale memo to the buyer on WhatsApp."""
from datetime import date
from decimal import Decimal as D
from urllib.parse import unquote

from django.test import TestCase
from django.urls import reverse

from apps.business.core.models import Unit
from apps.business.core.testing import make_farm
from apps.business.markets.models import DeductionMethod, DeductionType
from apps.business.parties.models import Party
from apps.business.species.models import Species

from .models import FishSale, FishSaleLine, SaleDeduction


class SaleMemoTests(TestCase):
    def setUp(self):
        self.b, self.owner, _ = make_farm()
        self.client.force_login(self.owner)
        self.buyer = Party.objects.create(business=self.b, name="Karim Paikar", phone="01711-223344", is_buyer=True)
        self.sale = FishSale.objects.create(business=self.b, date=date(2026, 10, 5), buyer=self.buyer, memo_no="17", received_now=D("20000"))
        FishSaleLine.objects.create(business=self.b, sale=self.sale, species=Species.objects.get(business=self.b, name="Rui"),
                                    quantity=D("100"), unit=Unit.objects.get(business=self.b, symbol="kg"), rate=D("250"))
        kind = DeductionType.objects.filter(business=self.b).first()
        SaleDeduction.objects.create(business=self.b, sale=self.sale, deduction_type=kind, method=DeductionMethod.PERCENT, value=D("4"))
        self.sale.recalc()

    def link(self):
        r = self.client.get(reverse("business:sale_detail", args=[self.sale.pk]))
        return r, r.context["wa"]

    def test_memo_goes_to_the_buyers_number(self):
        r, wa = self.link()
        self.assertTrue(wa.startswith("https://wa.me/8801711223344?text="))
        text = unquote(wa.split("text=", 1)[1])
        self.assertIn("5 Oct 2026 · #17", text)
        self.assertIn("Rui: 100 kg × ৳250 = ৳25,000", text)
        self.assertIn("Net: ৳24,000", text)
        self.assertIn("Paid at the sale: ৳20,000", text)
        self.assertIn("Still to pay: ৳4,000", text)
        self.assertContains(r, "Send to buyer")

    def test_without_a_number_whatsapp_asks_who(self):
        Party.objects.filter(pk=self.buyer.pk).update(phone="")
        r, wa = self.link()
        self.assertTrue(wa.startswith("https://wa.me/?text="))
        self.assertNotContains(r, "Send to buyer")

    def test_a_deleted_sale_has_no_memo_to_send(self):
        self.sale.soft_delete()
        _, wa = self.link()
        self.assertIsNone(wa)
