"""Shop categories: the same editable list as creditors' (apps.core.people_categories), with the shops' starters."""
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from ..models import DefaultShopCategory, Shop, ShopCategory


def mine(user):
    return ShopCategory.objects.filter(user=user)


class ShopCategoryTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("rina", password="pw-12345!")
        self.client.force_login(self.user)

    def test_starters_other_and_the_plus(self):
        r = self.client.get(reverse("shop_create"))
        self.assertEqual(sorted(mine(self.user).values_list("code", flat=True)), sorted(DefaultShopCategory.values))
        field = r.context["form"].fields["category"]
        self.assertEqual((field.quick_add, r.context["form"].initial["category"]), ("shop_category", mine(self.user).get(code="OTHER").pk))
        self.assertIn(reverse("shop_categories"), str(field.help_text))
        self.assertEqual(Shop.objects.create(user=self.user, name="Corner").category.code, "OTHER")

    def test_add_with_plus_then_use_it_and_filter_by_it(self):
        self.client.get(reverse("shop_create"))                                 # the + sits on this form
        r = self.client.post(reverse("quick_create", args=["shop_category"]), {"qa_shop_category-name": "Fish market"})
        fish = mine(self.user).get(pk=r.json()["id"])
        self.client.post(reverse("shop_create"), {"name": "Karim Fish", "category": fish.pk})
        Shop.objects.create(user=self.user, name="Medicine Corner", category=mine(self.user).get(code="PHARMACY"))
        page = lambda **p: [s.name for s in self.client.get(reverse("shop_list"), p).context["page_obj"]]
        self.assertEqual(page(category=fish.pk), ["Karim Fish"])
        self.assertEqual(page(category="PHARMACY"), ["Medicine Corner"])        # an old link
        self.assertEqual(page(category=fish.pk, filter_type="exclude"), ["Medicine Corner"])

    def test_old_code_in_a_form_and_csv(self):
        self.client.post(reverse("shop_create"), {"name": "Bread", "category": "BAKERY"})
        self.assertEqual(Shop.objects.get(name="Bread").category.code, "BAKERY")
        f = SimpleUploadedFile("s.csv", b"Name,Category\nRahim Store,Grocery\nTailor Joy,Tailor\nNo cat,\n", content_type="text/csv")
        self.client.post(reverse("shop_import"), {"csv_file": f})
        got = {s.name: s.category.name for s in Shop.objects.filter(user=self.user)}
        self.assertEqual({k: got[k] for k in ("Rahim Store", "Tailor Joy", "No cat")}, {"Rahim Store": "Grocery", "Tailor Joy": "Tailor", "No cat": "Other"})

    def test_categories_page(self):
        self.assertContains(self.client.get(reverse("shop_categories")), "Shop categories")
        grocery = mine(self.user).get(code="GROCERY")
        Shop.objects.create(user=self.user, name="Rahim Store", category=grocery)
        self.client.post(reverse("shop_categories"), {"action": "rename", "pk": grocery.pk, "name": "Mudi dokan"})
        self.assertContains(self.client.get(reverse("shop_list")), "Mudi dokan")
        self.client.post(reverse("shop_categories"), {"action": "delete", "pk": grocery.pk})
        self.assertTrue(mine(self.user).filter(pk=grocery.pk).exists())          # in use: kept
        self.assertContains(self.client.get(reverse("shop_categories")), "1 shop")
