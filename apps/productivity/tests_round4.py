"""Ticking off from the task's own form, subtasks moving with their task,
time and estimates added up over subtasks, the list grouped and sorted,
files kept with a task, and the calendar moving a task to another day."""
import shutil
import tempfile
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.trash.models import DeletedItem
from apps.trash.services import forget, restore

from .models import Priority, Project, Repeat, Status, Task, TaskActivity, TaskFile, TimeEntry

PW = "Str0ng-pass-123"
TODAY = timezone.localdate()


class Base(TestCase):
    def setUp(self):
        self.me = User.objects.create_superuser("me", "me@example.com", PW)
        self.client.force_login(self.me)

    def task(self, title, **kw):
        return Task.objects.create(owner=self.me, title=title, **kw)

    def form(self, task, **changes):
        data = {"title": task.title, "status": task.status, "priority": task.priority, "repeat": task.repeat,
                "repeat_every": task.repeat_every, "due_date": task.due_date.isoformat() if task.due_date else "",
                "project": task.project_id or "", "parent": task.parent_id or ""}
        data.update(changes)
        return self.client.post(reverse("work:task", args=[task.pk]), data)


class FormDoneTests(Base):
    def test_done_on_the_form_leaves_the_next_repeat_closes_subtasks_and_stops_the_timer(self):
        t = self.task("Pay rent", repeat=Repeat.MONTHLY, due_date=TODAY)
        sub = self.task("Get the receipt", parent=t)
        TimeEntry.objects.create(owner=self.me, task=t, started_at=timezone.now() - timedelta(minutes=5))
        r = self.form(t, status=Status.DONE)
        self.assertEqual(r.status_code, 302)
        t.refresh_from_db(); sub.refresh_from_db()
        self.assertEqual((t.status, sub.status), (Status.DONE, Status.DONE))
        self.assertIsNotNone(t.completed_at)
        nxt = Task.objects.exclude(pk__in=[t.pk, sub.pk]).get()
        self.assertEqual((nxt.title, nxt.status), ("Pay rent", Status.TODO))
        self.assertGreater(nxt.due_date, TODAY)
        self.assertFalse(TimeEntry.objects.filter(ended_at__isnull=True).exists())

    def test_reopened_on_the_form_into_in_progress(self):
        t = self.task("Ship", status=Status.DONE, completed_at=timezone.now())
        self.form(t, status=Status.DOING, title="Ship it")
        t.refresh_from_db()
        self.assertEqual((t.status, t.completed_at, t.title), (Status.DOING, None, "Ship it"))
        self.assertEqual(Task.objects.count(), 1)

    def test_saving_a_done_task_again_keeps_when_it_was_done(self):
        when = timezone.now() - timedelta(days=3)
        t = self.task("Old", status=Status.DONE, completed_at=when)
        self.form(t, title="Old one")
        t.refresh_from_db()
        self.assertEqual(t.completed_at, when)

    def test_a_new_task_made_done(self):
        self.client.post(reverse("work:task_new"), {"title": "Logged", "status": Status.DONE, "priority": 0, "repeat": ""})
        self.assertIsNotNone(Task.objects.get(title="Logged").completed_at)


class SubtaskFollowAndRollupTests(Base):
    def test_subtasks_move_with_their_task_to_another_project(self):
        a = Project.objects.create(owner=self.me, name="A")
        b = Project.objects.create(owner=self.me, name="B")
        other = Project.objects.create(owner=self.me, name="Other")
        t = self.task("Parent", project=a)
        s1 = self.task("Same project", parent=t, project=a)
        s2 = self.task("Its own project", parent=t, project=other)
        self.form(t, project=b.pk)
        s1.refresh_from_db(); s2.refresh_from_db()
        self.assertEqual((s1.project, s2.project), (b, other))
        # and from the quick menus too
        self.client.post(reverse("work:api_task_update", args=[t.pk]), {"project": a.pk})
        s1.refresh_from_db()
        self.assertEqual(s1.project, a)

    def test_time_and_estimates_add_up_over_subtasks(self):
        t = self.task("Parent", estimate_minutes=30)
        s = self.task("Child", parent=t, estimate_minutes=90)
        now = timezone.now()
        TimeEntry.objects.create(owner=self.me, task=t, started_at=now - timedelta(hours=2), ended_at=now - timedelta(hours=1))
        TimeEntry.objects.create(owner=self.me, task=s, started_at=now - timedelta(minutes=30), ended_at=now)
        r = self.client.get(reverse("work:task", args=[t.pk]))
        self.assertEqual(r.context["with_subs"], {"spent": 5400, "estimate": 120})
        self.assertContains(r, "wtd-rollup")
        self.assertIsNone(self.client.get(reverse("work:task", args=[s.pk])).context["with_subs"])


class GroupSortTests(Base):
    def setUp(self):
        super().setUp()
        self.p = Project.objects.create(owner=self.me, name="Site")
        self.a = self.task("b task", project=self.p, priority=Priority.HIGH, due_date=TODAY + timedelta(days=5))
        self.b = self.task("A task", priority=Priority.URGENT, status=Status.DOING)
        self.c = self.task("c task", project=self.p, due_date=TODAY + timedelta(days=1), waiting_for="Rahim")

    def groups(self, **params):
        r = self.client.get(reverse("work:tasks"), {"view": "list", **params})
        return [(key, [t.title for t in items]) for key, label, items, total in r.context["groups"]]

    def test_by_project(self):
        self.assertEqual(self.groups(by="project"), [(f"p{self.p.pk}", ["b task", "c task"]), ("p-none", ["A task"])])

    def test_by_priority_and_status(self):
        self.assertEqual([k for k, _ in self.groups(by="priority")], ["pr4", "pr3", "pr0"])
        self.assertEqual(dict(self.groups(by="status"))["doing"], ["A task"])

    def test_sorted(self):
        self.assertEqual(self.groups(by="project", sort="title")[0][1], ["b task", "c task"])
        self.assertEqual(self.groups(by="project", sort="due")[0][1], ["c task", "b task"])
        self.assertEqual(self.groups(by="status", sort="priority")[1][1], ["b task", "c task"])

    def test_one_group_opens_and_odd_values_are_ignored(self):
        self.assertEqual(self.groups(by="project", group="p-none"), [("p-none", ["A task"])])
        self.assertEqual(self.client.get(reverse("work:tasks"), {"by": "nonsense", "sort": "x"}).status_code, 200)

    def test_a_grouping_can_be_saved_as_a_view(self):
        res = self.client.post(reverse("work:api_view_save"), {"name": "By project", "query": "view=list&by=project&sort=due&junk=1"}).json()
        self.assertIn("by=project&sort=due", res["url"])
        self.assertNotIn("junk", res["url"])
        r = self.client.get(reverse("work:tasks"), {"view": "list", "by": "project"})
        self.assertContains(r, "data-save-view")


class TaskFileTests(Base):
    def setUp(self):
        super().setUp()
        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()
        self.t = self.task("Brief")

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)

    def up(self, *files, task=None):
        return self.client.post(reverse("work:api_task_files", args=[(task or self.t).pk]), {"file": list(files)}).json()

    def test_files_are_kept_shown_and_only_for_their_owner(self):
        res = self.up(SimpleUploadedFile("spec v2.pdf", b"%PDF-1.4 hello"), SimpleUploadedFile("shot.png", b"\x89PNG\r\n\x1a\n" + b"\0" * 20))
        self.assertTrue(res["ok"])
        self.assertEqual(res["count"], 2)
        pdf = TaskFile.objects.get(name="spec v2.pdf")
        png = TaskFile.objects.get(name="shot.png")
        self.assertTrue(png.is_image and not pdf.is_image)
        r = self.client.get(reverse("work:task_file", args=[pdf.pk]))
        self.assertEqual(b"".join(r.streaming_content), b"%PDF-1.4 hello")
        self.assertIn("attachment", r["Content-Disposition"])
        self.assertIn("spec", r["Content-Disposition"])
        self.assertEqual(r["Content-Type"], "application/octet-stream")
        r = self.client.get(reverse("work:task_file", args=[png.pk]))
        self.assertEqual((r["Content-Type"], r["Content-Disposition"].split(";")[0]), ("image/png", "inline"))
        self.assertIn("sandbox", r["Content-Security-Policy"])
        page = self.client.get(reverse("work:task", args=[self.t.pk]))
        self.assertContains(page, "spec v2.pdf")
        self.assertEqual(TaskActivity.objects.filter(task=self.t, data__field="file").count(), 2)
        other = User.objects.create_superuser("other", "o@example.com", PW)
        self.client.force_login(other)
        self.assertEqual(self.client.get(reverse("work:task_file", args=[pdf.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("work:api_task_files", args=[self.t.pk]), {"file": SimpleUploadedFile("x.txt", b"x")}).status_code, 404)
        self.assertEqual(self.client.post(reverse("work:api_task_file_delete", args=[pdf.pk])).status_code, 404)

    def test_too_big_and_none(self):
        from . import api
        old = api.FILE_MAX_MB
        api.FILE_MAX_MB = 0
        try:
            res = self.client.post(reverse("work:api_task_files", args=[self.t.pk]), {"file": SimpleUploadedFile("big.zip", b"12345")})
        finally:
            api.FILE_MAX_MB = old
        self.assertEqual(res.status_code, 400)
        self.assertIn("big.zip", res.json()["error"])
        self.assertEqual(self.client.post(reverse("work:api_task_files", args=[self.t.pk])).status_code, 400)
        self.assertFalse(TaskFile.objects.exists())

    def test_removed_file_is_gone_from_disk(self):
        self.up(SimpleUploadedFile("notes.txt", b"hi"))
        tf = TaskFile.objects.get()
        path = tf.file.path
        res = self.client.post(reverse("work:api_task_file_delete", args=[tf.pk])).json()
        self.assertEqual(res["count"], 0)
        import os
        self.assertFalse(os.path.exists(path))
        self.assertFalse(TaskFile.objects.exists())

    def test_a_deleted_task_comes_back_with_its_files_and_emptying_the_trash_removes_them(self):
        import os
        self.up(SimpleUploadedFile("plan.docx", b"doc"))
        path = TaskFile.objects.get().file.path
        self.client.post(reverse("work:api_task_delete", args=[self.t.pk]))
        self.assertFalse(TaskFile.objects.exists())
        self.assertTrue(os.path.exists(path))
        restore(DeletedItem.objects.get())
        self.assertEqual(TaskFile.objects.get().name, "plan.docx")
        self.client.post(reverse("work:api_task_delete", args=[self.t.pk]))
        forget(DeletedItem.objects.all())
        self.assertFalse(os.path.exists(path))

    def test_files_are_in_the_export(self):
        import io
        import zipfile
        self.up(SimpleUploadedFile("brief.pdf", b"pdf"))
        z = zipfile.ZipFile(io.BytesIO(self.client.get(reverse("work:export")).content))
        names = [n for n in z.namelist() if n.startswith("tasks/files/")]
        self.assertEqual(len(names), 1)
        self.assertTrue(names[0].endswith("-brief.pdf"))


class CalendarMoveTests(Base):
    def test_calendar_moves_a_task_and_keeps_its_start_before_its_due_date(self):
        t = self.task("Report", start_date=TODAY + timedelta(days=3), due_date=TODAY + timedelta(days=5))
        # the month the task is due in: near the end of a month that's the next one
        r = self.client.get(reverse("work:calendar"), {"month": t.due_date.strftime("%Y-%m")})
        self.assertContains(r, 'draggable="true"')
        self.assertContains(r, "wcal-move")
        self.client.post(reverse("work:api_task_update", args=[t.pk]), {"due_date": (TODAY + timedelta(days=1)).isoformat()})
        t.refresh_from_db()
        self.assertEqual((t.start_date, t.due_date), (TODAY + timedelta(days=1), TODAY + timedelta(days=1)))
        self.client.post(reverse("work:api_task_update", args=[t.pk]), {"due_date": (TODAY + timedelta(days=9)).isoformat()})
        t.refresh_from_db()
        self.assertEqual(t.start_date, TODAY + timedelta(days=1))
