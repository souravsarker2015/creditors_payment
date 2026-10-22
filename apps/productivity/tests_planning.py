"""What came in from the big task trackers: saved views, "blocked by",
richer repeats, task activity and comments, the urgent × important matrix,
the timeline — and the focus session that's saved once."""
import io
from datetime import date, timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from . import services
from .models import Priority, Project, Repeat, SavedView, Status, Task, TaskActivity, TimeEntry

PW = "Str0ng-pass-123"
TODAY = timezone.localdate()


class Base(TestCase):
    def setUp(self):
        self.me = User.objects.create_superuser("me", "me@example.com", PW)
        self.client.force_login(self.me)

    def task(self, title, **kw):
        return Task.objects.create(owner=self.me, title=title, **kw)


class RepeatTests(Base):
    def test_next_dates(self):
        thu = date(2026, 10, 22)
        self.assertEqual(services.next_due(thu, Repeat.DAILY, every=3), date(2026, 10, 25))
        self.assertEqual(services.next_due(thu, Repeat.WEEKLY, every=2), date(2026, 11, 5))
        self.assertEqual(services.next_due(thu, Repeat.WEEKLY, days="0,4"), date(2026, 10, 23))        # Friday, same week
        self.assertEqual(services.next_due(date(2026, 10, 23), Repeat.WEEKLY, days="0,4"), date(2026, 10, 26))   # then Monday
        self.assertEqual(services.next_due(date(2026, 10, 23), Repeat.WEEKLY, every=2, days="1,3"), date(2026, 11, 3))
        self.assertEqual(services.next_due(date(2026, 1, 31), Repeat.MONTHLY, every=3), date(2026, 4, 30))
        self.assertEqual(services.next_due(date(2024, 2, 29), Repeat.YEARLY), date(2025, 2, 28))

    def test_quick_add_words(self):
        p = services.parse_quick("Water the plants every! 3 days", TODAY)
        self.assertEqual((p.title, p.repeat, p.repeat_every, p.repeat_from_done), ("Water the plants", Repeat.DAILY, 3, True))
        p = services.parse_quick("Standup every mon, wed and fri", TODAY)
        self.assertEqual((p.title, p.repeat, p.repeat_days), ("Standup", Repeat.WEEKLY, "0,2,4"))
        self.assertLessEqual(p.due - TODAY, timedelta(days=6))
        self.assertEqual(services.parse_quick("Renew the domain every year", TODAY).repeat, Repeat.YEARLY)
        self.assertEqual(services.parse_quick("1:1 every 2 weeks", TODAY).repeat_every, 2)

    def test_the_next_one_keeps_the_rule(self):
        t = self.task("Review", due_date=TODAY - timedelta(days=2), start_date=TODAY - timedelta(days=4), repeat=Repeat.WEEKLY, repeat_every=2)
        nxt = services.set_done(t)
        self.assertEqual((nxt.due_date, nxt.start_date, nxt.repeat_every), (TODAY + timedelta(days=12), TODAY + timedelta(days=10), 2))
        t2 = self.task("Plants", due_date=TODAY - timedelta(days=5), repeat=Repeat.DAILY, repeat_every=3, repeat_from_done=True)
        self.assertEqual(services.set_done(t2).due_date, TODAY + timedelta(days=3))         # from today, not from 5 days ago
        self.assertIn("from when it's done", services.repeat_text(t2))

    def test_the_task_form(self):
        url = reverse("work:task_new")
        r = self.client.post(url, {"title": "Gym", "status": "todo", "priority": 0, "repeat": "weekly", "repeat_every": 1,
                                   "repeat_on": ["1", "3"], "due_date": TODAY.isoformat()})
        t = Task.objects.get(title="Gym")
        self.assertEqual(t.repeat_days, "1,3")
        r = self.client.post(url, {"title": "Bad", "status": "todo", "priority": 0, "repeat_every": 1,
                                   "start_date": TODAY.isoformat(), "due_date": (TODAY - timedelta(days=1)).isoformat()})
        self.assertContains(r, "The start can")


class BlockedTests(Base):
    def setUp(self):
        super().setUp()
        self.design, self.build, self.ship = self.task("Design"), self.task("Build"), self.task("Ship")

    def block(self, task, other):
        return self.client.post(reverse("work:api_task_blockers", args=[task.pk]), {"add": other.pk}).json()

    def test_blocking_and_being_told_when_ready(self):
        self.assertTrue(self.block(self.build, self.design)["blocked"])
        self.block(self.ship, self.build)
        self.assertFalse(self.block(self.design, self.ship)["ok"])                  # no circles
        self.assertTrue(Task.objects.get(pk=self.build.pk).is_blocked)
        res = self.client.post(reverse("work:api_task_done", args=[self.design.pk]), {"done": "1"}).json()
        self.assertEqual(res["unblocked"], ["Build"])
        self.assertFalse(Task.objects.get(pk=self.build.pk).is_blocked)
        words = [a.words for a in TaskActivity.objects.filter(task=self.build)]
        self.assertIn("Ready: “Design” is done", words)
        self.assertIn("Now blocked by “Design”", words)
        self.client.post(reverse("work:api_task_blockers", args=[self.build.pk]), {"remove": self.design.pk})
        self.assertFalse(self.build.blocked_by.exists())

    def test_on_the_list(self):
        self.block(self.build, self.design)
        r = self.client.get(reverse("work:tasks") + "?view=list")
        self.assertContains(r, 'data-group="blocked"')
        self.assertContains(r, "wt-blocked")
        r = self.client.get(reverse("work:tasks") + "?view=list&blocked=yes")
        self.assertEqual([t.title for _k, _l, items, _n in r.context["groups"] for t in items], ["Build"])
        r = self.client.get(reverse("work:tasks") + "?view=list&blocked=no")
        self.assertNotIn("Build", [t.title for _k, _l, items, _n in r.context["groups"] for t in items])

    def test_someone_elses_task_cant_be_used(self):
        other = User.objects.create_user("o", password=PW)
        theirs = Task.objects.create(owner=other, title="Theirs")
        self.assertEqual(self.client.post(reverse("work:api_task_blockers", args=[self.build.pk]), {"add": theirs.pk}).status_code, 404)


class ActivityTests(Base):
    def test_changes_are_noted(self):
        p = Project.objects.create(owner=self.me, name="Launch")
        t = self.task("Write docs")
        t.status, t.priority, t.project, t.due_date = Status.DOING, Priority.HIGH, p, date(2026, 11, 5)
        t.save()
        words = [a.words for a in t.activity.all()]
        self.assertIn("Created this task", words)
        self.assertIn("Status: To do → In progress", words)
        self.assertIn("Priority: No priority → High", words)
        self.assertIn("Project: — → Launch", words)
        self.assertIn("Due date: — → 5 Nov 2026", words)
        t.order = 99
        t.save()                                                                      # moving it about isn't news
        self.assertEqual(t.activity.count(), 5)

    def test_comments(self):
        t = self.task("Bug")
        r = self.client.post(reverse("work:api_task_comment", args=[t.pk]), {"text": "Seen on https://example.com"}).json()
        self.assertIn('href="https://example.com"', r["html"])
        c = TaskActivity.objects.get(task=t, kind="comment")
        self.assertContains(self.client.get(reverse("work:task", args=[t.pk])), "Seen on")
        self.assertFalse(self.client.post(reverse("work:api_task_comment", args=[t.pk]), {"text": " "}).json()["ok"])
        other = User.objects.create_superuser("o", "o@example.com", PW)      # can use Productivity, but it's not their task
        self.client.force_login(other)
        self.assertEqual(self.client.post(reverse("work:api_comment_delete", args=[c.pk])).status_code, 404)
        self.client.force_login(self.me)
        self.client.post(reverse("work:api_comment_delete", args=[c.pk]))
        self.assertFalse(TaskActivity.objects.filter(kind="comment").exists())


class ViewsTests(Base):
    def test_saved_views(self):
        res = self.client.post(reverse("work:api_view_save"), {"name": "Urgent", "query": "view=board&priority=3&junk=1"}).json()
        v = SavedView.objects.get()
        self.assertEqual(v.query, "view=board&priority=3")
        self.assertTrue(res["url"].endswith(f"sv={v.pk}"))
        r = self.client.get(reverse("work:tasks") + "?view=list")
        self.assertContains(r, "Urgent")
        self.assertIn(f"view-{v.pk}", [c["id"] for c in r.context["work_config"]["commands"]])
        other = User.objects.create_superuser("o", "o@example.com", PW)
        self.client.force_login(other)
        self.assertEqual(self.client.post(reverse("work:api_view_action", args=[v.pk]), {"action": "delete"}).status_code, 404)
        self.client.force_login(self.me)
        self.client.post(reverse("work:api_view_action", args=[v.pk]), {"action": "delete"})
        self.assertFalse(SavedView.objects.exists())

    def test_matrix(self):
        self.task("Hotfix", priority=Priority.URGENT)
        self.task("Roadmap", priority=Priority.HIGH, due_date=TODAY + timedelta(days=20))
        self.task("Reply to email", due_date=TODAY)
        self.task("Tidy desktop")
        r = self.client.get(reverse("work:tasks") + "?view=matrix")
        got = {key: [t.title for t in items] for key, _l, _h, items in r.context["quadrants"]}
        self.assertEqual(got, {"do": ["Hotfix"], "plan": ["Roadmap"], "quick": ["Reply to email"], "drop": ["Tidy desktop"]})

    def test_timeline(self):
        p = Project.objects.create(owner=self.me, name="Launch")
        self.task("Build", project=p, start_date=TODAY, due_date=TODAY + timedelta(days=6))
        self.task("Undated")
        r = self.client.get(reverse("work:tasks") + "?view=timeline")
        (project, bars), = r.context["tl_rows"]
        self.assertEqual((project, bars[0]["days"], round(bars[0]["width"], 2)), (p, 7, round(700 / 42, 2)))
        self.assertEqual(r.context["tl_undated"], 1)
        self.assertContains(r, "wtl-bar-item")


class FocusSavedOnceTests(Base):
    def test_the_same_session_twice_is_kept_once(self):
        start = timezone.now() - timedelta(minutes=25)
        data = {"started_at": start.isoformat(), "ended_at": timezone.now().isoformat(), "description": "Focus session"}
        self.client.post(reverse("work:api_focus_log"), data)
        self.client.post(reverse("work:api_focus_log"), data)            # another tab, or a retry
        self.assertEqual(TimeEntry.objects.filter(kind="focus").count(), 1)

    def test_the_timer_pill_is_on_every_page_but_focus(self):
        self.assertContains(self.client.get(reverse("work:tasks")), "data-focus-pill")
        self.assertNotContains(self.client.get(reverse("work:focus")), "data-focus-pill")


class BackupTests(Base):
    def test_blockers_activity_and_views_come_back(self):
        a, b = self.task("A"), self.task("B")
        b.blocked_by.add(a)
        TaskActivity.objects.create(task=b, kind="comment", text="Note to self")
        SavedView.objects.create(owner=self.me, name="Mine", query="priority=3")
        blob = self.client.get(reverse("work:export")).content
        other = User.objects.create_superuser("other", "o@example.com", PW)
        self.client.force_login(other)
        upload = io.BytesIO(blob)
        upload.name = "backup.zip"
        self.client.post(reverse("work:settings"), {"action": "restore", "backup": upload})
        nb = Task.objects.get(owner=other, title="B")
        self.assertEqual([t.title for t in nb.blocked_by.all()], ["A"])
        self.assertEqual(nb.activity.filter(data__field="created").count(), 1)       # not a second "created"
        self.assertTrue(nb.activity.filter(kind="comment", text="Note to self").exists())
        self.assertTrue(SavedView.objects.filter(owner=other, name="Mine").exists())
