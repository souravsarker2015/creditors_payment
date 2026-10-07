"""Whole-system backup & restore: exact round trips, no duplicates, nothing
half-done, and only site admins."""
import io
import json
import shutil
import tempfile
import zipfile
from decimal import Decimal as D
from pathlib import Path

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.business.core.testing import make_farm
from apps.business.ponds.models import Pond
from apps.creditors.models import Creditor

from . import backup as bk



def data_of(path):
    return zipfile.ZipFile(path).read("data.json")


def rewrite(src, dst, change):
    """Copy a backup, letting `change(manifest, rows)` edit it, and re-seal it (valid checksums)."""
    with zipfile.ZipFile(src) as z:
        manifest = json.loads(z.read("manifest.json"))
        rows = json.loads(z.read("data.json"))
        others = {n: z.read(n) for n in z.namelist() if n not in ("manifest.json", "data.json")}
    change(manifest, rows)
    data = json.dumps(rows).encode()
    manifest["files"]["data.json"] = {"sha256": bk._sha256(data), "size": len(data)}
    with zipfile.ZipFile(dst, "w") as z:
        z.writestr("data.json", data)
        for n, blob in others.items():
            z.writestr(n, blob)
        z.writestr("manifest.json", json.dumps(manifest))
    return dst


class BackupTestBase(TestCase):
    # A folder of its own for each test class: tests running side by side
    # (--parallel) never see or remove each other's files.
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="fintrack-backup-tests-"))
        cls._dirs = override_settings(BACKUP_DIR=cls.tmp / "backups", MEDIA_ROOT=cls.tmp / "media")
        cls._dirs.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._dirs.disable()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        shutil.rmtree(self.tmp / "backups", ignore_errors=True)   # each test starts with no server copies
        User = get_user_model()
        self.admin = User.objects.create_superuser("boss", password="pw-boss-1")
        self.creditor = Creditor.objects.create(user=self.admin, name="Dutch-Bangla Bank")
        self.b, self.owner, self.staff = make_farm()
        self.pond = Pond.objects.create(business=self.b, name="East pond", area=D("60"))
        self.pond.photo.save("east.jpg", ContentFile(b"\xff\xd8 pond photo"), save=True)
        self.dir = Path(tempfile.mkdtemp(dir=self.tmp))

    def export(self, name="a.zip"):
        path = self.dir / name
        bk.write_backup(path, self.admin)
        return path


class RoundTripTests(BackupTestBase):
    def test_restore_brings_back_exactly_what_was_saved(self):
        path = self.export()
        self.creditor.name = "Changed"
        self.creditor.save()
        Creditor.objects.create(user=self.admin, name="Added after the backup")
        Pond.all_objects.filter(pk=self.pond.pk).delete()

        bk.restore_backup(bk.read_backup(path))

        self.assertEqual(Creditor.objects.get(pk=self.creditor.pk).name, "Dutch-Bangla Bank")
        self.assertFalse(Creditor.objects.filter(name="Added after the backup").exists())
        self.assertTrue(Pond.all_objects.filter(pk=self.pond.pk, name="East pond").exists())

    def test_exporting_after_a_restore_gives_the_same_data(self):
        first = self.export("first.zip")
        bk.restore_backup(bk.read_backup(first))
        self.assertEqual(data_of(first), data_of(self.export("second.zip")))

    def test_times_just_past_a_whole_second_survive_the_round_trip(self):
        # Stored to the millisecond, 0.0004 s past a second is written ".000"; read back it's exactly on
        # the second. Both must export the same, or a backup of restored data looks different.
        from datetime import datetime, timezone as tz

        Pond.all_objects.filter(pk=self.pond.pk).update(created_at=datetime(2026, 1, 2, 3, 4, 5, 400, tzinfo=tz.utc))
        first = self.export("first.zip")
        self.assertIn(b'"2026-01-02T03:04:05Z"', data_of(first))
        bk.restore_backup(bk.read_backup(first))
        self.assertEqual(data_of(first), data_of(self.export("second.zip")))

    def test_restoring_twice_never_duplicates(self):
        path = self.export()
        before = bk.current_counts()
        bk.restore_backup(bk.read_backup(path), keep_copy=False)
        bk.restore_backup(bk.read_backup(path), keep_copy=False)
        self.assertEqual(bk.current_counts(), before)
        self.assertEqual(Creditor.objects.filter(name="Dutch-Bangla Bank").count(), 1)

    def test_soft_deleted_records_come_back_too(self):
        self.pond.is_deleted = True
        self.pond.save()
        path = self.export()
        Pond.all_objects.all().delete()
        bk.restore_backup(bk.read_backup(path))
        self.assertTrue(Pond.all_objects.get(pk=self.pond.pk).is_deleted)

    def test_new_records_after_a_restore_get_fresh_ids(self):
        path = self.export()
        bk.restore_backup(bk.read_backup(path))
        new = Creditor.objects.create(user=self.admin, name="Next")
        self.assertGreater(new.pk, self.creditor.pk)

    def test_passwords_and_profiles_come_back(self):
        path = self.export()
        self.admin.set_password("other")
        self.admin.save()
        bk.restore_backup(bk.read_backup(path))
        admin = get_user_model().objects.get(username="boss")
        self.assertTrue(admin.check_password("pw-boss-1"))
        self.assertEqual(admin.profile.pk, self.admin.profile.pk)      # one profile, not a second one

    def test_uploaded_photos_come_back(self):
        path = self.export()
        name = Pond.objects.get(pk=self.pond.pk).photo.name
        default_storage.delete(name)
        bk.restore_backup(bk.read_backup(path))
        with default_storage.open(name) as fh:
            self.assertEqual(fh.read(), b"\xff\xd8 pond photo")

    def test_group_permissions_follow_their_names_not_ids(self):
        """Permission ids differ between servers; the backup maps them by name."""
        perm = Permission.objects.get(codename="change_user")
        group = Group.objects.create(name="Helpers")
        group.permissions.add(perm)
        moved = rewrite(self.export(), self.dir / "moved.zip", lambda m, rows: self._shift_permission_ids(m, rows))
        group.permissions.clear()
        bk.restore_backup(bk.read_backup(moved))
        self.assertEqual(list(Group.objects.get(name="Helpers").permissions.values_list("codename", flat=True)), ["change_user"])

    @staticmethod
    def _shift_permission_ids(manifest, rows):
        """Pretend the backup came from a server where every permission id was 5000 higher."""
        manifest["refs"]["permission"] = {str(int(k) + 5000): v for k, v in manifest["refs"]["permission"].items()}
        for r in rows:
            if r["model"] == "auth.group":
                r["fields"]["permissions"] = [p + 5000 for p in r["fields"]["permissions"]]

    def test_a_copy_of_the_current_data_is_kept_first(self):
        path = self.export()
        result = bk.restore_backup(bk.read_backup(path))
        self.assertTrue(result["safety_copy"].name.startswith("before-restore-"))
        self.assertEqual(bk.read_backup(result["safety_copy"]).counts, bk.current_counts())

    def test_everyone_is_signed_out(self):
        self.client.force_login(self.owner)
        bk.restore_backup(bk.read_backup(self.export()))
        self.assertEqual(self.client.get(reverse("networth")).status_code, 302)


class RefusedBackupTests(BackupTestBase):
    def assertRefusedAndUnchanged(self, path, words):
        before = bk.current_counts()
        with self.assertRaises(bk.BackupError) as ctx:
            bk.restore_backup(bk.read_backup(path), keep_copy=False)
        self.assertIn(words, str(ctx.exception))
        self.assertEqual(bk.current_counts(), before)
        self.assertEqual(Creditor.objects.get(pk=self.creditor.pk).name, "Dutch-Bangla Bank")

    def test_not_a_backup(self):
        path = self.dir / "photo.zip"
        path.write_bytes(b"not a zip")
        self.assertRefusedAndUnchanged(path, "not a FinTrack backup")

    def test_a_file_changed_after_download(self):
        src = self.export()
        bad = self.dir / "edited.zip"
        with zipfile.ZipFile(src) as z, zipfile.ZipFile(bad, "w") as out:
            for n in z.namelist():
                blob = z.read(n)
                out.writestr(n, blob.replace(b"Dutch-Bangla Bank", b"Hacked Bank Ltd!!") if n == "data.json" else blob)
        self.assertRefusedAndUnchanged(bad, "changed")

    def test_records_that_dont_fit_together_undo_everything(self):
        """A record pointing at a person who isn't in the backup: the whole restore is rolled back."""
        def orphan(manifest, rows):
            for r in rows:
                if r["model"] == "creditors.creditor":
                    r["fields"]["user"] = 999999
        self.assertRefusedAndUnchanged(rewrite(self.export(), self.dir / "orphan.zip", orphan), "don't fit together")

    def test_counts_must_match_the_contents_list(self):
        def drop_one(manifest, rows):
            rows[:] = [r for r in rows if r["model"] != "creditors.creditor"]
        self.assertRefusedAndUnchanged(rewrite(self.export(), self.dir / "short.zip", drop_one), "damaged")

    def test_a_backup_from_a_newer_version(self):
        def newer(manifest, rows):
            manifest["migrations"]["creditors"].append("9999_from_the_future")
        self.assertRefusedAndUnchanged(rewrite(self.export(), self.dir / "newer.zip", newer), "newer version")

    def test_an_older_backup_that_only_misses_new_tables_is_accepted(self):
        def older(manifest, rows):
            manifest["migrations"]["accounts"].remove("0003_userprofile_view_mode")
        backup = bk.read_backup(rewrite(self.export(), self.dir / "older.zip", older))
        self.assertTrue(backup.notes)

    def test_an_older_backup_across_a_data_change_is_refused(self):
        """A later update that changed existing data (RunPython) can't be replayed on old data."""
        from django.db.migrations.loader import MigrationLoader
        from django.db import connection
        from django.db.migrations.operations.special import RunPython

        loader = MigrationLoader(connection)
        key = next((k for k, m in sorted(loader.graph.nodes.items()) if k[0].startswith(("creditors", "business")) and any(isinstance(o, RunPython) for o in m.operations)), None)
        if key is None:
            self.skipTest("no data migration to test with")

        def older(manifest, rows):
            manifest["migrations"][key[0]].remove(key[1])
        self.assertRefusedAndUnchanged(rewrite(self.export(), self.dir / "old.zip", older), "older version")

    def test_a_backup_without_an_admin(self):
        def no_admin(manifest, rows):
            for r in rows:
                if r["model"] == "auth.user":
                    r["fields"]["is_superuser"] = False
        self.assertRefusedAndUnchanged(rewrite(self.export(), self.dir / "noadmin.zip", no_admin), "no active admin")

    def test_files_outside_the_media_folder_are_refused(self):
        src = self.export()
        bad = rewrite(src, self.dir / "slip.zip", lambda m, rows: m["files"].update({"../evil.txt": {"sha256": bk._sha256(b"x"), "size": 1}}))
        with zipfile.ZipFile(bad, "a") as z:
            z.writestr("../evil.txt", b"x")
        self.assertRefusedAndUnchanged(bad, "damaged")

    def test_unknown_tables_are_refused(self):
        def session(manifest, rows):
            rows.append({"model": "sessions.session", "pk": "x", "fields": {}})
            manifest["counts"]["sessions.session"] = 1
        self.assertRefusedAndUnchanged(rewrite(self.export(), self.dir / "sess.zip", session), "doesn't know")


class BackupPageTests(BackupTestBase):
    def test_only_site_admins(self):
        for user in (self.owner, self.staff):
            self.client.force_login(user)
            self.assertEqual(self.client.get(reverse("backup_home")).status_code, 403)
            self.assertEqual(self.client.post(reverse("backup_download")).status_code, 403)
            self.assertEqual(self.client.post(reverse("backup_restore")).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(reverse("backup_home")).status_code, 302)

    def test_the_admin_menu_links_to_it_only_for_admins(self):
        self.client.force_login(self.owner)
        self.assertNotIn(reverse("backup_home"), self.client.get(reverse("networth")).content.decode())
        self.client.force_login(self.admin)
        self.assertIn(reverse("backup_home"), self.client.get(reverse("networth")).content.decode())

    def test_download(self):
        self.client.force_login(self.admin)
        r = self.client.post(reverse("backup_download"))
        self.assertEqual(r["Content-Type"], "application/zip")
        self.assertIn("attachment", r["Content-Disposition"])
        path = self.dir / "dl.zip"
        path.write_bytes(b"".join(r.streaming_content))
        self.assertEqual(bk.read_backup(path).counts, bk.current_counts())

    def test_upload_check_and_restore(self):
        path = self.export()
        self.creditor.name = "Changed"
        self.creditor.save()
        self.client.force_login(self.admin)
        with open(path, "rb") as fh:
            r = self.client.post(reverse("backup_upload"), {"backup": fh})
        self.assertRedirects(r, reverse("backup_preview"))
        page = self.client.get(reverse("backup_preview")).content.decode()
        self.assertIn("boss", page)
        self.assertEqual(Creditor.objects.get(pk=self.creditor.pk).name, "Changed")      # nothing yet

        r = self.client.post(reverse("backup_restore"), {"confirm": "yes", "password": "wrong"})
        self.assertRedirects(r, reverse("backup_preview"))
        self.assertEqual(Creditor.objects.get(pk=self.creditor.pk).name, "Changed")

        r = self.client.post(reverse("backup_restore"), {"confirm": "yes", "password": "pw-boss-1"})
        self.assertRedirects(r, reverse("login"), fetch_redirect_response=False)
        self.assertEqual(Creditor.objects.get(pk=self.creditor.pk).name, "Dutch-Bangla Bank")
        self.assertTrue(self.client.login(username="boss", password="pw-boss-1"))

    def test_a_bad_upload_is_explained_and_changes_nothing(self):
        self.client.force_login(self.admin)
        r = self.client.post(reverse("backup_upload"), {"backup": io.BytesIO(b"nope")}, follow=True)
        self.assertContains(r, "not a FinTrack backup")

    def test_server_copies(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("backup_save"))
        name = bk.server_backups()[0]["name"]
        self.assertContains(self.client.get(reverse("backup_home")), name)
        r = self.client.get(reverse("backup_file", args=[name]))
        self.assertEqual(r["Content-Type"], "application/zip")
        self.assertEqual(self.client.get(reverse("backup_file", args=["..%2Fsettings.py"])).status_code, 404)
        self.client.post(reverse("backup_delete", args=[name]))
        self.assertEqual(bk.server_backups(), [])
