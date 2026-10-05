"""Recently deleted: every personal delete can be undone, exactly as it was."""
from datetime import date, timedelta
from decimal import Decimal as D

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.contributors.models import Contribution, Contributor
from apps.creditors.models import Creditor, Transaction as CreditorTx
from apps.expense.models import Expense, ExpenseCategory
from apps.goals.models import AutoSave, GoalEntry, SavingsGoal

from .models import DeletedItem

TODAY = date.today()


class TrashTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("me", password="pw12345!")
        self.client.force_login(self.user)

    def test_delete_then_undo_puts_it_back_with_the_same_id(self):
        cat = ExpenseCategory.objects.create(user=self.user, name="Food")
        e = Expense.objects.create(user=self.user, category=cat, amount=D("500"), date=TODAY, note="rice")
        r = self.client.post(reverse("expense_delete", args=[e.pk]), follow=True)
        self.assertFalse(Expense.objects.filter(pk=e.pk).exists())
        item = DeletedItem.objects.get(user=self.user)
        self.assertContains(r, reverse("trash_restore", args=[item.pk]))          # the Undo button
        self.assertContains(r, "Undo")
        self.client.post(reverse("trash_restore", args=[item.pk]))
        back = Expense.objects.get(pk=e.pk)
        self.assertEqual((back.amount, back.note, back.category_id), (D("500"), "rice", cat.pk))
        self.assertFalse(DeletedItem.objects.exists())

    def test_a_goal_comes_back_with_its_entries_and_auto_save(self):
        g = SavingsGoal.objects.create(user=self.user, name="Laptop", target_amount=D("1000"))
        GoalEntry.objects.create(goal=g, kind=GoalEntry.DEPOSIT, amount=D("1000"), date=TODAY)
        AutoSave.objects.create(goal=g, amount=D("100"), frequency="MONTHLY", next_run_date=TODAY + timedelta(days=30))
        self.client.post(reverse("goal_delete", args=[g.pk]))
        self.assertFalse(SavingsGoal.objects.exists())
        item = DeletedItem.objects.get()
        self.assertEqual(item.count, 3)
        self.client.post(reverse("trash_restore", args=[item.pk]))
        self.assertEqual((GoalEntry.objects.filter(goal_id=g.pk).count(), AutoSave.objects.filter(goal_id=g.pk).count()), (1, 1))

    def test_restoring_a_goal_entry_rechecks_the_goal(self):
        g = SavingsGoal.objects.create(user=self.user, name="Bike", target_amount=D("500"))
        entry = GoalEntry.objects.create(goal=g, kind=GoalEntry.DEPOSIT, amount=D("500"), date=TODAY)
        from apps.goals.services import sync_reached

        sync_reached(g)
        self.client.post(reverse("goal_entry_delete", args=[entry.pk]))
        g.refresh_from_db()
        reached_after_delete = g.reached_at
        self.client.post(reverse("trash_restore", args=[DeletedItem.objects.get().pk]))
        g.refresh_from_db()
        self.assertIsNone(reached_after_delete)
        self.assertIsNotNone(g.reached_at)

    def test_cannot_restore_when_its_owner_is_gone(self):
        c = Contributor.objects.create(user=self.user, name="Uncle")
        gift = Contribution.objects.create(contributor=c, amount=D("2000"), date=TODAY)
        self.client.post(reverse("contribution_delete", args=[gift.pk]))
        c.delete()                                       # gone for good
        r = self.client.post(reverse("trash_restore", args=[DeletedItem.objects.get().pk]), follow=True)
        self.assertContains(r, "can&#x27;t be put back")
        self.assertFalse(Contribution.objects.exists())

    def test_list_forget_empty_and_others_cannot_touch_it(self):
        cr = Creditor.objects.create(user=self.user, name="Karim")
        for amount in ("100", "200"):
            t = CreditorTx.objects.create(creditor=cr, transaction_type=CreditorTx.BORROW, amount=D(amount), date=TODAY)
            self.client.post(reverse("transaction_delete", args=[t.pk]))
        self.assertContains(self.client.get(reverse("trash_list")), "Karim · ৳200")
        first = DeletedItem.objects.last()
        other = User.objects.create_user("them", password="pw12345!")
        self.client.force_login(other)
        self.assertEqual(self.client.post(reverse("trash_restore", args=[first.pk])).status_code, 404)
        self.client.force_login(self.user)
        self.client.post(reverse("trash_forget", args=[first.pk]))
        self.assertEqual(DeletedItem.objects.count(), 1)
        self.client.post(reverse("trash_empty"))
        self.assertFalse(DeletedItem.objects.exists())

    def test_old_items_are_cleared_after_30_days(self):
        old = DeletedItem.objects.create(user=self.user, label="Old", kind="Expense", data="[]")
        DeletedItem.objects.filter(pk=old.pk).update(deleted_at=timezone.now() - timedelta(days=31))
        self.client.get(reverse("trash_list"))
        self.assertFalse(DeletedItem.objects.exists())
