"""Everything deleted on a farm can be found and brought back; and an old record keeps what it points at."""
from datetime import date
from decimal import Decimal as D

from django.apps import apps
from django.test import TestCase
from django.urls import reverse

from apps.business.finance.models import Account, Category, CategoryType, Scope, Transaction, Transfer
from apps.business.ponds.models import CultureCycle, Pond

from ..deleted import KINDS
from ..models import BusinessBaseModel
from ..testing import make_farm


class Farm(TestCase):
    def setUp(self):
        self.b, self.owner, self.staff = make_farm()
        self.client.force_login(self.owner)
        self.pond = Pond.objects.create(business=self.b, name="East")
        self.cash = Account.objects.create(business=self.b, name="Cash box", kind="cash", opening_balance=D("100"))
        self.bank = Account.objects.create(business=self.b, name="Bank", kind="bank", opening_balance=D("100"))

    def restore(self, obj):
        return self.client.post(reverse("business:deleted_restore", args=[obj._meta.label_lower, obj.pk]), follow=True)


class DeletedPageTests(Farm):
    def test_every_kind_of_record_is_listed(self):
        """A new business model that can be deleted by itself belongs here; one that goes with its parent is named."""
        with_parent = {"business_feed.feedpurchaseline", "business_sales.fishsaleline", "business_sales.salededuction",
                       "business_markets.marketdeduction", "business_finance.budget", "business_staff.absence"}
        models = {m._meta.label_lower for m in apps.get_models() if issubclass(m, BusinessBaseModel)}
        self.assertEqual(models - set(KINDS) - with_parent, set())
        self.assertEqual(set(KINDS) - models, set())

    def test_a_deleted_entry_with_no_list_of_its_own_comes_back_with_its_money(self):
        move = Transfer.objects.create(business=self.b, date=date.today(), from_account=self.bank, to_account=self.cash, amount=D("40"))
        move.soft_delete()
        self.assertEqual(self.cash.balance, D("100"))
        self.assertContains(self.client.get(reverse("business:deleted")), "Transfer")
        self.assertContains(self.restore(move), "restored")
        self.assertEqual(self.cash.balance, D("140"))

    def test_the_list_can_be_narrowed(self):
        self.pond.soft_delete()
        self.bank.soft_delete()
        page = self.client.get(reverse("business:deleted"), {"kind": "business_ponds.pond"})
        self.assertEqual([r["obj"] for r in page.context["rows"]], [self.pond])
        self.assertEqual(page.context["total"], 2)

    def test_a_cycle_cant_make_two_running(self):
        old = CultureCycle.objects.create(business=self.b, pond=self.pond, start_date=date.today())
        old.soft_delete()
        CultureCycle.objects.create(business=self.b, pond=self.pond, start_date=date.today())
        self.assertContains(self.restore(old), "already has a running cycle")
        self.assertFalse(CultureCycle.objects.filter(pk=old.pk).exists())

    def test_a_name_taken_since_is_said_not_doubled(self):
        self.pond.soft_delete()
        Pond.objects.create(business=self.b, name="East")
        self.assertContains(self.restore(self.pond), "already called")
        self.assertEqual(Pond.objects.filter(name="East").count(), 1)

    def test_pressing_restore_twice_is_fine(self):
        self.pond.soft_delete()
        self.restore(self.pond)
        self.assertContains(self.restore(self.pond), "already back")

    def test_it_stays_inside_the_farm_and_the_role(self):
        other, owner, _ = make_farm("other")
        theirs = Pond.objects.create(business=other, name="Theirs")
        theirs.soft_delete()
        self.assertContains(self.restore(theirs), "already back")
        self.assertFalse(Pond.objects.filter(pk=theirs.pk).exists())
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse("business:deleted")).status_code, 403)

    def test_only_what_belongs_here_can_be_named(self):
        url = reverse("business:deleted_restore", args=["auth.user", self.owner.pk])
        self.assertEqual(self.client.post(url).status_code, 404)


class OldRecordKeepsWhatItPointsAtTests(Farm):
    def setUp(self):
        super().setUp()
        self.category = Category.objects.create(business=self.b, name="Repairs", type=CategoryType.EXPENSE, scope=Scope.BUSINESS)
        self.entry = Transaction.objects.create(business=self.b, date=date.today(), category=self.category, amount=D("25"), account=self.cash)
        self.cash.soft_delete()
        self.url = reverse("business:transaction_edit", args=[self.entry.pk])

    def test_the_deleted_account_is_still_selected(self):
        field = self.client.get(self.url).context["form"]["account"]
        self.assertEqual(field.value(), self.cash.pk)
        self.assertIn(self.cash, field.field.queryset)

    def test_saving_leaves_the_money_where_it_was(self):
        data = {"amount": "30", "date": date.today().isoformat(), "category": self.category.pk, "account": self.cash.pk}
        self.assertEqual(self.client.post(self.url, data).status_code, 302)
        self.entry.refresh_from_db()
        self.assertEqual((self.entry.account_id, self.entry.amount), (self.cash.pk, D("30")))

    def test_a_new_entry_isnt_offered_it(self):
        self.assertNotIn(self.cash, self.client.get(reverse("business:transaction_add")).context["form"]["account"].field.queryset)


class RoleTests(Farm):
    def test_data_entry_isnt_offered_a_delete_it_cant_do(self):
        self.client.force_login(self.staff)
        self.assertNotContains(self.client.get(reverse("business:home")), reverse("business:deleted"))
