"""Reminders that carry on (repeats, moved due dates), subtasks deleted with
their task, a wider search, the timeline's drag, a backup's subtasks — and
sprints: planning, burndown, closing, velocity."""
import json
from datetime import datetime, time, timedelta

from django.contrib.auth.models import User
from django.core import serializers
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.trash.models import DeletedItem
from apps.trash.services import restore

from . import services, sprints
from .models import Repeat, Sprint, Status, Task, TaskActivity

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

    def update(self, task, **data):
        return self.client.post(reverse("work:api_task_update", args=[task.pk]), data).json()


class ReminderTests(Base):
    def test_the_next_repeat_keeps_its_reminder_as_many_days_before(self):
        due = TODAY + timedelta(days=3)
        t = self.task("Pay rent", repeat=Repeat.WEEKLY, due_date=due, remind_at=at(due - timedelta(days=1), 9, 30))
        nxt = services.set_done(t)
        self.assertEqual(nxt.due_date, due + timedelta(days=7))
        self.assertEqual(timezone.localtime(nxt.remind_at), timezone.localtime(at(due + timedelta(days=6), 9, 30)))

    def test_quick_add_repeat_with_a_time_keeps_reminding(self):
        t = services.create_from_quick(self.me, "Standup every day at 10am")
        nxt = services.set_done(t)
        self.assertIsNotNone(nxt.remind_at)
        self.assertEqual(timezone.localtime(nxt.remind_at).date(), nxt.due_date)

    def test_no_reminder_stays_none(self):
        t = self.task("Gym", repeat=Repeat.DAILY, due_date=TODAY)
        self.assertIsNone(services.set_done(t).remind_at)

    def test_a_moved_due_date_takes_its_reminder_along(self):
        due = TODAY + timedelta(days=2)
        t = self.task("Report", due_date=due, remind_at=at(due, 9))
        self.update(t, due_date=(due + timedelta(days=5)).isoformat())          # calendar drag / quick menu
        t.refresh_from_db()
        self.assertEqual(timezone.localtime(t.remind_at), timezone.localtime(at(due + timedelta(days=5), 9)))
        self.client.post(reverse("work:api_task_bulk"), {"ids": str(t.pk), "action": "due", "value": due.isoformat()})
        t.refresh_from_db()
        self.assertEqual(timezone.localtime(t.remind_at), timezone.localtime(at(due, 9)))

    def test_a_reminder_changed_with_the_date_is_kept_as_typed(self):
        due = TODAY + timedelta(days=2)
        t = self.task("Report", due_date=due, remind_at=at(due, 9))
        t.due_date, t.remind_at = due + timedelta(days=1), at(due, 15)
        t.save()
        t.refresh_from_db()
        self.assertEqual(timezone.localtime(t.remind_at), timezone.localtime(at(due, 15)))

    def test_the_form_offers_quick_reminders(self):
        t = self.task("Report", due_date=TODAY)
        self.assertContains(self.client.get(reverse("work:task", args=[t.pk])), "workRemind(")


class DeleteWithSubtasksTests(Base):
    def test_subtasks_go_to_the_trash_with_their_task_and_come_back_with_it(self):
        p = self.task("Release")
        a = self.task("Changelog", parent=p)
        self.task("Tag", parent=p)
        self.client.post(reverse("work:api_task_delete", args=[p.pk]))
        self.assertFalse(Task.objects.exists())
        restore(DeletedItem.objects.get())
        self.assertEqual(Task.objects.get(pk=a.pk).parent_id, p.pk)
        self.assertEqual(Task.objects.count(), 3)

    def test_bulk_delete_of_a_task_and_its_subtask(self):
        p = self.task("Release")
        a = self.task("Changelog", parent=p)
        res = self.client.post(reverse("work:api_task_bulk"), {"ids": f"{a.pk},{p.pk}", "action": "delete"}).json()
        self.assertTrue(res["ok"])
        self.assertFalse(Task.objects.exists())
        self.assertEqual(DeletedItem.objects.count(), 1)
        restore(DeletedItem.objects.get())
        self.assertEqual(Task.objects.count(), 2)


class SearchTests(Base):
    def find(self, q):
        return [r["title"] for r in self.client.get(reverse("work:api_search"), {"q": q}).json()["results"] if r["kind"] == "task"]

    def test_search_reads_notes_comments_files_and_numbers(self):
        a = self.task("Fix login", notes="The session cookie expires too early")
        b = self.task("Pricing page")
        TaskActivity.objects.create(task=b, kind=TaskActivity.Kind.COMMENT, text="Client wants annual discount")
        TaskActivity.objects.create(task=a, data={"field": "title", "old": "annual thing"})      # a change, not a comment
        self.assertEqual(self.find("cookie"), ["Fix login"])
        self.assertEqual(self.find("annual"), ["Pricing page"])
        self.assertEqual(self.find(f"#{b.pk}")[0], "Pricing page")
        self.assertEqual(self.find(str(a.pk))[0], "Fix login")
        self.assertEqual(self.find("login"), ["Fix login"])

    def test_a_title_match_comes_first_and_once(self):
        self.task("Invoice", notes="invoice notes")
        self.task("Other", notes="send the invoice")
        self.assertEqual(self.find("invoice"), ["Invoice", "Other"])


class TimelineDragTests(Base):
    def test_start_date_moves_and_keeps_order(self):
        t = self.task("Design", start_date=TODAY, due_date=TODAY + timedelta(days=3))
        self.update(t, start_date=(TODAY + timedelta(days=1)).isoformat(), due_date=(TODAY + timedelta(days=4)).isoformat())
        t.refresh_from_db()
        self.assertEqual((t.start_date, t.due_date), (TODAY + timedelta(days=1), TODAY + timedelta(days=4)))
        self.update(t, start_date=(TODAY + timedelta(days=9)).isoformat())          # start dragged past the due date
        t.refresh_from_db()
        self.assertEqual((t.start_date, t.due_date), (TODAY + timedelta(days=9), TODAY + timedelta(days=9)))

    def test_timeline_bars_can_be_dragged(self):
        self.task("Design", start_date=TODAY, due_date=TODAY + timedelta(days=3))
        r = self.client.get(reverse("work:tasks"), {"view": "timeline"})
        self.assertContains(r, 'data-edge="start"')
        self.assertContains(r, "workTimeline(42)")


class BackupSubtaskTests(Base):
    def test_a_subtask_listed_before_its_task_still_comes_back_under_it(self):
        p = self.task("Release", order=5)
        self.task("Changelog", parent=p, order=1)
        rows = json.loads(serializers.serialize("json", Task.objects.filter(owner=self.me).order_by("order")))
        self.assertTrue(rows[0]["fields"]["parent"])          # the subtask is first
        new = User.objects.create_superuser("new", "n@example.com", PW)
        services.restore(new, rows)
        sub = Task.objects.get(owner=new, title="Changelog")
        self.assertEqual(sub.parent.title, "Release")
        self.assertEqual(sub.parent.owner, new)


class SprintTests(Base):
    def setUp(self):
        super().setUp()
        self.sp = Sprint.objects.create(owner=self.me, name="Sprint 1", start_date=TODAY - timedelta(days=3), end_date=TODAY + timedelta(days=10))

    def test_new_sprint_follows_the_last_one(self):
        s = sprints.suggest(self.me, TODAY)
        self.assertEqual((s["name"], s["start_date"], s["end_date"]), ("Sprint 2", TODAY + timedelta(days=11), TODAY + timedelta(days=24)))
        r = self.client.post(reverse("work:sprints"), {"name": "Sprint 2", "goal": "Ship billing", "start_date": s["start_date"], "end_date": s["end_date"]})
        sp2 = Sprint.objects.get(name="Sprint 2")
        self.assertRedirects(r, reverse("work:sprint", args=[sp2.pk]))
        bad = self.client.post(reverse("work:sprints"), {"name": "X", "start_date": TODAY, "end_date": TODAY - timedelta(days=1)})
        self.assertEqual(bad.status_code, 200)
        self.assertFalse(Sprint.objects.filter(name="X").exists())

    def test_tasks_are_picked_with_their_subtasks(self):
        p = self.task("Billing")
        sub = self.task("Webhook", parent=p)
        done = self.task("Old", status=Status.DONE)
        page = self.client.get(reverse("work:sprint", args=[self.sp.pk]))
        self.assertIn(p, page.context["backlog"])
        self.assertNotIn(sub, page.context["backlog"])
        self.client.post(reverse("work:sprint", args=[self.sp.pk]), {"action": "add", "task": [p.pk, done.pk]})
        self.assertEqual(set(self.sp.tasks.values_list("title", flat=True)), {"Billing", "Webhook"})
        self.assertEqual(TaskActivity.objects.filter(task=p, data__field="sprint_id").get().data["new_label"], "Sprint 1")

    def test_burndown_counts_open_tasks_day_by_day(self):
        a = self.task("A", sprint=self.sp)
        self.task("B", sprint=self.sp)
        Task.objects.filter(pk=a.pk).update(status=Status.DONE, completed_at=at(TODAY - timedelta(days=2), 12))
        b = sprints.burndown(self.sp, TODAY)
        self.assertEqual([n for _d, n in b["points"]], [2, 1, 1, 1])
        c = sprints.chart(self.sp, TODAY)
        self.assertEqual((c["total"], c["left"]), (2, 1))
        self.assertContains(self.client.get(reverse("work:sprint", args=[self.sp.pk])), "wbu-done")

    def test_closing_moves_the_rest_on_and_keeps_a_summary(self):
        self.task("Done one", sprint=self.sp, status=Status.DONE, completed_at=timezone.now(), estimate_minutes=60)
        left = self.task("Left", sprint=self.sp)
        r = self.client.post(reverse("work:sprint", args=[self.sp.pk]), {"action": "close", "move_to": "new"})
        self.sp.refresh_from_db()
        left.refresh_from_db()
        nxt = Sprint.objects.exclude(pk=self.sp.pk).get()
        self.assertRedirects(r, reverse("work:sprint", args=[nxt.pk]))
        self.assertEqual(left.sprint, nxt)
        self.assertEqual((self.sp.summary["done"], self.sp.summary["left"], self.sp.summary["done_minutes"]), (1, 1, 60))
        self.assertEqual(self.sp.state(), "done")
        self.assertEqual(sprints.velocity(self.me), [(self.sp, 1, 1)])
        page = self.client.get(reverse("work:sprints"))
        self.assertEqual(page.context["average"], 1.0)
        # a closed sprint keeps its burndown, and can't be closed again
        self.assertEqual(sprints.burndown(self.sp)["total"], 2)
        self.client.post(reverse("work:sprint", args=[nxt.pk]), {"action": "close", "move_to": ""})
        left.refresh_from_db()
        self.assertIsNone(left.sprint)

    def test_list_filter_bulk_and_form(self):
        a = self.task("In it", sprint=self.sp)
        b = self.task("Not in it")
        titles = lambda **q: [t.title for g in self.client.get(reverse("work:tasks"), {"view": "list", **q}).context["groups"] for t in g[2]]  # noqa: E731
        self.assertEqual(titles(sprint="current"), ["In it"])
        self.assertEqual(titles(sprint="none"), ["Not in it"])
        self.client.post(reverse("work:api_task_bulk"), {"ids": str(b.pk), "action": "sprint", "value": self.sp.pk})
        self.assertEqual(titles(sprint=str(self.sp.pk)), ["In it", "Not in it"])
        page = self.client.get(reverse("work:task", args=[a.pk]))
        self.assertContains(page, 'name="sprint"')
        self.client.post(reverse("work:task", args=[a.pk]), {"title": "In it", "status": "todo", "priority": 0, "repeat": "", "sprint": self.sp.pk})
        a.refresh_from_db()
        self.assertEqual(a.sprint, self.sp)
        self.update(a, sprint="")              # the ⋯ menu's "Take out of the sprint"
        a.refresh_from_db()
        self.assertIsNone(a.sprint)

    def test_today_shows_the_running_sprint_and_delete_keeps_tasks(self):
        t = self.task("In it", sprint=self.sp)
        self.assertContains(self.client.get(reverse("work:today")), "wd-sprint")
        self.client.post(reverse("work:sprint", args=[self.sp.pk]), {"action": "delete"})
        t.refresh_from_db()
        self.assertIsNone(t.sprint)
        self.assertFalse(Sprint.objects.exists())

    def test_only_the_owner(self):
        other = User.objects.create_superuser("other", "o@example.com", PW)
        self.client.force_login(other)
        self.assertEqual(self.client.get(reverse("work:sprint", args=[self.sp.pk])).status_code, 404)
        t = Task.objects.create(owner=other, title="Mine")
        self.update(t, sprint=self.sp.pk)
        t.refresh_from_db()
        self.assertIsNone(t.sprint)

    def test_sprints_are_in_the_export_and_come_back(self):
        self.task("In it", sprint=self.sp)
        import io
        import zipfile
        z = zipfile.ZipFile(io.BytesIO(self.client.get(reverse("work:export")).content))
        rows = json.loads(z.read("data.json"))
        self.assertTrue(any(r["model"] == "productivity.sprint" for r in rows))
        new = User.objects.create_superuser("new", "n@example.com", PW)
        services.restore(new, rows)
        self.assertEqual(Task.objects.get(owner=new, title="In it").sprint.owner, new)
