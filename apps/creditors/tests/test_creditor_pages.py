"""The creditor pages: where Edit goes back to, same-name protection, the
running balance, receipt photos, search, the CSV files, and one-tap amounts."""
import shutil
import tempfile
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.plans.models import InstallmentPlan
from apps.wallets.models import Wallet

from ..models import Creditor, CreditorCategory, Transaction

MEDIA = tempfile.mkdtemp()
PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
       b"\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82")


def csv_file(text):
    return SimpleUploadedFile("people.csv", text.encode("utf-8"), content_type="text/csv")


@override_settings(MEDIA_ROOT=MEDIA)
class CreditorPageTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        self.user = User.objects.create_user("me", password="pw12345!")
        self.client.force_login(self.user)
        self.today = timezone.localdate()
        self.karim = Creditor.objects.create(user=self.user, name="Karim", phone="01711000000", note="from the market",
                                             category=CreditorCategory.FRIEND)

    def entry(self, kind, amount, days_ago=0, **extra):
        return Transaction.objects.create(creditor=self.karim, transaction_type=kind, amount=Decimal(amount),
                                          date=self.today - timedelta(days=days_ago), **extra)

    # ── Edit goes back to the person ──

    def test_saving_the_profile_returns_to_the_creditors_page(self):
        url = reverse("creditor_edit", args=[self.karim.pk])
        detail = reverse("creditor_detail", args=[self.karim.pk])
        self.assertEqual(self.client.get(url).context["back_url"], detail)
        r = self.client.post(url, {"name": "Karim", "category": CreditorCategory.FRIEND, "phone": "01811000000"})
        self.assertRedirects(r, detail)

    # ── Same name ──

    def test_a_second_creditor_with_the_same_name_is_refused(self):
        r = self.client.post(reverse("creditor_create"), {"name": "  karim ", "category": CreditorCategory.OTHER})
        self.assertEqual(r.status_code, 200)
        self.assertIn("name", r.context["form"].errors)
        self.assertEqual(Creditor.objects.filter(user=self.user).count(), 1)

    def test_the_same_name_is_fine_for_someone_else_and_when_editing_yourself(self):
        other = User.objects.create_user("other", password="pw12345!")
        Creditor.objects.create(user=other, name="Rahim")
        r = self.client.post(reverse("creditor_create"), {"name": "Rahim", "category": CreditorCategory.OTHER})
        self.assertEqual(r.status_code, 302)
        r = self.client.post(reverse("creditor_edit", args=[self.karim.pk]), {"name": "KARIM", "category": CreditorCategory.FRIEND})
        self.assertEqual(r.status_code, 302)

    # ── Running balance, wallet, receipts ──

    def test_each_entry_shows_what_was_owed_after_it_even_when_filtered(self):
        self.entry(Transaction.BORROW, "5000", days_ago=400)
        self.entry(Transaction.REPAY, "1000", days_ago=10)
        last = self.entry(Transaction.REPAY, "500", days_ago=1)
        year = (self.today - timedelta(days=1)).year
        r = self.client.get(reverse("creditor_detail", args=[self.karim.pk]) + f"?year={year}")
        rows = {tx.pk: tx.balance_after for tx in r.context["transactions"]}
        self.assertEqual(rows[last.pk], Decimal("3500"))
        self.assertContains(r, "You owed ৳3,500 after this")

    def test_paying_too_much_is_said_without_a_minus_sign(self):
        self.entry(Transaction.BORROW, "1000", days_ago=5)
        self.entry(Transaction.REPAY, "1500", days_ago=1)
        r = self.client.get(reverse("creditor_detail", args=[self.karim.pk]))
        self.assertContains(r, "Paid ৳500 too much after this")
        self.assertNotContains(r, "Paid −৳500")

    def test_a_receipt_can_be_added_to_a_loan_and_only_its_owner_sees_it(self):
        url = reverse("creditor_detail", args=[self.karim.pk])
        photo = SimpleUploadedFile("slip.png", PNG, content_type="image/png")
        r = self.client.post(url, {"transaction_type": Transaction.BORROW, "amount": "2000", "date": self.today.isoformat(), "receipt": photo})
        self.assertEqual(r.status_code, 302)
        tx = Transaction.objects.get()
        self.assertTrue(tx.receipt.name.startswith(f"receipts/{self.user.pk}/"))
        view = reverse("receipt_view", args=["loan", tx.pk])
        self.assertContains(self.client.get(url), view)
        self.assertEqual(self.client.get(view).status_code, 200)
        self.client.force_login(User.objects.create_user("them", password="pw12345!"))
        self.assertEqual(self.client.get(view).status_code, 404)

    def test_paying_back_from_a_wallet_that_cannot_cover_it_warns(self):
        bkash = Wallet.objects.create(user=self.user, name="bKash", opening_balance=Decimal("1000"), opening_date=self.today - timedelta(days=5))
        self.entry(Transaction.BORROW, "5000", days_ago=3)
        r = self.client.post(reverse("creditor_detail", args=[self.karim.pk]),
                             {"transaction_type": Transaction.REPAY, "amount": "3000", "wallet": bkash.pk, "date": self.today.isoformat()}, follow=True)
        self.assertContains(r, "less than nothing")
        self.assertEqual(Transaction.objects.filter(transaction_type=Transaction.REPAY).count(), 1)   # saved all the same

    def test_the_wallet_picker_shows_each_balance(self):
        Wallet.objects.create(user=self.user, name="Cash", opening_balance=Decimal("2500"))
        self.assertContains(self.client.get(reverse("creditor_detail", args=[self.karim.pk])), "Cash · ৳2,500")

    # ── One-tap amounts ──

    def test_a_link_can_fill_in_the_kind_and_amount(self):
        r = self.client.get(reverse("creditor_detail", args=[self.karim.pk]) + "?record=REPAY&amount=1500.5")
        initial = r.context["form"].initial
        self.assertEqual((initial["transaction_type"], initial["amount"]), ("REPAY", Decimal("1500.50")))
        for bad in ("-5", "abc", "1e40", "nan"):
            r = self.client.get(reverse("creditor_detail", args=[self.karim.pk]) + f"?amount={bad}")
            self.assertNotIn("amount", r.context["form"].initial, bad)

    def test_the_form_offers_the_whole_balance_and_the_next_installment(self):
        self.entry(Transaction.BORROW, "6000", days_ago=40)
        InstallmentPlan.objects.create(user=self.user, creditor=self.karim, amount=Decimal("1000"), start_date=self.today + timedelta(days=5))
        r = self.client.get(reverse("creditor_detail", args=[self.karim.pk]))
        self.assertContains(r, 'data-pay-amount="6000.00"')
        self.assertContains(r, 'data-pay-amount="1000.00"')
        self.assertContains(r, "?record=REPAY&amp;amount=1000.00#record")

    # ── Search and CSV ──

    def test_search_finds_a_phone_number_or_a_word_in_the_note(self):
        Creditor.objects.create(user=self.user, name="Someone else")
        for q in ("01711", "0171 1000", "market"):
            names = [c.name for c in self.client.get(reverse("creditor_list"), {"q": q}).context["page_obj"]]
            self.assertEqual(names, ["Karim"], q)

    def test_the_list_export_carries_phone_and_due_date(self):
        self.karim.due_date = date(2026, 12, 31)
        self.karim.save()
        body = self.client.get(reverse("creditor_list") + "?export=csv").content.decode("utf-8-sig")
        self.assertIn("Phone,Due date", body.splitlines()[0])
        self.assertIn("01711000000,2026-12-31", body)

    def test_import_reads_dates_and_says_which_amounts_it_could_not_read(self):
        text = ("Name,Phone,Opening Balance,Date,Due date\n"
                "Rafi,017,\"2,500\",15/01/2025,2026-12-01\n"
                "Mitu,018,lots,,\n"
                "Joy,019,100,someday,\n"
                "Karim,,50,,\n")
        r = self.client.post(reverse("creditor_import"), {"csv_file": csv_file(text)}, follow=True)
        msgs = " ".join(str(m) for m in r.context["messages"])
        self.assertIn("Imported 3 creditor(s).", msgs)
        self.assertIn("Row 3: “lots” isn't an amount", msgs)
        self.assertIn("Row 4: “someday” isn't a date", msgs)
        self.assertIn("1 duplicate name(s)", msgs)
        rafi = Creditor.objects.get(user=self.user, name="Rafi")
        self.assertEqual(rafi.due_date, date(2026, 12, 1))
        self.assertEqual(list(rafi.transactions.values_list("amount", "date")), [(Decimal("2500.00"), date(2025, 1, 15))])
        self.assertFalse(Creditor.objects.get(user=self.user, name="Mitu").transactions.exists())
        self.assertEqual(Creditor.objects.get(user=self.user, name="Joy").transactions.get().date, self.today)

    def test_the_import_template_shows_the_new_columns(self):
        header = self.client.get(reverse("creditor_import_template")).content.decode("utf-8-sig").splitlines()[0]
        self.assertTrue(header.endswith("Opening Balance,Date,Due date"))
