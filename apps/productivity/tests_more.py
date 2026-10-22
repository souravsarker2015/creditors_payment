"""Subtasks, copies and templates, a project copied, invoices from tracked
time, tasks brought in from other apps (CSV), the board's WIP limit and a
project's burn-up."""
import io
from datetime import date, datetime, time, timedelta
from decimal import Decimal as D

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from . import copying, importer, invoices, services
from .models import Priority, Project, Status, Task, TaskTemplate, TimeEntry, WorkSettings

PW = "Str0ng-pass-123"
TODAY = timezone.localdate()


def at(day, h, m=0):
    return timezone.make_aware(datetime.combine(day, time(h, m)))


class Base(TestCase):
    def setUp(self):
        self.me = User.objects.create_superuser("me", "me@example.com", PW)
        self.client.force_login(self.me)

    def task(self, title, **kw):
        return Task.objects.create(owner=self.me, title=title, **kw)


class SubtaskTests(Base):
    def setUp(self):
        super().setUp()
        self.p = Project.objects.create(owner=self.me, name="Launch")
        self.release = self.task("Release v2", project=self.p)

    def add(self, text, parent=None):
        return self.client.post(reverse("work:api_subtask_add", args=[(parent or self.release).pk]), {"text": text}).json()

    def test_adding_with_quick_add_words(self):
        res = self.add("Write the changelog tomorrow ~30m !high")
        sub = Task.objects.get(pk=res["id"])
        self.assertEqual((sub.parent, sub.project, sub.due_date, sub.estimate_minutes, sub.priority),
                         (self.release, self.p, TODAY + timedelta(days=1), 30, Priority.HIGH))
        self.assertEqual(res["counts"], "0/1")
        self.assertNotIn("wt-parent", res["html"])                     # no "↑ Release v2" on the parent's own page

    def test_one_level_deep(self):
        sub = Task.objects.get(pk=self.add("Tag it")["id"])
        self.assertFalse(self.add("Deeper", parent=sub)["ok"])
        self.assertFalse(services.can_be_parent(self.release, sub))     # a task with subtasks can't become one
        r = self.client.post(reverse("work:task", args=[self.release.pk]), {"title": "Release v2", "status": "todo", "priority": 0, "parent": sub.pk})
        self.assertEqual(r.status_code, 200)                             # the form says no

    def test_finishing_the_task_finishes_its_subtasks(self):
        a, b = (Task.objects.get(pk=self.add(t)["id"]) for t in ("A", "B"))
        services.set_done(a)
        self.assertEqual(Task.objects.get(pk=self.release.pk).subtask_counts, "1/2")
        services.set_done(Task.objects.get(pk=self.release.pk))
        self.assertEqual(Task.objects.get(pk=b.pk).status, Status.DONE)

    def test_the_list_keeps_them_under_their_task(self):
        self.add("Hidden one")
        r = self.client.get(reverse("work:tasks") + "?view=list")
        titles = [t.title for _k, _l, items, _n in r.context["groups"] for t in items]
        self.assertNotIn("Hidden one", titles)
        self.assertContains(r, "wt-subs")
        r = self.client.get(reverse("work:tasks") + "?view=list&sub=1")
        self.assertIn("Hidden one", [t.title for _k, _l, items, _n in r.context["groups"] for t in items])
        self.assertContains(self.client.get(reverse("work:today")), "Release v2")


class CopyTests(Base):
    def setUp(self):
        super().setUp()
        self.p = Project.objects.create(owner=self.me, name="Client A", client="Acme", hourly_rate=D("1500"))
        self.t = self.task("Onboard client", project=self.p, priority=Priority.HIGH, estimate_minutes=90, due_date=TODAY + timedelta(days=5),
                           notes="Steps", status=Status.DONE)
        self.t.checklist.create(text="Send contract", done=True)
        self.task("Kick-off call", parent=self.t, project=self.p, due_date=TODAY + timedelta(days=2))
        self.task("Old step", parent=self.t, project=self.p, status=Status.DONE)

    def test_duplicate(self):
        res = self.client.post(reverse("work:api_task_duplicate", args=[self.t.pk])).json()
        copy = Task.objects.get(pk=res["id"])
        self.assertEqual((copy.title, copy.status, copy.priority, copy.estimate_minutes, copy.notes),
                         ("Onboard client (copy)", Status.TODO, Priority.HIGH, 90, "Steps"))
        self.assertEqual([(c.text, c.done) for c in copy.checklist.all()], [("Send contract", False)])
        self.assertEqual([s.title for s in copy.subtasks.all()], ["Kick-off call"])          # open subtasks only

    def test_template_save_and_use(self):
        self.client.post(reverse("work:api_task_template", args=[self.t.pk]), {"name": "New client"})
        tpl = TaskTemplate.objects.get()
        self.assertEqual((tpl.name, tpl.data["due_in"], len(tpl.data["subtasks"])), ("New client", 5, 1))
        later = TODAY + timedelta(days=30)
        made = copying.use_template(tpl, base=later)
        self.assertEqual((made.due_date, made.project, made.subtasks.get().due_date), (later + timedelta(days=5), self.p, later + timedelta(days=2)))
        r = self.client.post(reverse("work:templates"), {"template": tpl.pk})
        self.assertRedirects(r, reverse("work:task", args=[Task.objects.filter(title="Onboard client").latest("pk").pk]))
        self.assertContains(self.client.get(reverse("work:tasks")), "From a template")
        self.client.post(reverse("work:templates"), {"template": tpl.pk, "action": "delete"})
        self.assertFalse(TaskTemplate.objects.exists())

    def test_copy_a_project(self):
        self.task("Open work", project=self.p, due_date=TODAY)
        r = self.client.post(reverse("work:project_duplicate", args=[self.p.pk]))
        copy = Project.objects.get(name="Client A (copy)")
        self.assertRedirects(r, reverse("work:project", args=[copy.pk]))
        self.assertEqual((copy.client, copy.hourly_rate), ("Acme", D("1500")))
        self.assertEqual([t.title for t in copy.tasks.all()], ["Open work"])                   # open work only, no dates
        self.assertIsNone(copy.tasks.get().due_date)
        self.client.post(reverse("work:project_duplicate", args=[self.p.pk]))
        self.assertTrue(Project.objects.filter(name="Client A (copy 2)").exists())


class InvoiceTests(Base):
    def setUp(self):
        super().setUp()
        self.p = Project.objects.create(owner=self.me, name="Site", client="Acme", hourly_rate=D("2000"))
        self.q = Project.objects.create(owner=self.me, name="App", client="Acme")                 # no rate
        day = TODAY - timedelta(days=2)
        self.build = self.task("Build", project=self.p)
        TimeEntry.objects.create(owner=self.me, project=self.p, task=self.build, started_at=at(day, 9), ended_at=at(day, 10, 30), billable=True)
        TimeEntry.objects.create(owner=self.me, project=self.p, task=self.build, started_at=at(day, 14), ended_at=at(day, 15), billable=True)
        TimeEntry.objects.create(owner=self.me, project=self.p, description="Lunch chat", started_at=at(day, 12), ended_at=at(day, 12, 30))
        TimeEntry.objects.create(owner=self.me, project=self.q, description="Design", started_at=at(day, 16), ended_at=at(day, 17), billable=True)

    def test_lines_and_totals(self):
        inv = invoices.build(self.me, TODAY - timedelta(days=7), TODAY, client="Acme")
        got = [(l.label, l.hours, l.amount) for l in inv.lines]
        self.assertEqual(got, [("Design", D("1.00"), None), ("Build", D("2.50"), D("5000.00"))])
        self.assertEqual((inv.hours, inv.total, inv.unpriced), (D("3.50"), D("5000.00"), D("1.00")))
        self.assertEqual(len(invoices.build(self.me, TODAY - timedelta(days=7), TODAY, project=self.p, billable_only=False).lines), 2)

    def test_billed_once(self):
        url = reverse("work:invoice") + f"?project={self.p.pk}&from={TODAY - timedelta(days=7)}&to={TODAY}"
        r = self.client.get(url)
        self.assertContains(r, "৳5,000")
        self.client.post(url, {"action": "billed"})
        self.assertEqual(TimeEntry.objects.filter(invoiced_at__isnull=False).count(), 2)
        r = self.client.get(url)
        self.assertEqual(r.context["inv"].lines, [])
        self.assertEqual(r.context["inv"].already_billed, 2)
        self.assertEqual(len(self.client.get(url + "&billed=1").context["inv"].lines), 1)
        csv = self.client.get(url + "&billed=1&export=csv").content.decode()
        self.assertIn("Build", csv)

    def test_currency(self):
        s = WorkSettings.for_user(self.me)
        s.currency = "$"
        s.save()
        self.assertContains(self.client.get(reverse("work:invoice") + f"?project={self.p.pk}&from={TODAY - timedelta(days=7)}"), "$5,000.00")


class ImportTests(Base):
    TODOIST = (b"TYPE,CONTENT,DESCRIPTION,PRIORITY,INDENT,AUTHOR,RESPONSIBLE,DATE,DATE_LANG,TIMEZONE\n"
               b"section,Work,,,,,,,,\ntask,Write report,Notes here,4,1,,,2026-10-30,en,\ntask,Buy milk,,1,1,,,,en,\n")
    JIRA = (b"Summary,Issue key,Issue Type,Status,Priority,Due Date,Labels,Description,Project name\n"
            b"Fix login,ABC-1,Bug,In Progress,Highest,22/Oct/26 10:00 AM,backend auth,It loops,Web\n")

    def test_dates(self):
        for raw, want in [("2026-11-05", date(2026, 11, 5)), ("05/11/2026", date(2026, 11, 5)), ("11/25/2026", date(2026, 11, 25)),
                          ("22 Oct 2026", date(2026, 10, 22)), ("Oct 22, 2026", date(2026, 10, 22)), ("31/02/2026", None), ("soon", None)]:
            self.assertEqual(importer.parse_date(raw, date(2026, 10, 1)), want, raw)

    def test_todoist_and_jira(self):
        p = importer.read(self.TODOIST)
        self.assertEqual((p.source, p.skipped, [r["title"] for r in p.rows]), ("todoist", 1, ["Write report", "Buy milk"]))
        self.assertEqual(p.rows[0]["priority"], Priority.URGENT)            # Todoist's 4 is p1
        p = importer.read(self.JIRA)
        r = p.rows[0]
        self.assertEqual((p.source, r["status"], r["priority"], r["tags"], r["project"]), ("jira", Status.DOING, Priority.URGENT, ["backend", "auth"], "Web"))

    def test_no_title_column(self):
        self.assertTrue(importer.read(b"Foo,Bar\n1,2\n").error)

    def test_upload_preview_and_add(self):
        url = reverse("work:import")
        r = self.client.post(url, {"file": SimpleUploadedFile("jira.csv", self.JIRA, content_type="text/csv")})
        self.assertContains(r, "Looks like a Jira export")
        self.assertFalse(Task.objects.exists())                             # nothing added before you say so
        r = self.client.post(url, {"action": "confirm"})
        self.assertRedirects(r, reverse("work:tasks") + "?view=list")
        t = Task.objects.get()
        self.assertEqual((t.title, t.project.name, sorted(t.tags.values_list("name", flat=True))), ("Fix login", "Web", ["auth", "backend"]))
        self.assertEqual(self.client.post(url, {"action": "confirm"}).status_code, 302)    # a second confirm adds nothing
        self.assertEqual(Task.objects.count(), 1)


class BoardAndProjectTests(Base):
    def test_wip_limit(self):
        s = WorkSettings.for_user(self.me)
        s.wip_limit = 1
        s.save()
        self.task("A", status=Status.DOING)
        self.task("B", status=Status.DOING)
        r = self.client.get(reverse("work:tasks") + "?view=board")
        self.assertContains(r, "2 / 1")
        self.assertContains(r, "is-over")
        self.assertEqual(r.context["work_config"]["wip"], 1)

    def test_burnup(self):
        p = Project.objects.create(owner=self.me, name="P")
        for i in range(6):
            t = self.task(f"T{i}", project=p)
            Task.objects.filter(pk=t.pk).update(created_at=timezone.now() - timedelta(days=40))
        for t in Task.objects.filter(project=p)[:4]:
            Task.objects.filter(pk=t.pk).update(status=Status.DONE, completed_at=timezone.now() - timedelta(days=3))
        r = self.client.get(reverse("work:project", args=[p.pk]))
        b = r.context["burnup"]
        self.assertEqual((b["weeks"], b["left"], b["points"][-1]["done"]), (6, 2, 4))
        self.assertIsNotNone(b["eta"])
        self.assertContains(r, "data-burnup")


class BackupTests(Base):
    def test_templates_come_back_pointing_at_the_new_project(self):
        p = Project.objects.create(owner=self.me, name="Launch")
        t = self.task("Ship", project=p)
        copying.save_template(t, "Ship it")
        blob = self.client.get(reverse("work:export")).content
        other = User.objects.create_superuser("other", "o@example.com", PW)
        self.client.force_login(other)
        upload = io.BytesIO(blob)
        upload.name = "backup.zip"
        self.client.post(reverse("work:settings"), {"action": "restore", "backup": upload})
        tpl = TaskTemplate.objects.get(owner=other)
        self.assertEqual(tpl.data["project"], Project.objects.get(owner=other, name="Launch").pk)
