"""Creditor categories are a list each person keeps: the familiar starters, plus any
they add with the + beside the dropdown, renamed, hidden or deleted on their page."""
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import translation

from apps.core.people_categories import ensure_starters

from ..models import Creditor, CreditorCategory, DefaultCreditorCategory, Transaction


def mine(user):
    return CreditorCategory.objects.filter(user=user)


class StartersTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("rina", password="pw-12345!")
        self.client.force_login(self.user)

    def test_a_new_account_gets_the_familiar_list_once(self):
        self.client.get(reverse("creditor_create"))
        self.assertEqual(sorted(mine(self.user).values_list("code", flat=True)), sorted(DefaultCreditorCategory.values))
        mine(self.user).exclude(code="OTHER").delete()                     # trimmed down to one…
        self.client.get(reverse("creditor_list"))
        self.assertEqual(list(mine(self.user).values_list("code", flat=True)), ["OTHER"])   # …stays trimmed

    def test_a_new_creditor_starts_in_other(self):
        r = self.client.get(reverse("creditor_create"))
        other = mine(self.user).get(code="OTHER")
        self.assertEqual(r.context["form"].initial["category"], other.pk)
        self.assertEqual(Creditor.objects.create(user=self.user, name="Karim").category, other)   # as the fixed list's default did

    def test_starters_follow_the_language_until_renamed(self):
        ensure_starters(CreditorCategory, self.user, Creditor.objects.none())
        family = mine(self.user).get(code="FAMILY")
        with translation.override("bn"):
            self.assertEqual(str(family), "পরিবার")
        family.name = "Relatives"
        family.save()
        with translation.override("bn"):
            self.assertEqual(str(family), "Relatives")


class FormTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("rina", password="pw-12345!")
        self.other = User.objects.create_user("someone", password="pw-12345!")
        self.client.force_login(self.user)
        ensure_starters(CreditorCategory, self.user, Creditor.objects.none())
        ensure_starters(CreditorCategory, self.other, Creditor.objects.none())

    def test_the_dropdown_is_my_list_with_a_plus(self):
        field = self.client.get(reverse("creditor_create")).context["form"].fields["category"]
        self.assertEqual(set(field.queryset), set(mine(self.user)))
        self.assertEqual(field.quick_add, "creditor_category")
        self.assertIn(reverse("creditor_categories"), str(field.help_text))

    def test_saving_with_one_of_mine(self):
        bank = mine(self.user).get(code="BANK")
        self.client.post(reverse("creditor_create"), {"name": "Sonali", "category": bank.pk})
        self.assertEqual(Creditor.objects.get(name="Sonali").category, bank)

    def test_someone_elses_category_is_refused(self):
        theirs = mine(self.other).get(code="BANK")
        r = self.client.post(reverse("creditor_create"), {"name": "Sonali", "category": theirs.pk})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Creditor.objects.filter(name="Sonali").exists())

    def test_an_old_page_or_offline_form_sending_the_old_code_still_works(self):
        self.client.post(reverse("creditor_create"), {"name": "Karim", "category": "FRIEND"})
        self.assertEqual(Creditor.objects.get(name="Karim").category, mine(self.user).get(code="FRIEND"))

    def test_a_hidden_category_isnt_offered_but_a_creditor_in_it_keeps_it(self):
        bank = mine(self.user).get(code="BANK")
        karim = Creditor.objects.create(user=self.user, name="Karim", category=bank)
        bank.is_active = False
        bank.save()
        self.assertNotIn(bank, self.client.get(reverse("creditor_create")).context["form"].fields["category"].queryset)
        self.assertIn(bank, self.client.get(reverse("creditor_edit", args=[karim.pk])).context["form"].fields["category"].queryset)


class QuickAddTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("rina", password="pw-12345!")
        self.client.force_login(self.user)
        ensure_starters(CreditorCategory, self.user, Creditor.objects.none())
        self.url = reverse("quick_create", args=["creditor_category"])

    def test_plus_adds_one_and_picks_it(self):
        r = self.client.post(self.url, {"qa_creditor_category-name": "  Neighbour "})
        self.assertEqual(r.status_code, 201)
        made = mine(self.user).get(name="Neighbour")
        self.assertEqual((r.json()["id"], r.json()["name"], made.code), (made.pk, "Neighbour", ""))

    def test_a_name_already_there_is_picked_not_doubled(self):
        family = mine(self.user).get(code="FAMILY")
        for typed in ("family", "পরিবার"):                       # also its Bangla name
            r = self.client.post(self.url, {"qa_creditor_category-name": typed})
            self.assertEqual((r.status_code, r.json()["id"]), (200, family.pk))
        self.assertEqual(mine(self.user).count(), len(DefaultCreditorCategory.values))


class CategoriesPageTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("rina", password="pw-12345!")
        self.client.force_login(self.user)
        self.url = reverse("creditor_categories")
        self.client.get(self.url)                                  # the starters are made on the first visit
        self.bank = mine(self.user).get(code="BANK")
        self.sonali = Creditor.objects.create(user=self.user, name="Sonali", category=self.bank)

    def post(self, **data):
        return self.client.post(self.url, data, follow=True)

    def test_add_rename_hide_and_delete(self):
        self.post(action="add", name="Neighbour")
        neighbour = mine(self.user).get(name="Neighbour")
        self.post(action="rename", pk=self.bank.pk, name="Banks & NGOs")
        self.assertContains(self.client.get(reverse("creditor_detail", args=[self.sonali.pk])), "Banks &amp; NGOs")
        self.post(action="toggle", pk=self.bank.pk)
        self.bank.refresh_from_db()
        self.assertFalse(self.bank.is_active)
        self.sonali.refresh_from_db()
        self.assertEqual(self.sonali.category, self.bank)            # hidden, not taken away
        self.post(action="delete", pk=neighbour.pk)
        self.assertFalse(mine(self.user).filter(pk=neighbour.pk).exists())

    def test_one_in_use_cant_be_deleted(self):
        r = self.post(action="delete", pk=self.bank.pk)
        self.assertTrue(mine(self.user).filter(pk=self.bank.pk).exists())
        self.assertContains(r, "still used")

    def test_no_twins(self):
        self.post(action="add", name="bank")
        self.post(action="rename", pk=mine(self.user).get(code="FAMILY").pk, name="BANK")
        self.assertEqual(mine(self.user).filter(name__iexact="bank").count(), 1)

    def test_someone_else_cant_touch_mine(self):
        intruder = User.objects.create_user("x", password="pw-12345!")
        self.client.force_login(intruder)
        self.post(action="delete", pk=mine(self.user).get(code="FAMILY").pk)
        self.post(action="rename", pk=self.bank.pk, name="Mine now")
        self.assertTrue(mine(self.user).filter(code="FAMILY").exists())
        self.bank.refresh_from_db()
        self.assertEqual(self.bank.name, "Bank")

    def test_the_page_shows_who_is_in_each(self):
        r = self.client.get(self.url)
        self.assertContains(r, f'href="{reverse("creditor_list")}?category={self.bank.pk}"')
        self.assertContains(r, "1 creditor")


class FilterTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("rina", password="pw-12345!")
        self.client.force_login(self.user)
        ensure_starters(CreditorCategory, self.user, Creditor.objects.none())
        self.mine_new = CreditorCategory.objects.create(user=self.user, name="Neighbour")
        Creditor.objects.create(user=self.user, name="Next door", category=self.mine_new)
        Creditor.objects.create(user=self.user, name="Uncle", category=mine(self.user).get(code="FAMILY"))

    def names(self, **params):
        return [c.name for c in self.client.get(reverse("creditor_list"), params).context["page_obj"]]

    def test_filter_by_my_own_category(self):
        self.assertEqual(self.names(category=self.mine_new.pk), ["Next door"])
        self.assertEqual(self.names(category=self.mine_new.pk, filter_type="exclude"), ["Uncle"])
        choices = dict(self.client.get(reverse("creditor_list")).context["category_choices"])
        self.assertEqual(choices[str(self.mine_new.pk)], "Neighbour")

    def test_an_old_link_with_a_code_still_filters(self):
        self.assertEqual(self.names(category="FAMILY"), ["Uncle"])

    def test_someone_elses_category_id_is_ignored(self):
        other = User.objects.create_user("x", password="pw-12345!")
        theirs = CreditorCategory.objects.create(user=other, name="Theirs")
        self.assertEqual(self.names(category=theirs.pk), ["Next door", "Uncle"])


class CsvImportTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("rina", password="pw-12345!")
        self.client.force_login(self.user)

    def test_categories_by_name_code_or_new(self):
        text = ("Name,Phone,Category,Note,Opening Balance,Date,Due date\n"
                "Karim,,Friend,,500,2026-01-01,\n"
                "Bank Asia,,BANK,,,,\n"
                "Rahim,,Neighbour,,,,\n"
                "Nobody,,,,,,\n")
        f = SimpleUploadedFile("c.csv", text.encode(), content_type="text/csv")
        self.client.post(reverse("creditor_import"), {"csv_file": f})
        got = {c.name: (c.category.code, c.category.name) for c in Creditor.objects.filter(user=self.user)}
        self.assertEqual(got, {"Karim": ("FRIEND", "Friend"), "Bank Asia": ("BANK", "Bank"),
                               "Rahim": ("", "Neighbour"), "Nobody": ("OTHER", "Other")})
        self.assertEqual(Transaction.objects.get(creditor__name="Karim").amount, Decimal("500"))

    def test_the_export_writes_the_name(self):
        ensure_starters(CreditorCategory, self.user, Creditor.objects.none())
        Creditor.objects.create(user=self.user, name="Karim", category=CreditorCategory.objects.create(user=self.user, name="Neighbour"))
        body = self.client.get(reverse("creditor_list"), {"export": "csv"}).content.decode("utf-8-sig")
        self.assertIn("Karim,Neighbour", body)
