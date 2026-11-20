"""Every table, every backup. A record goes into every table the app has
(backup_testing.fill_every_table, which reads the models — a new feature's
tables are included by themselves), then each kind of backup is made and
restored, and nothing may be missing or changed:

    the whole system      (Backup & restore, for site admins)
    one person's data     (My data & backup)
    the work tracker      (Work → Settings → Your data)

When one of these fails after adding a feature, the new table isn't carried
by that backup — fix the backup, don't skip the table here.
"""
import json
from datetime import timedelta
import shutil
import tempfile
import zipfile
from pathlib import Path

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.business.core.testing import make_farm

from .. import backup as bk
from .. import personal_backup as pb
from ..backup_testing import differences, fill_every_table, fingerprint

# Personal-app tables that aren't one person's: one row for the whole site.
SITE_WIDE = {"accounts.securitysettings"}


class CoverageBase(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="fintrack-coverage-"))
        cls._dirs = override_settings(BACKUP_DIR=cls.tmp / "backups", MEDIA_ROOT=cls.tmp / "media")
        cls._dirs.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._dirs.disable()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.b, self.owner, self.staff = make_farm()
        self.owner.is_superuser = self.owner.is_staff = True
        self.owner.save()
        problems = fill_every_table(self.owner, self.b)
        self.assertEqual(problems, [], "backup_testing couldn't make a row for these tables — add a RECIPE")

    def mine(self, user):
        return {label: n for label, n in pb.counts_for(user).items()}


class WholeSystemTests(CoverageBase):
    def test_every_table_comes_back_exactly(self):
        empty = [m._meta.label_lower for m in bk.backup_models() if not m._base_manager.exists()]
        self.assertEqual(empty, [])
        first = self.tmp / "first.zip"
        bk.write_backup(first, self.owner)
        manifest = json.loads(zipfile.ZipFile(first).read("manifest.json"))
        missing = [m._meta.label_lower for m in bk.backup_models() if not manifest["counts"].get(m._meta.label_lower)]
        self.assertEqual(missing, [], "tables with rows that the backup didn't write")
        files = [n for n in zipfile.ZipFile(first).namelist() if n.startswith("media/")]
        self.assertTrue(files)

        from apps.creditors.models import Creditor          # changes after the backup: all undone by the restore
        Creditor.objects.create(user=self.owner, name="Added after the backup")
        get_user_model().objects.create_user("joined-later", password="x")
        for name in files:
            default_storage.delete(name[len("media/"):])
        bk.restore_backup(bk.read_backup(first))

        second = self.tmp / "second.zip"
        bk.write_backup(second, self.owner)
        self.assertEqual(zipfile.ZipFile(first).read("data.json"), zipfile.ZipFile(second).read("data.json"))
        for name in files:
            self.assertTrue(default_storage.exists(name[len("media/"):]), name)


class MyDataTests(CoverageBase):
    def test_every_personal_table_is_in_my_data(self):
        owned = {m._meta.label_lower for m, _l in pb.owned_models()}
        left_out = sorted(m._meta.label_lower for m in apps.get_models()
                          if pb._personal_app(m) and m._meta.label_lower not in owned | pb.SKIP_MODELS | SITE_WIDE)
        self.assertEqual(left_out, [], "personal tables that “My data” doesn't reach")

    def test_restore_into_another_account_brings_back_every_record(self):
        from ..my_data import build_zip

        before = self.mine(self.owner)
        self.assertEqual([k for k, v in before.items() if not v], [], "personal tables with nothing to back up")
        data, _made = build_zip(self.owner)
        path = self.tmp / "mine.zip"
        path.write_bytes(data)
        other = get_user_model().objects.create_user("someone-else", password="x")
        pb.restore(other, pb.read(path), keep_copy=False)
        self.assertEqual(self.mine(other), before)


class WorkTrackerTests(CoverageBase):
    def test_download_and_add_brings_every_work_table(self):
        work = {label: n for label, n in self.mine(self.owner).items() if label.startswith("productivity.")}
        self.client.force_login(self.owner)
        blob = self.client.get(reverse("work:export")).content
        other = get_user_model().objects.create_superuser("work-other", password="x")
        self.client.force_login(other)
        self.client.post(reverse("work:settings"), {"action": "restore", "backup": SimpleUploadedFile("work.zip", blob)})
        self.maxDiff = None
        got = {label: n for label, n in self.mine(other).items() if label.startswith("productivity.")}
        self.assertEqual({k: got.get(k, 0) for k in work}, work)


class LinksInsideRecordsTests(CoverageBase):
    """Records named by id inside text or JSON follow their record to its new id (relink.py)."""

    def make(self, user):
        from django.core.files.base import ContentFile

        from apps.productivity.models import ExamNote, ExamSubject, Note, NoteImage, PrepExam, PrepTopic, Project, Question, Task, TaskTemplate

        from ..backup_testing import PNG

        img = NoteImage(owner=user, name="cell.png")
        img.file.save("cell.png", ContentFile(PNG), save=True)
        task = Task.objects.create(owner=user, title="Write the report")
        Note.objects.create(owner=user, title="Biology", body=f"![cell](/work/images/{img.pk}/) see /work/tasks/{task.pk}/ and /work/tasks/999999/")
        subject = ExamSubject.objects.create(owner=user, name="Bio")
        ExamNote.objects.create(owner=user, subject=subject, question="A cell?", answer=f"![cell](/work/images/{img.pk}/)")
        topic = PrepTopic.objects.create(owner=user, name="Python links")
        q = Question.objects.create(owner=user, topic=topic, prompt="GIL?")
        PrepExam.objects.create(owner=user, title="Mock", question_ids=[q.pk], answers={str(q.pk): {"text": "a lock"}}, marks={str(q.pk): 1.0})
        project = Project.objects.create(owner=user, name="Linked project")
        TaskTemplate.objects.create(owner=user, name="Tpl", data={"title": "x", "project": project.pk})

    def check(self, user):
        from apps.productivity.models import ExamNote, Note, NoteImage, PrepExam, Project, Question, Task, TaskTemplate

        img = NoteImage.objects.get(owner=user, name="cell.png")
        self.assertTrue(img.file.storage.exists(img.file.name))
        task = Task.objects.get(owner=user, title="Write the report")
        body = Note.objects.get(owner=user, title="Biology").body
        self.assertEqual(body, f"![cell](/work/images/{img.pk}/) see /work/tasks/{task.pk}/ and /work/tasks/999999/")
        self.assertEqual(ExamNote.objects.get(owner=user, question="A cell?").answer, f"![cell](/work/images/{img.pk}/)")
        q = Question.objects.get(owner=user, prompt="GIL?")
        exam = PrepExam.objects.get(owner=user, title="Mock")
        self.assertEqual((exam.question_ids, list(exam.answers), list(exam.marks)), ([q.pk], [str(q.pk)], [str(q.pk)]))
        self.assertEqual(TaskTemplate.objects.get(owner=user, name="Tpl").data["project"], Project.objects.get(owner=user, name="Linked project").pk)
        self.client.force_login(user)
        self.assertEqual(self.client.get(f"/work/images/{img.pk}/").status_code, 200)

    def test_my_data_restore_into_another_account(self):
        from ..my_data import build_zip

        self.make(self.owner)
        data, _made = build_zip(self.owner)
        path = self.tmp / "links.zip"
        path.write_bytes(data)
        other = get_user_model().objects.create_superuser("links-other", password="x")      # may use the work tracker
        pb.restore(other, pb.read(path), keep_copy=False)
        self.check(other)

    def test_work_backup_added_to_another_account(self):
        self.make(self.owner)
        self.client.force_login(self.owner)
        blob = self.client.get(reverse("work:export")).content
        other = get_user_model().objects.create_superuser("links-work", password="x")
        self.client.force_login(other)
        self.client.post(reverse("work:settings"), {"action": "restore", "backup": SimpleUploadedFile("work.zip", blob)})
        self.check(other)


class ExactlyTests(CoverageBase):
    """Not just every table: every field and every link comes back exactly — times to the microsecond, an
    entry still pointing at the right wallet, a task at the right project — through each backup and restore."""

    def setUp(self):
        super().setUp()
        from decimal import Decimal as D

        from apps.cards.models import Card, CardBank, CardEntry, EmiPlan, MfsFees
        from apps.productivity.models import Diagram, Note, NoteCategory, Project, Task, TimeEntry
        from apps.wallets.models import Wallet

        u = self.owner
        early = timezone.now() - timedelta(days=40, microseconds=123457)
        bkash = Wallet.objects.create(user=u, name="bKash two", kind="mobile")
        nagad = Wallet.objects.create(user=u, name="Nagad two", kind="mobile")
        MfsFees.objects.create(wallet=nagad, bill_rate=D("1.25"), bank_rate=D("1.5"), pays_bills=False)
        ebl = CardBank.objects.create(user=u, name="EBL two")
        card = Card.objects.create(user=u, name="Second card", bank=ebl, statement_day=20, due_day=10, transfer_fee_rate=D("1.5"))
        CardEntry.objects.create(card=card, kind="cash", amount=D("5000"), fee=D("75"), fee_rate=D("1.5"), wallet=nagad, date=timezone.localdate())
        CardEntry.objects.create(card=card, kind="pay", amount=D("5075"), fee=D("50.75"), wallet=bkash, route="mfs_bank", date=timezone.localdate())
        EmiPlan.objects.create(card=card, title="Phone", amount=D("30000"), months=6, rate=D("9"), start=timezone.localdate())
        cats = [NoteCategory.objects.create(owner=u, name=f"Shelf {i}") for i in range(2)]
        n = Note.objects.create(owner=u, title="On the second shelf", body="text")
        n.categories.set([cats[1]])
        projects = [Project.objects.create(owner=u, name=f"Project {i}") for i in range(2)]
        t = Task.objects.create(owner=u, title="In the second project", project=projects[1])
        TimeEntry.objects.create(owner=u, task=t, project=projects[1], started_at=early, ended_at=early + timedelta(minutes=25, microseconds=7))
        Diagram.objects.create(owner=u, title="With a picture", kind="mindmap", preview="<svg xmlns='http://www.w3.org/2000/svg'/>")
        Note.objects.filter(pk=n.pk).update(created_at=early, updated_at=early + timedelta(microseconds=1))

    def check(self, before, after):
        self.maxDiff = None
        self.assertEqual(differences(before, after), [])

    def test_the_whole_system(self):
        scope = lambda: [(m, m._base_manager.all()) for m in bk.backup_models()]
        before = fingerprint(scope())
        path = self.tmp / "exact.zip"
        bk.write_backup(path, self.owner)
        bk.restore_backup(bk.read_backup(path))
        self.check(before, fingerprint(scope()))

    def test_my_data_into_another_account(self):
        from ..my_data import build_zip

        scope = lambda user: [(m, m._base_manager.filter(**{lookup: user})) for m, lookup in pb.owned_models()]
        skip = dict(pb.SKIP_FIELDS)
        before = fingerprint(scope(self.owner), skip)
        data, _made = build_zip(self.owner)
        path = self.tmp / "exact-mine.zip"
        path.write_bytes(data)
        other = get_user_model().objects.create_superuser("exact-other", password="x")
        pb.restore(other, pb.read(path), keep_copy=False)
        self.check(before, fingerprint(scope(other), skip))

    def test_the_work_backup_into_another_account(self):
        from apps.productivity.services import KEYS, backup_models

        scope = lambda user: [(m, m._base_manager.filter(**{lookup: user})) for m, lookup in backup_models()]
        skip = {"productivity.worksettings": KEYS}
        before = fingerprint(scope(self.owner), skip)
        self.client.force_login(self.owner)
        blob = self.client.get(reverse("work:export")).content
        other = get_user_model().objects.create_superuser("exact-work", password="x")
        self.client.force_login(other)
        self.client.post(reverse("work:settings"), {"action": "restore", "backup": SimpleUploadedFile("work.zip", blob)})
        self.check(before, fingerprint(scope(other), skip))
