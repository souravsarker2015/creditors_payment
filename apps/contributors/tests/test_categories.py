"""Contributor categories: the same editable list as creditors' (apps.core.people_categories), with the contributors' starters."""
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from ..models import Contributor, ContributorCategory, DefaultContributorCategory


def mine(user):
    return ContributorCategory.objects.filter(user=user)


class ContributorCategoryTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("rina", password="pw-12345!")
        self.client.force_login(self.user)

    def test_starters_other_and_the_plus(self):
        r = self.client.get(reverse("contributor_create"))
        self.assertEqual(sorted(mine(self.user).values_list("code", flat=True)), sorted(DefaultContributorCategory.values))
        field = r.context["form"].fields["category"]
        self.assertEqual((field.quick_add, r.context["form"].initial["category"]), ("contributor_category", mine(self.user).get(code="OTHER").pk))
        self.assertIn(reverse("contributor_categories"), str(field.help_text))
        self.assertEqual(Contributor.objects.create(user=self.user, name="Brother").category.code, "OTHER")

    def test_add_with_plus_then_use_it_and_filter_by_it(self):
        self.client.get(reverse("contributor_create"))                                 # the + sits on this form
        r = self.client.post(reverse("quick_create", args=["contributor_category"]), {"qa_contributor_category-name": "Old classmates"})
        mates = mine(self.user).get(pk=r.json()["id"])
        self.client.post(reverse("contributor_create"), {"name": "Rana", "category": mates.pk})
        Contributor.objects.create(user=self.user, name="Aunt Hena", category=mine(self.user).get(code="RELATIVE"))
        page = lambda **p: [s.name for s in self.client.get(reverse("contributor_list"), p).context["page_obj"]]
        self.assertEqual(page(category=mates.pk), ["Rana"])
        self.assertEqual(page(category="RELATIVE"), ["Aunt Hena"])        # an old link
        self.assertEqual(page(category=mates.pk, filter_type="exclude"), ["Aunt Hena"])

    def test_old_code_in_a_form_and_csv(self):
        self.client.post(reverse("contributor_create"), {"name": "Mosque fund", "category": "DONOR"})
        self.assertEqual(Contributor.objects.get(name="Mosque fund").category.code, "DONOR")
        f = SimpleUploadedFile("s.csv", b"Name,Category\nAbul Store,Friend\nTailor Joy,Classmate\nNo cat,\n", content_type="text/csv")
        self.client.post(reverse("contributor_import"), {"csv_file": f})
        got = {s.name: s.category.name for s in Contributor.objects.filter(user=self.user)}
        self.assertEqual({k: got[k] for k in ("Abul Store", "Tailor Joy", "No cat")}, {"Abul Store": "Friend", "Tailor Joy": "Classmate", "No cat": "Other"})

    def test_categories_page(self):
        self.assertContains(self.client.get(reverse("contributor_categories")), "Contributor categories")
        grocery = mine(self.user).get(code="FAMILY")
        Contributor.objects.create(user=self.user, name="Abul", category=grocery)
        self.client.post(reverse("contributor_categories"), {"action": "rename", "pk": grocery.pk, "name": "Kin"})
        self.assertContains(self.client.get(reverse("contributor_list")), "Kin")
        self.client.post(reverse("contributor_categories"), {"action": "delete", "pk": grocery.pk})
        self.assertTrue(mine(self.user).filter(pk=grocery.pk).exists())          # in use: kept
        self.assertContains(self.client.get(reverse("contributor_categories")), "1 contributor")
