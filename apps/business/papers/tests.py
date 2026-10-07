import io
import zipfile
from datetime import date, timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.business.core.models import AuditLog, Membership, Role
from apps.business.core.testing import make_farm

from .models import FarmPaper

TODAY = date.today()


class PaperTests(TestCase):
    def setUp(self):
        self.b, self.owner, self.staff = make_farm()
        self.client.force_login(self.owner)

    def add(self, **kw):
        return FarmPaper.objects.create(business=self.b, **{"title": "Trade licence", **kw})

    def test_state_from_the_expiry_date(self):
        self.assertEqual(self.add(expires_on=TODAY - timedelta(days=1)).state, "expired")
        self.assertEqual(self.add(expires_on=TODAY + timedelta(days=10)).state, "soon")
        self.assertEqual(self.add(expires_on=TODAY + timedelta(days=10), remind_days=5).state, "valid")
        self.assertEqual(self.add().state, "forever")

    def test_add_with_photo_and_open_it_privately(self):
        with self.settings(MEDIA_ROOT=self._tmp()):
            r = self.client.post(reverse("business:papers_add"), {
                "title": "Farm registration", "kind": "fishery", "number": "UFO-12", "expires_on": (TODAY + timedelta(days=200)).isoformat(),
                "remind_days": "30", "file": SimpleUploadedFile("reg.jpg", b"\xff\xd8\xff\xe0jpeg", content_type="image/jpeg")})
            self.assertEqual(r.status_code, 302)
            p = FarmPaper.objects.get()
            self.assertTrue(p.file.name.startswith(f"business/{self.b.pk}/papers/"))
            r = self.client.get(reverse("business:paper_file", args=[p.pk]))
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r["Content-Type"], "image/jpeg")
            r.close()
            self.client.force_login(self.staff)                         # data entry: no papers
            self.assertEqual(self.client.get(reverse("business:paper_file", args=[p.pk])).status_code, 403)
            self.assertNotEqual(self.client.get(reverse("business:papers")).status_code, 200)

    def test_other_farm_cannot_open_it(self):
        p = self.add(file="business/1/papers/x.jpg")
        other, other_owner, _ = make_farm("other")
        self.client.force_login(other_owner)
        self.assertEqual(self.client.get(reverse("business:paper_file", args=[p.pk])).status_code, 404)

    def test_expiry_before_issue_is_refused(self):
        r = self.client.post(reverse("business:papers_add"), {"title": "X", "kind": "trade", "remind_days": "30",
                                                            "issued_on": TODAY.isoformat(), "expires_on": (TODAY - timedelta(days=1)).isoformat()})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(FarmPaper.objects.exists())

    def test_home_reminds_owner_not_staff(self):
        self.add(title="Trade licence 2026", expires_on=TODAY + timedelta(days=7))
        self.add(title="Old lease", expires_on=TODAY - timedelta(days=3))
        self.add(title="Far away", expires_on=TODAY + timedelta(days=300))
        r = self.client.get(reverse("business:home"))
        self.assertContains(r, "Renew: Trade licence 2026")
        self.assertContains(r, "Renew: Old lease")
        self.assertNotContains(r, "Renew: Far away")
        self.client.force_login(self.staff)
        self.assertNotContains(self.client.get(reverse("business:home")), "Renew:")

    def test_list_groups_by_state(self):
        self.add(title="A", expires_on=TODAY - timedelta(days=3))
        self.add(title="B", expires_on=TODAY + timedelta(days=300))
        r = self.client.get(reverse("business:papers"))
        self.assertContains(r, "Expired")
        self.assertContains(r, "Valid")

    def _tmp(self):
        import tempfile

        d = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(d, ignore_errors=True))
        return d


class ExportTests(TestCase):
    def setUp(self):
        self.b, self.owner, self.staff = make_farm()

    def test_owner_downloads_every_record(self):
        from apps.business.ponds.models import Pond

        Pond.objects.create(business=self.b, name="East pond")
        gone = Pond.objects.create(business=self.b, name="Deleted pond")
        gone.soft_delete()
        other, _, _ = make_farm("other")
        Pond.objects.create(business=other, name="Someone else's")
        self.client.force_login(self.owner)
        r = self.client.get(reverse("business:export"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "application/zip")
        z = zipfile.ZipFile(io.BytesIO(r.content))
        ponds = z.read("ponds-pond.csv").decode("utf-8-sig")
        self.assertIn("East pond", ponds)
        self.assertNotIn("Deleted pond", ponds)
        self.assertNotIn("Someone else", ponds)
        self.assertIn("README.txt", z.namelist())
        self.assertTrue(AuditLog.objects.filter(business=self.b, model="export").exists())
        self.assertContains(self.client.get(reverse("business:activity")), "Downloaded all records")

    def test_only_the_owner_may_download(self):
        Membership.objects.filter(business=self.b, user=self.staff).update(role=Role.MANAGER)
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse("business:export")).status_code, 403)
        self.assertNotContains(self.client.get(reverse("business:setup_hub")), "Download all records")
