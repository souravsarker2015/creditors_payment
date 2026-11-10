"""Shop pages: Edit returns to the shop, the memo photo, running balance."""
import shutil
import tempfile
from decimal import Decimal as D

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from ..models import Shop, ShopCategory, Transaction

MEDIA = tempfile.mkdtemp()
PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
       b"\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82")


@override_settings(MEDIA_ROOT=MEDIA)
class ShopPageTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        self.user = User.objects.create_user("me", password="pw12345!")
        self.client.force_login(self.user)
        self.shop = Shop.objects.create(user=self.user, name="Mayer Doa Store")

    def test_edit_returns_to_the_shop(self):
        r = self.client.post(reverse("shop_edit", args=[self.shop.pk]), {"name": "Mayer Doa Store", "category": ShopCategory.OTHER})
        self.assertRedirects(r, reverse("shop_detail", args=[self.shop.pk]))

    def test_a_memo_photo_on_a_purchase(self):
        url = reverse("shop_detail", args=[self.shop.pk])
        r = self.client.post(url, {"transaction_type": Transaction.PURCHASE, "amount": "850", "date": timezone.localdate().isoformat(),
                                   "receipt": SimpleUploadedFile("memo.png", PNG, content_type="image/png")})
        self.assertEqual(r.status_code, 302)
        tx = Transaction.objects.get()
        view = reverse("receipt_view", args=["shop", tx.pk])
        page = self.client.get(url)
        self.assertContains(page, view)
        self.assertContains(page, "Due ৳850 after this")
        self.assertEqual(self.client.get(view).status_code, 200)
        r = self.client.get(reverse("shop_transaction_edit", args=[tx.pk]))
        self.assertContains(r, 'enctype="multipart/form-data"')
        self.assertContains(r, view)
