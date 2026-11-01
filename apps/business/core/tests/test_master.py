"""Farm setup (master data): seeding, the shared list/form pages, "+ Add new"."""
from django.test import TestCase
from django.urls import reverse

from apps.business.core.models import Unit
from apps.business.core.seeding import seed_all
from apps.business.core.testing import make_farm
from apps.business.finance.models import Account, Category
from apps.business.markets.models import DeductionType, Market, MarketDeduction
from apps.business.parties.models import Party
from apps.business.ponds.models import Pond
from apps.business.species.models import Species


class SeedingTests(TestCase):
    def test_new_farm_gets_starter_lists(self):
        b, _, _ = make_farm()
        self.assertEqual(Species.objects.filter(business=b).count(), 18)
        self.assertTrue(Species.objects.filter(business=b, name="Rui", name_bn="রুই").exists())
        self.assertTrue(DeductionType.objects.filter(business=b, name="Aarot commission").exists())
        self.assertTrue(Category.objects.filter(business=b, name="School fees", parent__name="Children").exists())
        self.assertTrue(Account.objects.get(business=b).is_default)

    def test_seeding_again_adds_nothing_and_keeps_edits(self):
        b, _, _ = make_farm()
        rui = Species.objects.get(business=b, name="Rui")
        rui.name_bn = "রুই মাছ"
        rui.save()
        self.assertEqual(sum(seed_all(b).values()), 0)
        self.assertEqual(Species.objects.get(pk=rui.pk).name_bn, "রুই মাছ")

    def test_seeded_species_keep_their_order(self):
        b, _, _ = make_farm()
        self.assertEqual(list(Species.objects.filter(business=b).values_list("name", flat=True)[:3]), ["Rui", "Katla", "Mrigal"])

    def test_seeding_is_not_in_the_activity_log(self):
        b, _, _ = make_farm()
        self.assertEqual(b.audit_log.count(), 0)


class MasterPagesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.b, cls.owner, cls.staff = make_farm()

    def setUp(self):
        self.client.force_login(self.owner)

    def test_every_list_and_form_renders(self):
        for name in ["ponds", "species", "markets", "deduction_types", "suppliers", "buyers", "feed_products", "categories", "accounts"]:
            for url in (reverse(f"business:{name}"), reverse(f"business:{name}_add")):
                self.assertEqual(self.client.get(url).status_code, 200, url)
        self.assertEqual(self.client.get(reverse("business:setup_hub")).status_code, 200)
        self.assertEqual(self.client.get(reverse("business:home")).status_code, 200)

    def test_duplicate_names_are_refused_case_insensitively(self):
        r = self.client.post(reverse("business:species_add"), {"name": "rui", "color": "#0e7490"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("name", r.context["form"].errors)

    def test_soft_delete_and_restore(self):
        sp = Species.objects.get(business=self.b, name="Pabda")
        self.client.post(reverse("business:species_delete", args=[sp.pk]))
        self.assertFalse(Species.objects.filter(pk=sp.pk).exists())
        self.assertIn(sp, self.client.get(reverse("business:species") + "?show=deleted").context["objects"])
        self.client.post(reverse("business:species_restore", args=[sp.pk]))
        self.assertTrue(Species.objects.filter(pk=sp.pk).exists())

    def test_search(self):
        r = self.client.get(reverse("business:species") + "?q=পাঙ্গাস")
        self.assertEqual([s.name for s in r.context["objects"]], ["Pangas"])

    def test_other_farms_records_are_not_reachable(self):
        other, _, _ = make_farm("other")
        sp = Species.objects.filter(business=other).first()
        self.assertEqual(self.client.get(reverse("business:species_edit", args=[sp.pk])).status_code, 404)
        self.client.post(reverse("business:species_delete", args=[sp.pk]))
        self.assertFalse(Species.all_objects.get(pk=sp.pk).is_deleted)

    def test_data_entry_can_add_people_but_not_change_settings(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse("business:suppliers_add")).status_code, 200)
        self.assertEqual(self.client.get(reverse("business:ponds_add")).status_code, 403)
        self.assertEqual(self.client.get(reverse("business:accounts")).status_code, 403)
        self.assertEqual(self.client.get(reverse("business:ponds")).status_code, 200)

    def test_quick_add_creates_or_picks_existing(self):
        url = reverse("business:quick_add", args=["market"])
        r = self.client.post(url, {"qa_market-name": "Trishal"})
        self.assertEqual(r.status_code, 201)
        r = self.client.post(url, {"qa_market-name": "trishal"})
        self.assertEqual(r.json()["id"], Market.objects.get(business=self.b).pk)
        self.assertEqual(Market.objects.filter(business=self.b).count(), 1)

    def test_quick_add_respects_roles(self):
        self.client.force_login(self.staff)
        r = self.client.post(reverse("business:quick_add", args=["deduction_type"]), {"qa_deduction_type-name": "Ice 2", "qa_deduction_type-method": "fixed"})
        self.assertEqual(r.status_code, 403)
        r = self.client.post(reverse("business:quick_add", args=["buyer"]), {"qa_buyer-name": "Hasan"})
        self.assertEqual(r.status_code, 201)
        self.assertTrue(Party.objects.get(name="Hasan").is_buyer)


class PondTests(TestCase):
    def setUp(self):
        self.b, owner, _ = make_farm()
        self.client.force_login(owner)
        self.bigha = Unit.objects.get(business=self.b, symbol="bigha")

    def test_area_is_converted_to_decimals(self):
        self.client.post(reverse("business:ponds_add"), {"name": "East", "area": "2", "area_unit": self.bigha.pk, "status": "in_use", "ownership": "own"})
        self.assertEqual(Pond.objects.get().area_decimal, 66)

    def test_lease_fields_cleared_for_own_pond_and_checked_for_leased(self):
        self.client.post(reverse("business:ponds_add"), {"name": "A", "status": "in_use", "ownership": "own", "lease_amount": "5000"})
        self.assertIsNone(Pond.objects.get().lease_amount)
        r = self.client.post(reverse("business:ponds_add"), {"name": "B", "status": "in_use", "ownership": "leased",
                                                            "lease_start": "2026-05-01", "lease_end": "2026-01-01"})
        self.assertIn("lease_end", r.context["form"].errors)


class MarketTests(TestCase):
    def setUp(self):
        self.b, owner, _ = make_farm()
        self.client.force_login(owner)
        self.commission = DeductionType.objects.get(business=self.b, name="Aarot commission")
        self.labour = DeductionType.objects.get(business=self.b, name="Labour")
        self.mon = Unit.objects.get(business=self.b, symbol="mon")

    def post(self, rows, **extra):
        data = {"name": "Mesua aarot", "rows-TOTAL_FORMS": str(len(rows)), "rows-INITIAL_FORMS": "0", "rows-MIN_NUM_FORMS": "0", "rows-MAX_NUM_FORMS": "1000", **extra}
        for i, row in enumerate(rows):
            data.update({f"rows-{i}-{k}": v for k, v in row.items()})
        return self.client.post(reverse("business:markets_add"), data)

    def test_market_with_deductions(self):
        self.post([{"deduction_type": self.commission.pk, "method": "percent", "value": "3"},
                   {"deduction_type": self.labour.pk, "method": "per_unit", "value": "20", "unit": self.mon.pk}])
        m = Market.objects.get()
        self.assertEqual([d.describe() for d in m.deductions.all()], ["3%", "৳20/mon"])

    def test_per_unit_needs_a_unit(self):
        r = self.post([{"deduction_type": self.labour.pk, "method": "per_unit", "value": "20"}])
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Market.objects.exists())

    def test_a_removed_row_leaves_no_trace(self):
        # Row 0 was added then removed on the page: only row 1 is posted.
        data_rows = [{}, {"deduction_type": self.commission.pk, "method": "percent", "value": "2.5"}]
        self.post(data_rows)
        self.assertEqual(MarketDeduction.objects.count(), 1)

    def test_deduction_type_in_use_cannot_be_deleted(self):
        self.post([{"deduction_type": self.commission.pk, "method": "percent", "value": "3"}])
        self.client.post(reverse("business:deduction_types_delete", args=[self.commission.pk]))
        self.assertFalse(DeductionType.all_objects.get(pk=self.commission.pk).is_deleted)


class PartyTests(TestCase):
    def setUp(self):
        self.b, owner, _ = make_farm()
        self.client.force_login(owner)

    def test_supplier_page_adds_a_supplier_with_opening_balance(self):
        self.client.post(reverse("business:suppliers_add"), {"name": "Mollah Feed", "opening_balance": "85000", "opening_type": "payable"})
        p = Party.objects.get()
        self.assertTrue(p.is_supplier)
        self.assertFalse(p.is_buyer)
        self.assertEqual(p.opening_signed, -85000)

    def test_someone_can_be_both(self):
        self.client.post(reverse("business:buyers_add"), {"name": "Karim", "is_supplier": "on", "opening_type": "receivable"})
        p = Party.objects.get()
        self.assertTrue(p.is_buyer and p.is_supplier)
        self.assertEqual(self.client.get(reverse("business:suppliers")).context["objects"], [p])


class FinanceTests(TestCase):
    def setUp(self):
        self.b, owner, _ = make_farm()
        self.client.force_login(owner)

    def test_sub_category_takes_its_parents_type_and_scope(self):
        children = Category.objects.get(business=self.b, name="Children")
        self.client.post(reverse("business:categories_add"), {"name": "Exam fees", "type": "income", "scope": "business", "parent": children.pk})
        c = Category.objects.get(name="Exam fees")
        self.assertEqual((c.type, c.scope), ("expense", "household"))

    def test_same_name_allowed_in_different_places(self):
        r = self.client.post(reverse("business:categories_add"), {"name": "Transport", "type": "expense", "scope": "household"})
        self.assertEqual(r.status_code, 302)
        r = self.client.post(reverse("business:categories_add"), {"name": "transport", "type": "expense", "scope": "household"})
        self.assertEqual(r.status_code, 200)

    def test_system_category_cannot_be_deleted(self):
        sales = Category.objects.get(business=self.b, name="Fish sales")
        self.client.post(reverse("business:categories_delete", args=[sales.pk]))
        self.assertFalse(Category.all_objects.get(pk=sales.pk).is_deleted)

    def test_only_one_default_account(self):
        self.client.post(reverse("business:accounts_add"), {"name": "bKash", "kind": "mobile", "is_default": "on"})
        self.assertEqual(list(Account.objects.filter(business=self.b, is_default=True).values_list("name", flat=True)), ["bKash"])
