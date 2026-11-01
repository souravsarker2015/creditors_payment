"""Deleting a person, shop or income source (added by mistake) with all its
entries, and bringing it all back from Recently deleted."""
from datetime import date
from decimal import Decimal as D

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from apps.trash.models import DeletedItem


class DeleteRecordTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("del_user", password="x")
        self.other = User.objects.create_user("del_other", password="x")
        self.client.force_login(self.user)

    def _round_trip(self, obj, url_name, list_name, children):
        """Delete obj, check it and its entries are gone, restore, check they're back."""
        model, pk = type(obj), obj.pk
        before = [c.count() for c in children]
        r = self.client.post(reverse(url_name, args=[pk]))
        self.assertRedirects(r, reverse(list_name), fetch_redirect_response=False)
        self.assertFalse(model.objects.filter(pk=pk).exists())
        self.assertEqual([c.count() for c in children], [0] * len(children))
        item = DeletedItem.objects.get(user=self.user)
        self.client.post(reverse("trash_restore", args=[item.pk]))
        self.assertTrue(model.objects.filter(pk=pk).exists())
        self.assertEqual([c.count() for c in children], before)

    def test_creditor_with_entries_and_plan(self):
        from apps.creditors.models import Creditor, Transaction
        from apps.plans.models import InstallmentPlan

        c = Creditor.objects.create(user=self.user, name="Typo")
        Transaction.objects.create(creditor=c, transaction_type="BORROW", amount=D("500"), date=date(2026, 1, 1))
        InstallmentPlan.objects.create(user=self.user, creditor=c, amount=D("100"), frequency="weekly", start_date=date(2026, 2, 1))
        self._round_trip(c, "creditor_delete", "creditor_list",
                         [Transaction.objects.filter(creditor_id=c.pk), InstallmentPlan.objects.filter(creditor_id=c.pk)])

    def test_debtor_shop_source_member(self):
        from apps.debtors.models import Debtor, Transaction as DT
        from apps.household.models import HouseholdMember, Purchase, Settlement
        from apps.income.models import IncomeSource, IncomeTransaction
        from apps.shops.models import Shop, Transaction as ST

        d = Debtor.objects.create(user=self.user, name="D")
        DT.objects.create(debtor=d, transaction_type="LEND", amount=D("50"), date=date(2026, 1, 1))
        self._round_trip(d, "debtor_delete", "debtor_list", [DT.objects.filter(debtor_id=d.pk)])
        DeletedItem.objects.all().delete()

        s = Shop.objects.create(user=self.user, name="S")
        ST.objects.create(shop=s, transaction_type="PURCHASE", amount=D("70"), date=date(2026, 1, 1))
        self._round_trip(s, "shop_delete", "shop_list", [ST.objects.filter(shop_id=s.pk)])
        DeletedItem.objects.all().delete()

        src = IncomeSource.objects.create(user=self.user, name="Job")
        IncomeTransaction.objects.create(source=src, amount=D("900"), date=date(2026, 1, 1))
        self._round_trip(src, "income_source_delete", "income_source_list", [IncomeTransaction.objects.filter(source_id=src.pk)])
        DeletedItem.objects.all().delete()

        m = HouseholdMember.objects.create(user=self.user, name="Mother")
        Settlement.objects.create(member=m, amount=D("30"), date=date(2026, 1, 1))
        p = Purchase.objects.create(user=self.user, buyer=m, amount=D("80"), date=date(2026, 1, 1))
        self._round_trip(m, "household_member_delete", "household_member_list", [Settlement.objects.filter(member_id=m.pk)])
        p.refresh_from_db()
        self.assertEqual(p.buyer_id, m.pk)   # the bazar entry is kept and linked again

    def test_only_the_owner_and_only_by_post(self):
        from apps.creditors.models import Creditor

        c = Creditor.objects.create(user=self.other, name="Not yours")
        self.assertEqual(self.client.post(reverse("creditor_delete", args=[c.pk])).status_code, 404)
        mine = Creditor.objects.create(user=self.user, name="Mine")
        self.assertEqual(self.client.get(reverse("creditor_delete", args=[mine.pk])).status_code, 405)
        self.assertContains(self.client.get(reverse("creditor_detail", args=[mine.pk])), reverse("creditor_delete", args=[mine.pk]))
