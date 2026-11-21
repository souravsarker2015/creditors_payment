"""Debtor categories: the same editable list as creditors' (apps.core.people_categories), with the debtors' starters."""
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from apps.core.people_categories import ensure_starters

from ..models import Debtor, DebtorCategory, DefaultDebtorCategory


def mine(user):
    return DebtorCategory.objects.filter(user=user)


class DebtorCategoryTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("rina", password="pw-12345!")
        self.client.force_login(self.user)

    def test_starters_other_and_the_plus(self):
        r = self.client.get(reverse("debtor_create"))
        self.assertEqual(sorted(mine(self.user).values_list("code", flat=True)), sorted(DefaultDebtorCategory.values))
        field = r.context["form"].fields["category"]
        self.assertEqual((field.quick_add, r.context["form"].initial["category"]), ("debtor_category", mine(self.user).get(code="OTHER").pk))
        self.assertEqual(Debtor.objects.create(user=self.user, name="Rafi").category.code, "OTHER")

    def test_add_with_plus_then_use_it_and_filter_by_it(self):
        self.client.get(reverse("debtor_create"))                               # the + sits on this form
        r = self.client.post(reverse("quick_create", args=["debtor_category"]), {"qa_debtor_category-name": "Cousin"})
        cousin = mine(self.user).get(pk=r.json()["id"])
        self.client.post(reverse("debtor_create"), {"name": "Mitu", "category": cousin.pk})
        Debtor.objects.create(user=self.user, name="Rafi", category=mine(self.user).get(code="CLIENT"))
        page = lambda **p: [d.name for d in self.client.get(reverse("debtor_list"), p).context["page_obj"]]
        self.assertEqual(page(category=cousin.pk), ["Mitu"])
        self.assertEqual(page(category="CLIENT"), ["Rafi"])                    # an old link
        self.assertEqual(page(category=cousin.pk, filter_type="exclude"), ["Rafi"])

    def test_old_code_in_a_form_and_csv(self):
        self.client.post(reverse("debtor_create"), {"name": "Sumi", "category": "TENANT"})
        self.assertEqual(Debtor.objects.get(name="Sumi").category.code, "TENANT")
        f = SimpleUploadedFile("d.csv", b"Name,Category\nKarim,Client\nJoy,Cousin\nAbu,\n", content_type="text/csv")
        self.client.post(reverse("debtor_import"), {"csv_file": f})
        got = {d.name: d.category.name for d in Debtor.objects.filter(user=self.user)}
        self.assertEqual({k: got[k] for k in ("Karim", "Joy", "Abu")}, {"Karim": "Client", "Joy": "Cousin", "Abu": "Other"})

    def test_categories_page(self):
        r = self.client.get(reverse("debtor_categories"))
        self.assertContains(r, "Debtor categories")
        client = mine(self.user).get(code="CLIENT")
        Debtor.objects.create(user=self.user, name="Rafi", category=client)
        self.client.post(reverse("debtor_categories"), {"action": "rename", "pk": client.pk, "name": "Customer"})
        self.assertContains(self.client.get(reverse("debtor_list")), "Customer")
        self.client.post(reverse("debtor_categories"), {"action": "delete", "pk": client.pk})
        self.assertTrue(mine(self.user).filter(pk=client.pk).exists())          # in use: kept
