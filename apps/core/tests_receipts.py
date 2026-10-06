"""Receipt photos: upload, private viewing, and removal with "delete for good"."""
import shutil
import tempfile
from datetime import date
from decimal import Decimal as D

from django.contrib.auth.models import User
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.business.core.testing import make_farm
from apps.business.finance.models import Category, Transaction
from apps.expense.models import Expense, ExpenseCategory
from apps.household.models import Purchase

MEDIA = tempfile.mkdtemp()
PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
       b"\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82")


@override_settings(MEDIA_ROOT=MEDIA)
class ReceiptTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        self.user = User.objects.create_user("me", password="pw12345!")
        self.client.force_login(self.user)
        self.cat = ExpenseCategory.objects.create(user=self.user, name="Food")

    def photo(self, name="memo.png", size=None):
        return SimpleUploadedFile(name, PNG if size is None else b"x" * size, content_type="image/png")

    def test_upload_and_view_privately(self):
        r = self.client.post(reverse("expense_create"), {"category": self.cat.pk, "amount": "250", "date": date.today().isoformat(), "receipt": self.photo()})
        self.assertEqual(r.status_code, 302)
        e = Expense.objects.get()
        self.assertTrue(e.receipt.name.startswith(f"receipts/{self.user.pk}/"))
        url = reverse("receipt_view", args=["expense", e.pk])
        self.assertContains(self.client.get(reverse("expense_list")), url)
        r = self.client.get(url)
        self.assertEqual((r.status_code, r["Content-Type"]), (200, "image/png"))
        self.assertEqual(b"".join(r.streaming_content), PNG)
        self.client.force_login(User.objects.create_user("them", password="pw12345!"))
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_too_big_or_wrong_type_is_refused(self):
        r = self.client.post(reverse("expense_create"), {"category": self.cat.pk, "amount": "10", "date": date.today().isoformat(),
                                                         "receipt": self.photo(size=9 * 1024 * 1024)})
        self.assertContains(r, "too big")
        r = self.client.post(reverse("expense_create"), {"category": self.cat.pk, "amount": "10", "date": date.today().isoformat(),
                                                         "receipt": SimpleUploadedFile("x.exe", b"MZ", content_type="application/octet-stream")})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Expense.objects.exists())

    def test_edit_form_links_the_current_receipt(self):
        p = Purchase.objects.create(user=self.user, amount=D("90"), date=date.today(), receipt=self.photo())
        r = self.client.get(reverse("household_purchase_edit", args=[p.pk]))
        self.assertContains(r, reverse("receipt_view", args=["bazar", p.pk]))
        self.assertContains(r, 'data-shrink="1600"')

    def test_delete_for_good_removes_the_photo(self):
        e = Expense.objects.create(user=self.user, category=self.cat, amount=D("50"), date=date.today(), receipt=self.photo())
        path = e.receipt.name
        self.client.post(reverse("expense_delete", args=[e.pk]))
        self.assertTrue(default_storage.exists(path))                 # still there while it can be undone
        from apps.trash.models import DeletedItem

        self.client.post(reverse("trash_forget", args=[DeletedItem.objects.get().pk]))
        self.assertFalse(default_storage.exists(path))

    def test_farm_receipts_need_money_access(self):
        b, owner, staff = make_farm("farm")
        cat = Category.objects.filter(business=b, type="expense").first()
        t = Transaction.objects.create(business=b, date=date.today(), category=cat, amount=D("300"), receipt=self.photo())
        url = reverse("receipt_view", args=["farm", t.pk])
        self.client.force_login(owner)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertContains(self.client.get(reverse("business:transactions") + "?period=all"), url)
        self.client.force_login(staff)
        self.assertEqual(self.client.get(url).status_code, 404)
