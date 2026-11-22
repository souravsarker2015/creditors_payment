"""The update that made creditor, debtor, shop and contributor categories editable keeps everything:
each person stays in the category they had, every account gets the familiar list,
and going back puts the old codes back."""
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

BEFORE = [("creditors", "0012_transaction_receipt"), ("debtors", "0008_transaction_receipt"),
          ("shops", "0007_transaction_receipt"), ("contributors", "0006_alter_contribution_amount")]
AFTER = [("creditors", "0013_creditor_categories"), ("debtors", "0009_debtor_categories"),
         ("shops", "0008_shop_categories"), ("contributors", "0007_contributor_categories")]


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
        old.get_model("shops", "Shop").objects.create(user=rina, name="Medicine Corner", category="PHARMACY")
        old.get_model("shops", "Shop").objects.create(user=joy, name="Odd shop", category="BOOKS")
        old.get_model("contributors", "Contributor").objects.create(user=joy, name="Mosque fund", category="DONOR")

        new = self.migrate(AFTER)
        Creditor, Debtor = new.get_model("creditors", "Creditor"), new.get_model("debtors", "Debtor")
        CreditorCategory = new.get_model("creditors", "CreditorCategory")
        got = {c.name: (c.category.user_id, c.category.code, c.category.name) for c in Creditor.objects.select_related("category")}
        self.assertEqual(got, {"Sonali": (rina.pk, "BANK", "Bank"), "Uncle": (rina.pk, "FAMILY", "Family"),
                               "Hasan": (joy.pk, "BANK", "Bank"), "Odd": (joy.pk, "SOMETHING_OLD", "Something Old")})
        self.assertEqual(Debtor.objects.get(name="Rafi").category.code, "TENANT")
        Shop, Contributor = new.get_model("shops", "Shop"), new.get_model("contributors", "Contributor")
        self.assertEqual((Shop.objects.get(name="Medicine Corner").category.name, Shop.objects.get(name="Medicine Corner").category.user_id), ("Pharmacy", rina.pk))
        self.assertEqual(Shop.objects.get(name="Odd shop").category.name, "Books")
        self.assertEqual(Contributor.objects.get(name="Mosque fund").category.code, "DONOR")
        self.assertEqual(new.get_model("shops", "ShopCategory").objects.filter(user=idle.pk).count(), 10)
        self.assertEqual(new.get_model("contributors", "ContributorCategory").objects.filter(user=idle.pk).count(), 12)
        self.assertEqual(CreditorCategory.objects.filter(user=idle.pk).count(), 12)    # every account gets the list
        self.assertEqual(CreditorCategory.objects.filter(user=joy.pk).count(), 13)
        self.assertNotEqual(Creditor.objects.get(name="Sonali").category_id, Creditor.objects.get(name="Hasan").category_id)

        back = self.migrate(BEFORE)
        codes = {c.name: c.category for c in back.get_model("creditors", "Creditor").objects.all()}
        self.assertEqual(codes, {"Sonali": "BANK", "Uncle": "FAMILY", "Hasan": "BANK", "Odd": "SOMETHING_OLD"})
        self.assertEqual(back.get_model("debtors", "Debtor").objects.get(name="Rafi").category, "TENANT")
        self.assertEqual({s.name: s.category for s in back.get_model("shops", "Shop").objects.all()}, {"Medicine Corner": "PHARMACY", "Odd shop": "BOOKS"})
        self.assertEqual(back.get_model("contributors", "Contributor").objects.get(name="Mosque fund").category, "DONOR")
