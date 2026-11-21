"""A backup made before an update that changed existing data still restores:
backup_upgrades does that update's change to the backup's records first.

Here: creditor and debtor categories, which were a fixed list (a code on each
person, "BANK") and became a list each person keeps (a link to their own row).
"""
import io
import json
import zipfile

from django.contrib.auth import get_user_model

from apps.creditors.models import Creditor, CreditorCategory, DefaultCreditorCategory
from apps.debtors.models import Debtor, DebtorCategory, DefaultDebtorCategory

from .. import backup as bk
from .. import personal_backup as pb
from .test_my_backup import MyBackupBase, reseal

User = get_user_model()
CATEGORY_TABLES = {"creditors.creditorcategory", "debtors.debtorcategory"}
UPDATES = {"creditors": "0013_creditor_categories", "debtors": "0009_debtor_categories"}


def as_before_the_update(manifest, rows):
    """Rewrite a backup the way the version before the update wrote it: a code on each person, no category tables."""
    code = {(r["model"], r["pk"]): (r["fields"]["code"] or "OTHER") for r in rows if r["model"] in CATEGORY_TABLES}
    for r in rows:
        if r["model"] == "creditors.creditor":
            r["fields"]["category"] = code[("creditors.creditorcategory", r["fields"]["category"])]
        elif r["model"] == "debtors.debtor":
            r["fields"]["category"] = code[("debtors.debtorcategory", r["fields"]["category"])]
    gone = [r for r in rows if r["model"] in CATEGORY_TABLES]
    rows[:] = [r for r in rows if r["model"] not in CATEGORY_TABLES]
    for label in CATEGORY_TABLES:
        manifest["counts"].pop(label, None)
    if "total" in manifest:
        manifest["total"] -= len(gone)
    for app, name in UPDATES.items():
        manifest["migrations"][app] = [m for m in manifest["migrations"][app] if m != name]


def reseal_whole(blob, change):
    """The same for a whole-system backup (its files sit at the top of the zip)."""
    src = zipfile.ZipFile(io.BytesIO(blob))
    manifest = json.loads(src.read("manifest.json"))
    rows = json.loads(src.read("data.json"))
    change(manifest, rows)
    data = json.dumps(rows).encode()
    manifest["files"]["data.json"] = {"sha256": bk._sha256(data), "size": len(data)}
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for n in src.namelist():
            if n not in ("manifest.json", "data.json"):
                z.writestr(n, src.read(n))
        z.writestr("data.json", data)
        z.writestr("manifest.json", json.dumps(manifest))
    return out.getvalue()


class CategoryUpgradeTests(MyBackupBase):
    def setUp(self):
        super().setUp()
        cats = {c.code: c for c in CreditorCategory.objects.filter(user=self.me)}   # made with the first creditor
        Creditor.objects.create(user=self.me, name="Sonali Bank", category=cats["BANK"])
        Creditor.objects.create(user=self.me, name="Uncle", category=cats["FAMILY"])
        Debtor.objects.create(user=self.me, name="Rafi")                             # "Other"
        Debtor.objects.create(user=self.me, name="Tenant upstairs",
                              category=DebtorCategory.objects.get(user=self.me, code="TENANT"))

    def assert_brought_back(self, user):
        got = {c.name: (c.category.code, c.category.user_id) for c in Creditor.objects.filter(user=user)}
        self.assertEqual(got, {"Dutch-Bangla Bank": ("OTHER", user.pk), "Sonali Bank": ("BANK", user.pk), "Uncle": ("FAMILY", user.pk)})
        got = {d.name: d.category.code for d in Debtor.objects.filter(user=user)}
        self.assertEqual(got, {"Rafi": "OTHER", "Tenant upstairs": "TENANT"})
        self.assertEqual(sorted(CreditorCategory.objects.filter(user=user).values_list("code", flat=True)), sorted(DefaultCreditorCategory.values))
        self.assertEqual(sorted(DebtorCategory.objects.filter(user=user).values_list("code", flat=True)), sorted(DefaultDebtorCategory.values))

    def test_my_data_from_before_the_update_restores_with_its_categories(self):
        old = self.write(reseal(self.my_zip(), as_before_the_update))
        backup = pb.read(old)
        self.assertTrue(any("brought up to date" in str(n) for n in backup.notes))
        newcomer = User.objects.create_user("newcomer", password="pw-new-1")
        pb.restore(newcomer, backup, keep_copy=False)
        self.assert_brought_back(newcomer)

    def test_the_whole_system_from_before_the_update_restores_with_its_categories(self):
        self.me.is_superuser = self.me.is_staff = True
        self.me.save()
        first = self.tmp / "whole.zip"
        bk.write_backup(first, self.me)
        old = self.tmp / "whole-old.zip"
        old.write_bytes(reseal_whole(first.read_bytes(), as_before_the_update))
        Creditor.objects.all().delete()
        CreditorCategory.objects.all().delete()
        bk.restore_backup(bk.read_backup(old), keep_copy=False)
        self.assert_brought_back(User.objects.get(username="rahim"))
        # every account gets the starters, as the update itself gave them
        karim = User.objects.get(username="karim")
        self.assertEqual(CreditorCategory.objects.filter(user=karim).count(), len(DefaultCreditorCategory.values))
        self.assertEqual(Creditor.objects.get(name="Karim's lender").category, CreditorCategory.objects.get(user=karim, code="OTHER"))

    def test_a_backup_made_now_keeps_my_own_categories_and_links(self):
        mine = CreditorCategory.objects.create(user=self.me, name="Neighbour", is_active=False)
        Creditor.objects.create(user=self.me, name="Next door", category=mine)
        newcomer = User.objects.create_user("newcomer", password="pw-new-1")
        pb.restore(newcomer, pb.read(self.write(self.my_zip())), keep_copy=False)
        came = Creditor.objects.get(user=newcomer, name="Next door").category
        self.assertEqual((came.name, came.is_active, came.user_id, came.code), ("Neighbour", False, newcomer.pk, ""))
        self.assertEqual(CreditorCategory.objects.filter(user=newcomer).count(), CreditorCategory.objects.filter(user=self.me).count())
