"""Debtor pages: Edit returns to the person, receipts, running balance, import."""
from datetime import timedelta
from decimal import Decimal as D

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from ..models import Debtor, DebtorCategory, Transaction


class DebtorPageTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("me", password="pw12345!")
        self.client.force_login(self.user)
        self.today = timezone.localdate()
        self.rafi = Debtor.objects.create(user=self.user, name="Rafi", phone="01911000000")

    def test_edit_returns_to_the_debtor(self):
        url = reverse("debtor_edit", args=[self.rafi.pk])
        r = self.client.post(url, {"name": "Rafi", "category": DebtorCategory.FRIEND})
        self.assertRedirects(r, reverse("debtor_detail", args=[self.rafi.pk]))

    def test_same_name_is_refused(self):
        r = self.client.post(reverse("debtor_create"), {"name": "RAFI", "category": DebtorCategory.FRIEND})
        self.assertIn("name", r.context["form"].errors)

    def test_running_balance_and_wallet_on_each_entry(self):
        Transaction.objects.create(debtor=self.rafi, transaction_type=Transaction.LEND, amount=D("4000"), date=self.today - timedelta(days=5))
        got = Transaction.objects.create(debtor=self.rafi, transaction_type=Transaction.RECEIVE, amount=D("1500"), date=self.today)
        r = self.client.get(reverse("debtor_detail", args=[self.rafi.pk]))
        self.assertEqual({t.pk: t.balance_after for t in r.context["transactions"]}[got.pk], D("2500"))
        self.assertContains(r, "They owed you ৳2,500 after this")
        self.assertContains(r, 'data-pay-type="RECEIVE"')

    def test_search_by_phone(self):
        Debtor.objects.create(user=self.user, name="Other")
        names = [d.name for d in self.client.get(reverse("debtor_list"), {"q": "0191"}).context["page_obj"]]
        self.assertEqual(names, ["Rafi"])

    def test_import_with_dates(self):
        text = "Name,Opening Balance,Date,Due date\nMitu,700,2025-03-01,01/12/2026\n"
        self.client.post(reverse("debtor_import"), {"csv_file": SimpleUploadedFile("d.csv", text.encode(), content_type="text/csv")})
        mitu = Debtor.objects.get(user=self.user, name="Mitu")
        self.assertEqual(mitu.due_date.isoformat(), "2026-12-01")
        self.assertEqual(mitu.transactions.get().date.isoformat(), "2025-03-01")
