"""A photo of the paper memo on a sale or feed purchase, and the sale form's
warning when fish are sold below what they cost to grow."""
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse

from apps.business.core.models import Membership, Role
from apps.business.core.testing import make_farm
from apps.business.feed.models import FeedPurchase
from apps.business.ponds.tests_wait import WaitBase, ago

from .models import FishSale

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f"
       b"\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82")
MEDIA = tempfile.mkdtemp()


def memo(name="memo.png"):
    return SimpleUploadedFile(name, PNG, content_type="image/png")


@override_settings(MEDIA_ROOT=MEDIA)
class MemoPhotoTests(WaitBase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def test_sale_memo_photo(self):
        sale = FishSale.objects.create(business=self.b, date=ago(1))
        url = reverse("business:sale_edit", args=[sale.pk])
        self.assertContains(self.client.get(url), 'enctype="multipart/form-data"')
        form = self.client.get(url).context["form"]
        data = {k: v for k, v in form.initial.items() if v is not None}
        data.update({"date": ago(1).isoformat(), "lines-TOTAL_FORMS": "1", "lines-INITIAL_FORMS": "0", "deds-TOTAL_FORMS": "0", "deds-INITIAL_FORMS": "0",
                     "lines-0-species": self.rui.pk, "lines-0-quantity": "10", "lines-0-unit": self.kg.pk, "lines-0-rate": "200",
                     "received_now": "2000", "account": "", "receipt": memo()})
        r = self.client.post(url, data)
        self.assertRedirects(r, reverse("business:sale_detail", args=[sale.pk]))
        sale.refresh_from_db()
        self.assertTrue(sale.receipt.name.startswith(f"business/{self.b.pk}/memos/"))
        self.assertNotIn("memo.png", sale.receipt.name)                    # random name, not the phone's
        self.assertContains(self.client.get(reverse("business:sale_detail", args=[sale.pk])), "data-memo-photo")
        view = reverse("receipt_view", args=["sale", sale.pk])
        self.assertEqual(self.client.get(view)["Content-Type"], "image/png")
        self.client.force_login(self.staff)                                 # the farm's data-entry person may see it too
        self.assertEqual(self.client.get(view).status_code, 200)
        _b, stranger, _s = make_farm("other")
        self.client.force_login(stranger)                                   # another farm may not
        self.assertEqual(self.client.get(view).status_code, 404)

    def test_feed_memo_photo_and_wrong_file(self):
        buy = FeedPurchase.objects.get(business=self.b)
        url = reverse("business:feed_purchases_edit", args=[buy.pk])
        self.assertContains(self.client.get(url), 'name="receipt"')
        FeedPurchase.objects.filter(pk=buy.pk).update(receipt=f"business/{self.b.pk}/memos/x.png")
        self.assertContains(self.client.get(reverse("business:feed_purchases")), reverse("receipt_view", args=["feed", buy.pk]))
        self.assertContains(self.client.get(url), "See the memo")
        from apps.business.feed.forms import FeedPurchaseForm

        form = FeedPurchaseForm({"supplier": buy.supplier_id, "date": ago(1).isoformat()}, {"receipt": SimpleUploadedFile("a.exe", b"MZ")},
                                instance=buy, business=self.b)
        self.assertIn("receipt", form.errors)


class BreakEvenTests(WaitBase):
    def setUp(self):
        super().setUp()
        self.weigh(0, "400")     # 900 fish × 400 g = 360 kg in the pond

    def evens(self):
        return self.client.get(reverse("business:sale_add")).context["break_evens"]

    def test_price_the_fish_must_fetch(self):
        # ৳3,000 fingerlings + 500 kg feed at ৳50 = ৳28,000 to cover with 360 kg → ৳77.78/kg
        self.assertEqual(self.evens(), {str(self.cycle.pk): "77.78"})
        self.assertContains(self.client.get(reverse("business:sale_add")), "data-break-even")

    def test_not_shown_to_people_who_cant_see_money(self):
        Membership.objects.filter(user=self.staff).update(role=Role.DATA_ENTRY)
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse("business:sale_add")).context["break_evens"], {})
