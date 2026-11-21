"""The update that made creditor and debtor categories editable keeps everything:
each person stays in the category they had, every account gets the familiar list,
and going back puts the old codes back."""
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

BEFORE = [("creditors", "0012_transaction_receipt"), ("debtors", "0008_transaction_receipt")]
AFTER = [("creditors", "0013_creditor_categories"), ("debtors", "0009_debtor_categories")]


class CategoryMigrationTests(TransactionTestCase):
    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def tearDown(self):
        self.migrate(MigrationExecutor(connection).loader.graph.leaf_nodes())   # the latest again, for the other tests

    def test_codes_become_links_and_back(self):
        old = self.migrate(BEFORE)
        User = old.get_model("auth", "User")
        OldCreditor, OldDebtor = old.get_model("creditors", "Creditor"), old.get_model("debtors", "Debtor")
        rina, joy, idle = (User.objects.create(username=n) for n in ("rina", "joy", "idle"))
        OldCreditor.objects.create(user=rina, name="Sonali", category="BANK")
        OldCreditor.objects.create(user=rina, name="Uncle", category="FAMILY")
        OldCreditor.objects.create(user=joy, name="Hasan", category="BANK")
        OldCreditor.objects.create(user=joy, name="Odd", category="SOMETHING_OLD")     # a value the list never had
        OldDebtor.objects.create(user=rina, name="Rafi", category="TENANT")

        new = self.migrate(AFTER)
        Creditor, Debtor = new.get_model("creditors", "Creditor"), new.get_model("debtors", "Debtor")
        CreditorCategory = new.get_model("creditors", "CreditorCategory")
        got = {c.name: (c.category.user_id, c.category.code, c.category.name) for c in Creditor.objects.select_related("category")}
        self.assertEqual(got, {"Sonali": (rina.pk, "BANK", "Bank"), "Uncle": (rina.pk, "FAMILY", "Family"),
                               "Hasan": (joy.pk, "BANK", "Bank"), "Odd": (joy.pk, "SOMETHING_OLD", "Something Old")})
        self.assertEqual(Debtor.objects.get(name="Rafi").category.code, "TENANT")
        self.assertEqual(CreditorCategory.objects.filter(user=idle.pk).count(), 12)    # every account gets the list
        self.assertEqual(CreditorCategory.objects.filter(user=joy.pk).count(), 13)
        self.assertNotEqual(Creditor.objects.get(name="Sonali").category_id, Creditor.objects.get(name="Hasan").category_id)

        back = self.migrate(BEFORE)
        codes = {c.name: c.category for c in back.get_model("creditors", "Creditor").objects.all()}
        self.assertEqual(codes, {"Sonali": "BANK", "Uncle": "FAMILY", "Hasan": "BANK", "Odd": "SOMETHING_OLD"})
        self.assertEqual(back.get_model("debtors", "Debtor").objects.get(name="Rafi").category, "TENANT")
