"""Backup & restore my data: one person's own backup (personal_backup.py)."""
import io
import json
import shutil
import tempfile
import zipfile
from datetime import date
from decimal import Decimal as D
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import TwoFactor
from apps.creditors.models import Creditor, Transaction
from apps.expense.models import Expense, ExpenseCategory
from apps.productivity.models import Tag, Task, TimeEntry, WorkSettings
from apps.trash.models import DeletedItem
from apps.wallets.models import Wallet

from . import backup as bk
from . import personal_backup as pb
from .my_data import build_zip

User = get_user_model()
TODAY = date.today()


def reseal(blob, change):
    """A copy of a personal backup, edited by `change(manifest, rows)`, with valid checksums."""
    src = zipfile.ZipFile(io.BytesIO(blob))
    manifest = json.loads(src.read("backup/manifest.json"))
    rows = json.loads(src.read("backup/data.json"))
    change(manifest, rows)
    data = json.dumps(rows).encode()
    manifest["files"]["data.json"] = {"sha256": pb._sha256(data), "size": len(data)}
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for n in src.namelist():
            if n not in ("backup/manifest.json", "backup/data.json"):
                z.writestr(n, src.read(n))
        z.writestr("backup/data.json", data)
        z.writestr("backup/manifest.json", json.dumps(manifest))
    return out.getvalue()


class MyBackupBase(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="fintrack-my-backup-tests-"))
        cls._dirs = override_settings(BACKUP_DIR=cls.tmp / "backups", MEDIA_ROOT=cls.tmp / "media")
        cls._dirs.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._dirs.disable()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        shutil.rmtree(self.tmp / "backups", ignore_errors=True)
        self.me = User.objects.create_user("rahim", password="pw-rahim-1", first_name="Rahim")
        self.other = User.objects.create_user("karim", password="pw-karim-1")
        self.wallet = Wallet.objects.create(user=self.me, name="bKash")
        self.creditor = Creditor.objects.create(user=self.me, name="Dutch-Bangla Bank")
        Transaction.objects.create(creditor=self.creditor, transaction_type=Transaction.BORROW, amount=D("5000"), date=TODAY, wallet=self.wallet)
        cat = ExpenseCategory.objects.create(user=self.me, name="Rent")
        self.expense = Expense.objects.create(user=self.me, category=cat, amount=D("1200"), date=TODAY, wallet=self.wallet)
        self.expense.receipt.save("rent.jpg", ContentFile(b"\xff\xd8 receipt"), save=True)
        tag = Tag.objects.create(owner=self.me, name="backend")
        self.task = Task.objects.create(owner=self.me, title="Fix the login bug")
        self.task.tags.add(tag)
        TimeEntry.objects.create(owner=self.me, task=self.task, started_at="2026-01-05T09:00:00Z", ended_at="2026-01-05T10:00:00Z")
        WorkSettings.for_user(self.me)
        TwoFactor.objects.create(user=self.me, secret="JBSWY3DPEHPK3PXP", enabled=True)
        # someone else's records, which a backup must never reach
        Creditor.objects.create(user=self.other, name="Karim's lender")
        self.others_wallet = Wallet.objects.create(user=self.other, name="Karim's cash")

    def my_zip(self, user=None):
        return build_zip(user or self.me)[0]

    def write(self, blob, name="mine.zip"):
        path = Path(tempfile.mkdtemp(dir=self.tmp)) / name
        path.write_bytes(blob)
        return path


class DownloadTests(MyBackupBase):
    def test_zip_has_sheets_and_a_restorable_copy_without_secrets(self):
        z = zipfile.ZipFile(io.BytesIO(self.my_zip()))
        names = set(z.namelist())
        self.assertIn("creditors-creditor.csv", names)
        self.assertIn("productivity-task.csv", names)            # the work tracker is in it now
        self.assertIn("backup/manifest.json", names)
        self.assertIn("backup/data.json", names)
        self.assertTrue(any(n.startswith("backup/media/receipts/") for n in names))
        self.assertFalse(any("twofactor" in n or "offlinereceipt" in n for n in names))
        self.assertNotIn(b"JBSWY3DPEHPK3PXP", b"".join(z.read(n) for n in names))
        settings_csv = z.read("productivity-worksettings.csv").decode("utf-8-sig")
        self.assertNotIn("feed", settings_csv.splitlines()[0].lower())
        self.assertNotIn(b"Karim", z.read("backup/data.json"))

    def test_page_and_download_need_sign_in(self):
        for name in ("my_data", "my_data_page", "my_data_restore"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 302)

    def test_page_shows_counts(self):
        self.client.force_login(self.me)
        r = self.client.get(reverse("my_data_page"))
        self.assertContains(r, "My data & backup")
        self.assertContains(r, reverse("my_data"))


class RestoreTests(MyBackupBase):
    def test_restore_into_another_account_relinks_everything(self):
        new = User.objects.create_user("rahim2", password="pw")
        before = pb.counts_for(self.me)
        result = pb.restore(new, pb.read(self.write(self.my_zip())), keep_copy=False)
        self.assertEqual({k: v for k, v in pb.counts_for(new).items() if v}, {k: v for k, v in before.items() if v})
        self.assertEqual(result["total"], sum(before.values()))
        tx = Transaction.objects.get(creditor__user=new)
        self.assertEqual(tx.wallet.user, new)
        task = Task.objects.get(owner=new)
        self.assertEqual([t.owner for t in task.tags.all()], [new])
        self.assertEqual(TimeEntry.objects.get(owner=new).task, task)
        expense = Expense.objects.get(user=new)
        self.assertNotEqual(expense.receipt.name, self.expense.receipt.name)
        self.assertTrue(expense.receipt.name.startswith(f"receipts/{new.pk}/"))
        self.assertEqual(default_storage.open(expense.receipt.name).read(), b"\xff\xd8 receipt")
        self.assertEqual(sum(pb.counts_for(self.me).values()), sum(before.values()))     # the original is untouched
        self.assertEqual(Creditor.objects.filter(user=self.other).count(), 1)

    def test_restoring_twice_replaces_never_duplicates(self):
        blob = self.my_zip()
        before = pb.counts_for(self.me)
        Creditor.objects.create(user=self.me, name="Added after the backup")
        pb.restore(self.me, pb.read(self.write(blob)))
        pb.restore(self.me, pb.read(self.write(blob)))
        self.assertEqual(pb.counts_for(self.me), before)
        self.assertFalse(Creditor.objects.filter(user=self.me, name="Added after the backup").exists())
        self.assertTrue(TwoFactor.objects.filter(user=self.me, enabled=True).exists())   # sign-in is not part of it

    def test_safety_copy_undoes_a_restore(self):
        Creditor.objects.create(user=self.me, name="Only in the newer data")
        old = self.write(build_zip(self.me)[0])
        Creditor.objects.filter(user=self.me, name="Only in the newer data").delete()
        result = pb.restore(self.me, pb.read(self.write(self.my_zip())))
        self.assertIsNotNone(result["copy"])
        self.assertTrue(pb.copy_path(self.me, result["copy"].name))
        pb.restore(self.me, pb.read(result["copy"]), keep_copy=False)
        self.assertFalse(Creditor.objects.filter(user=self.me, name="Only in the newer data").exists())
        pb.restore(self.me, pb.read(old), keep_copy=False)
        self.assertTrue(Creditor.objects.filter(user=self.me, name="Only in the newer data").exists())

    def test_recycle_bin_is_emptied(self):
        DeletedItem.objects.create(user=self.me, label="x", kind="creditor", data="[]")
        pb.restore(self.me, pb.read(self.write(self.my_zip())), keep_copy=False)
        self.assertFalse(DeletedItem.objects.filter(user=self.me).exists())

    def test_a_link_to_someone_elses_record_is_dropped(self):
        def point_at_karims_wallet(manifest, rows):
            for r in rows:
                if r["model"] == "expense.expense":
                    r["fields"]["wallet"] = self.others_wallet.pk
                if r["model"] == "wallets.wallet":
                    r["pk"] = 999999            # so the backup's own wallet can't be confused with Karim's
                if r["model"] == "creditors.transaction":
                    r["fields"]["wallet"] = 999999
        blob = reseal(self.my_zip(), point_at_karims_wallet)
        new = User.objects.create_user("thief", password="pw")
        pb.restore(new, pb.read(self.write(blob)), keep_copy=False)
        self.assertIsNone(Expense.objects.get(user=new).wallet)
        self.assertEqual(Transaction.objects.get(creditor__user=new).wallet.user, new)
        self.assertEqual(Wallet.objects.get(pk=self.others_wallet.pk).user, self.other)

    def test_records_claiming_another_owner_become_mine(self):
        def as_karim(manifest, rows):
            for r in rows:
                for key in ("user", "owner"):
                    if key in r["fields"]:
                        r["fields"][key] = self.other.pk
        pb.restore(self.me, pb.read(self.write(reseal(self.my_zip(), as_karim))), keep_copy=False)
        self.assertEqual(Creditor.objects.filter(user=self.other).count(), 1)
        self.assertEqual(Creditor.objects.filter(user=self.me).count(), 1)

    def test_tables_outside_my_data_are_refused(self):
        def add_user(manifest, rows):
            rows.append({"model": "auth.user", "pk": 50, "fields": {"username": "x", "is_superuser": True}})
            manifest["counts"]["auth.user"] = 1
        with self.assertRaises(bk.BackupError):
            pb.read(self.write(reseal(self.my_zip(), add_user)))

    def test_a_changed_file_is_refused(self):
        src = zipfile.ZipFile(io.BytesIO(self.my_zip()))
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as z:
            for n in src.namelist():
                z.writestr(n, src.read(n).replace(b"Dutch-Bangla", b"Dutch-Bangle") if n == "backup/data.json" else src.read(n))
        with self.assertRaisesMessage(bk.BackupError, "changed"):
            pb.read(self.write(out.getvalue()))

    def test_other_kinds_of_file_get_a_clear_message(self):
        whole = self.tmp / "whole.zip"
        User.objects.create_superuser("boss", password="pw")
        bk.write_backup(whole)
        with self.assertRaisesMessage(bk.BackupError, "whole system"):
            pb.read(whole)
        old = io.BytesIO()
        with zipfile.ZipFile(old, "w") as z:
            z.writestr("creditors-creditor.csv", "ID,Name\n")
        with self.assertRaisesMessage(bk.BackupError, "only has Excel sheets"):
            pb.read(self.write(old.getvalue()))
        with self.assertRaises(bk.BackupError):
            pb.read(self.write(b"not a zip"))


class PageFlowTests(MyBackupBase):
    def test_upload_check_and_restore(self):
        blob = self.my_zip()
        Creditor.objects.create(user=self.me, name="Added after the backup")
        self.client.force_login(self.me)
        r = self.client.post(reverse("my_data_upload"), {"backup": SimpleUploadedFile("mine.zip", blob, "application/zip")})
        self.assertRedirects(r, reverse("my_data_restore"))
        r = self.client.get(reverse("my_data_restore"))
        self.assertContains(r, "Check the backup")
        self.assertContains(r, "Restore now")
        r = self.client.post(reverse("my_data_restore"))                  # the box wasn't ticked
        self.assertRedirects(r, reverse("my_data_restore"))
        self.assertTrue(Creditor.objects.filter(user=self.me, name="Added after the backup").exists())
        r = self.client.post(reverse("my_data_restore"), {"confirm": "yes"}, follow=True)
        self.assertContains(r, "Restored")
        self.assertFalse(Creditor.objects.filter(user=self.me, name="Added after the backup").exists())
        self.assertContains(r, "Saved before a restore")
        self.assertEqual(self.client.get(reverse("my_data_restore")).status_code, 302)   # nothing waiting any more

    def test_bad_file_is_refused_on_upload(self):
        self.client.force_login(self.me)
        r = self.client.post(reverse("my_data_upload"), {"backup": SimpleUploadedFile("x.zip", b"nope")}, follow=True)
        self.assertContains(r, "My data")
        self.assertEqual(Creditor.objects.filter(user=self.me).count(), 1)

    def test_cancel(self):
        self.client.force_login(self.me)
        self.client.post(reverse("my_data_upload"), {"backup": SimpleUploadedFile("mine.zip", self.my_zip())})
        self.client.post(reverse("my_data_cancel"))
        self.assertEqual(self.client.get(reverse("my_data_restore")).status_code, 302)

    def test_someone_elses_saved_copy_is_out_of_reach(self):
        copy = pb.save_copy(self.other)
        self.client.force_login(self.me)
        self.assertEqual(self.client.get(reverse("my_data_copy", args=[copy.name])).status_code, 404)
        self.assertEqual(self.client.post(reverse("my_data_copy", args=[copy.name])).status_code, 404)
        self.assertEqual(self.client.get(reverse("my_data_copy", args=["..x.txt"])).status_code, 404)

    def test_someone_elses_pending_upload_is_ignored(self):
        self.client.force_login(self.other)
        self.client.post(reverse("my_data_upload"), {"backup": SimpleUploadedFile("mine.zip", self.my_zip(self.other))})
        name = self.client.session["my_backup_pending"]
        self.client.force_login(self.me)
        session = self.client.session
        session["my_backup_pending"] = name
        session.save()
        self.assertEqual(self.client.get(reverse("my_data_restore")).status_code, 302)

    def test_work_tracker_restore_reads_my_data_file(self):
        WorkSettings.objects.all().delete()
        new = User.objects.create_superuser("dev", password="pw")
        from apps.business.core.models import Dashboard

        Dashboard.objects.get_or_create(code="productivity", defaults={"name": "Productivity", "url_name": "work:today"})
        self.client.force_login(new)
        r = self.client.post(reverse("work:settings"), {"action": "restore", "backup": SimpleUploadedFile("mine.zip", self.my_zip())})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Task.objects.filter(owner=new).count(), 1)


class WholeSystemExtrasTests(MyBackupBase):
    def test_keep_only_the_newest(self):
        import os
        import time

        for i in range(4):
            path = bk.backup_dir() / f"fintrack-backup-2026-01-0{i + 1}-000000.zip"
            path.write_bytes(b"x")
            os.utime(path, (time.time() - 1000 + i, time.time() - 1000 + i))
        (bk.backup_dir() / "before-restore-2026-01-01-000000.zip").write_bytes(b"x")
        gone = bk.prune(2)
        self.assertEqual(sorted(gone), ["fintrack-backup-2026-01-01-000000.zip", "fintrack-backup-2026-01-02-000000.zip"])
        self.assertTrue((bk.backup_dir() / "before-restore-2026-01-01-000000.zip").exists())

    def test_work_tracker_has_its_own_area(self):
        keys = [a["key"] for a in bk.summary(bk.current_counts())]
        self.assertIn("work", keys)
        work = next(a for a in bk.summary(bk.current_counts()) if a["key"] == "work")
        self.assertTrue(any(r["label"] == "productivity.task" for r in work["rows"]))
