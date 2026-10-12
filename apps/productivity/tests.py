"""Productivity: who can open it, privacy, every page, the timer, quick add,
tasks, notes, habits, focus, reports and working offline."""
from datetime import date, datetime, timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.business.core.models import Dashboard, UserDashboardAccess

from . import services
from .models import (
    Goal, GoalStatus, Habit, HabitCheck, JournalEntry, LearningItem, Note, Project, Snippet, Status, Tag, Task, TimeEntry, WorkSettings,
    link_label,
)

PW = "Str0ng-pass-123"


def aware(*args):
    return timezone.make_aware(datetime(*args), timezone.get_current_timezone())


class AccessTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("boss", "b@example.com", PW)
        self.member = User.objects.create_user("worker", "w@example.com", PW)

    def test_admins_yes_others_only_when_allowed(self):
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(reverse("work:today")).status_code, 403)
        self.assertEqual(self.client.post(reverse("work:api_timer_start"), {"description": "x"}).status_code, 403)
        UserDashboardAccess.objects.create(user=self.member, dashboard=Dashboard.objects.get(code="productivity"), granted_by=self.admin)
        self.assertEqual(self.client.get(reverse("work:today")).status_code, 200)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("work:today")).status_code, 200)

    def test_switcher_offers_it_to_admins(self):
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("home")), reverse("work:today"))

    def test_nobody_sees_anyone_elses_work(self):
        other = User.objects.create_superuser("other", "o@example.com", PW)
        task = Task.objects.create(owner=other, title="Secret")
        note = Note.objects.create(owner=other, body="Private")
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("work:task", args=[task.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("work:note", args=[note.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("work:api_task_done", args=[task.pk])).status_code, 404)
        self.assertNotContains(self.client.get(reverse("work:tasks")), "Secret")
        self.assertEqual(self.client.post(reverse("work:api_timer_start"), {"task": task.pk}).status_code, 404)


class PagesTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser("dev", "d@example.com", PW)
        self.client.force_login(self.user)
        self.p = Project.objects.create(owner=self.user, name="FinTrack", color="teal", estimate_hours=10, hourly_rate=1000)
        tag = Tag.objects.create(owner=self.user, name="backend")
        self.t = Task.objects.create(owner=self.user, title="Write tests", project=self.p, due_date=timezone.localdate(), estimate_minutes=60)
        self.t.tags.add(tag)
        self.t.checklist.create(text="Models")
        now = timezone.now()
        TimeEntry.objects.create(owner=self.user, task=self.t, project=self.p, started_at=now - timedelta(hours=2), ended_at=now - timedelta(hours=1))
        TimeEntry.objects.create(owner=self.user, description="Running", started_at=now - timedelta(minutes=5))
        self.n = Note.objects.create(owner=self.user, title="Idea", body="# Heading\n\n- [ ] todo\n\n```py\nprint(1)\n```")
        Snippet.objects.create(owner=self.user, title="Docker prune", language="bash", code="docker system prune -af")
        h = Habit.objects.create(owner=self.user, name="Read", emoji="📚")
        HabitCheck.objects.create(habit=h, date=timezone.localdate() - timedelta(days=1))
        JournalEntry.objects.create(owner=self.user, date=timezone.localdate(), blockers="Waiting on review")

    def test_every_page(self):
        names = ["today", "tasks", "task_new", "projects", "project_new", "time", "entry_new", "focus", "notes", "snippets",
                 "snippet_new", "habits", "habit_new", "journal", "reports", "settings", "help", "goals", "goal_new", "learning",
                 "learning_new", "review", "calendar", "share", "wrapup"]
        for name in names:
            with self.subTest(name):
                r = self.client.get(reverse(f"work:{name}"))
                self.assertEqual(r.status_code, 200)
                self.assertContains(r, 'id="work-config"')
        for url in [reverse("work:task", args=[self.t.pk]), reverse("work:project", args=[self.p.pk]), reverse("work:project_edit", args=[self.p.pk]),
                    reverse("work:note", args=[self.n.pk]), reverse("work:tasks") + "?view=board", reverse("work:tasks") + "?done=1&q=write",
                    reverse("work:reports") + "?range=30", reverse("work:reports") + "?range=custom&from=2026-01-01&to=2026-02-01",
                    reverse("work:notes") + "?new=1", reverse("work:time") + "?week=2026-01-05", reverse("work:journal") + "?date=2026-01-05",
                    reverse("work:review") + "?range=quarter", reverse("work:review") + "?range=year", reverse("work:calendar") + "?month=2026-02",
                    reverse("work:learning") + "?show=all&kind=book", reverse("work:goals") + "?show=done"]:
            with self.subTest(url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_reports_csv(self):
        r = self.client.get(reverse("work:reports") + "?export=csv")
        self.assertEqual(r["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("Write tests", r.content.decode())

    def test_standup(self):
        r = self.client.get(reverse("work:journal"))
        self.assertContains(r, "Waiting on review")
        self.assertContains(r, "Write tests")   # on today's list (due today)


class TimerTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser("dev", "d@example.com", PW)
        self.client.force_login(self.user)

    def test_one_timer_at_a_time_and_phone_clock(self):
        task = Task.objects.create(owner=self.user, title="Bug", status=Status.TODO)
        at = timezone.now() - timedelta(minutes=30)
        r = self.client.post(reverse("work:api_timer_start"), {"task": task.pk, "at": at.isoformat()}).json()
        self.assertEqual(r["running"]["task"], task.pk)
        task.refresh_from_db()
        self.assertEqual(task.status, Status.DOING)          # started → in progress
        self.client.post(reverse("work:api_timer_start"), {"description": "Review", "at": (at + timedelta(minutes=20)).isoformat()})
        first = TimeEntry.objects.get(task=task)
        self.assertEqual(first.seconds, 20 * 60)              # stopped where the next one started
        r = self.client.post(reverse("work:api_timer_stop"), {"at": (at + timedelta(minutes=25)).isoformat()}).json()
        self.assertEqual(r["stopped"]["seconds"], 5 * 60)
        self.assertFalse(TimeEntry.objects.filter(owner=self.user, ended_at__isnull=True).exists())

    def test_future_or_ancient_times_are_clamped(self):
        self.client.post(reverse("work:api_timer_start"), {"description": "x", "at": (timezone.now() + timedelta(days=2)).isoformat()})
        e = TimeEntry.objects.get()
        self.assertLessEqual(e.started_at, timezone.now())

    def test_state_and_rename(self):
        self.client.post(reverse("work:api_timer_start"), {"description": "Coding"})
        self.client.post(reverse("work:api_timer_update"), {"description": "Code review"})
        r = self.client.get(reverse("work:api_timer_state")).json()
        self.assertEqual(r["running"]["label"], "Code review")

    def test_offline_key_saves_once(self):
        data = {"description": "From the outbox", "_ft_key": "k-1", "_ft_user": str(self.user.pk)}
        self.client.post(reverse("work:api_timer_start"), data)
        r = self.client.post(reverse("work:api_timer_start"), data, HTTP_X_FT_REPLAY="1").json()
        self.assertTrue(r["ok"])
        self.assertEqual(TimeEntry.objects.filter(owner=self.user).count(), 1)


class QuickAddTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser("dev", "d@example.com", PW)
        self.client.force_login(self.user)

    def test_parse(self):
        today = date(2026, 10, 12)   # a Monday
        p = services.parse_quick("Fix login bug #auth @api !high tomorrow ~45m *", today)
        self.assertEqual((p.title, p.tags, p.project, p.priority, p.due, p.estimate, p.my_day),
                         ("Fix login bug", ["auth"], "api", 3, date(2026, 10, 13), 45, True))
        p = services.parse_quick("Render 3d sun texture friday ~1.5h", today)
        self.assertEqual((p.title, p.due, p.estimate), ("Render 3d sun texture", date(2026, 10, 16), 90))
        self.assertEqual(services.parse_quick("Ship +2w due:25/12", today).due, date(2026, 12, 25))

    def test_api_add_finds_project_and_makes_tags(self):
        Project.objects.create(owner=self.user, name="Backend API")
        r = self.client.post(reverse("work:api_task_add"), {"text": "Cache users #perf @back !urgent"}).json()
        t = Task.objects.get(pk=r["id"])
        self.assertEqual((t.title, t.project.name, t.priority, list(t.tags.values_list("name", flat=True))), ("Cache users", "Backend API", 4, ["perf"]))
        self.assertIn('data-task="%d"' % t.pk, r["html"])
        self.assertEqual(self.client.post(reverse("work:api_task_add"), {"text": "#only-a-tag"}).status_code, 400)


class TaskTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser("dev", "d@example.com", PW)
        self.client.force_login(self.user)

    def test_done_and_repeat(self):
        t = Task.objects.create(owner=self.user, title="Standup notes", due_date=date(2026, 10, 9), repeat="weekdays")   # Friday
        t.checklist.create(text="Yesterday")
        r = self.client.post(reverse("work:api_task_done", args=[t.pk]), {"done": "1"}).json()
        self.assertTrue(r["done"])
        nxt = Task.objects.get(pk=r["next"]["id"])
        self.assertEqual(nxt.due_date, date(2026, 10, 11))      # skips the weekend: Friday → Sunday (the default Sun–Thu work week)
        self.assertEqual(nxt.checklist.count(), 1)
        self.client.post(reverse("work:api_task_done", args=[t.pk]), {"done": "0"})
        t.refresh_from_db()
        self.assertEqual((t.status, t.completed_at), (Status.TODO, None))

    def test_board_move_orders_between_cards(self):
        a = Task.objects.create(owner=self.user, title="A", status="doing", order=1)
        b = Task.objects.create(owner=self.user, title="B", status="doing", order=2)
        c = Task.objects.create(owner=self.user, title="C", status="todo", order=1)
        self.client.post(reverse("work:api_task_move", args=[c.pk]), {"status": "doing", "after": a.pk, "before": b.pk})
        c.refresh_from_db()
        self.assertEqual((c.status, c.order), ("doing", 1.5))
        self.client.post(reverse("work:api_task_move", args=[c.pk]), {"status": "done"})
        c.refresh_from_db()
        self.assertTrue(c.completed_at)

    def test_delete_and_undo_with_tags(self):
        t = Task.objects.create(owner=self.user, title="Tagged")
        t.tags.add(Tag.objects.create(owner=self.user, name="x"))
        r = self.client.post(reverse("work:api_task_delete", args=[t.pk])).json()
        self.assertFalse(Task.objects.filter(pk=t.pk).exists())
        self.client.post(r["undo"])
        self.assertEqual(list(Task.objects.get(pk=t.pk).tags.values_list("name", flat=True)), ["x"])

    def test_checklist(self):
        t = Task.objects.create(owner=self.user, title="T")
        r = self.client.post(reverse("work:api_checklist_add", args=[t.pk]), {"text": "Step 1"}).json()
        r = self.client.post(reverse("work:api_checklist_item", args=[r["id"]]), {"done": "1"}).json()
        self.assertEqual(r["progress"], [1, 1])

    def test_full_form(self):
        r = self.client.post(reverse("work:task_new"), {"title": "From the form", "status": "todo", "priority": "2", "tags_text": "a, b", "notes": "x"})
        t = Task.objects.get(title="From the form")
        self.assertRedirects(r, reverse("work:task", args=[t.pk]))
        self.assertEqual(sorted(t.tags.values_list("name", flat=True)), ["a", "b"])


class TotalsTests(TestCase):
    def test_split_across_midnight_and_projects(self):
        user = User.objects.create_user("dev", "", PW)
        p = Project.objects.create(owner=user, name="P")
        TimeEntry.objects.create(owner=user, project=p, started_at=aware(2026, 10, 10, 23, 0), ended_at=aware(2026, 10, 11, 1, 30))
        TimeEntry.objects.create(owner=user, started_at=aware(2026, 10, 11, 9, 0), ended_at=aware(2026, 10, 11, 9, 45), billable=True)
        t = services.totals(user, date(2026, 10, 10), date(2026, 10, 11))
        self.assertEqual(t.by_day, {date(2026, 10, 10): 3600, date(2026, 10, 11): 5400 + 2700})
        self.assertEqual(t.seconds, 9000 + 2700)
        self.assertEqual(t.billable_seconds, 2700)
        self.assertEqual(t.by_project[0], (p, 9000))
        only_11 = services.totals(user, date(2026, 10, 11), date(2026, 10, 11))
        self.assertEqual(only_11.seconds, 5400 + 2700)

    def test_streak_counts_work_days_that_hit_the_target(self):
        user = User.objects.create_user("dev", "", PW)
        s = WorkSettings.for_user(user)
        s.daily_target_minutes, s.work_days = 60, "01234"   # Mon–Fri
        s.save()
        for day in (date(2026, 10, 7), date(2026, 10, 8), date(2026, 10, 9)):   # Wed, Thu, Fri
            TimeEntry.objects.create(owner=user, started_at=aware(day.year, day.month, day.day, 9), ended_at=aware(day.year, day.month, day.day, 10, 30))
        self.assertEqual(services.focus_streak(user, date(2026, 10, 12)), 3)   # Monday morning: the weekend doesn't break it


class NotesHabitsFocusTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser("dev", "d@example.com", PW)
        self.client.force_login(self.user)

    def test_note_autosave_and_to_task(self):
        r = self.client.post(reverse("work:api_note_save"), {"body": "First line title\nmore", "tags": "idea, x"}).json()
        note = Note.objects.get(pk=r["id"])
        self.assertEqual(note.display_title, "First line title")
        self.client.post(reverse("work:api_note_save"), {"id": note.pk, "title": "Renamed"})
        note.refresh_from_db()
        self.assertEqual(note.title, "Renamed")
        self.assertEqual(self.client.post(reverse("work:api_note_save"), {"body": "  "}).status_code, 400)
        r = self.client.post(reverse("work:api_note_action", args=[note.pk]), {"action": "to_task"}).json()
        self.assertTrue(Task.objects.filter(title="Renamed").exists())

    def test_habit_streak(self):
        h = Habit.objects.create(owner=self.user, name="Run")
        today = timezone.localdate()
        HabitCheck.objects.create(habit=h, date=today - timedelta(days=1))
        Habit.objects.filter(pk=h.pk).update(created_at=timezone.now() - timedelta(days=10))
        r = self.client.post(reverse("work:api_habit_check", args=[h.pk]), {"date": today.isoformat(), "done": "1"}).json()
        self.assertEqual(r["streak"], 2)
        self.assertEqual(self.client.post(reverse("work:api_habit_check", args=[h.pk]), {"date": (today + timedelta(days=1)).isoformat()}).status_code, 400)

    def test_focus_session_is_logged(self):
        task = Task.objects.create(owner=self.user, title="Deep work")
        end = timezone.now()
        r = self.client.post(reverse("work:api_focus_log"), {"started_at": (end - timedelta(minutes=25)).isoformat(), "ended_at": end.isoformat(), "task": task.pk}).json()
        e = TimeEntry.objects.get(pk=r["id"])
        self.assertEqual((e.kind, e.task_id, e.seconds // 60), ("focus", task.pk, 25))

    def test_journal_autosave(self):
        day = timezone.localdate().isoformat()
        self.client.post(reverse("work:api_journal_save"), {"date": day, "plan": "Ship it", "mood": "4"})
        j = JournalEntry.objects.get(owner=self.user)
        self.assertEqual((j.plan, j.mood), ("Ship it", 4))

    def test_manual_entry_past_midnight(self):
        r = self.client.post(reverse("work:entry_new"), {"description": "Late deploy", "day": "2026-10-10", "start": "23:30", "end": "00:15"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(TimeEntry.objects.get(description="Late deploy").seconds, 45 * 60)

    def test_settings(self):
        r = self.client.post(reverse("work:settings"), {"action": "settings", "s-daily_target_hours": "7.5", "s-work_day_list": ["6", "0", "1", "2", "3"],
                                                        "s-week_start": "6", "s-focus_minutes": "50", "s-short_break_minutes": "10", "s-long_break_minutes": "20",
                                                        "s-long_break_every": "3", "s-sound": "bell", "s-volume": "40", "s-long_timer_hours": "4",
                                                        "s-idle_minutes": "20"})
        self.assertEqual(r.status_code, 302)
        s = WorkSettings.for_user(self.user)
        self.assertEqual((s.daily_target_minutes, s.work_days, s.focus_minutes, s.sound_enabled), (450, "01236", 50, False))
        self.assertContains(self.client.get(reverse("work:focus")), "50 / 10 / 20")


class OfflineTests(TestCase):
    def test_tracker_pages_are_kept_for_people_who_can_open_it(self):
        user = User.objects.create_superuser("dev", "d@example.com", PW)
        self.client.force_login(user)
        pages = self.client.get(reverse("offline_pages")).json()["more"]
        work = [u for u in pages if u.startswith("/work/")]
        self.assertIn(reverse("work:today"), work)
        self.assertFalse([u for u in work if "/api/" in u])
        for url in work:
            r = self.client.get(url)
            self.assertEqual((url, r.status_code, r.get("X-FT-Offline")), (url, 200, "1"))
        member = User.objects.create_user("plain", "", PW)
        self.client.force_login(member)
        self.assertFalse([u for u in self.client.get(reverse("offline_pages")).json()["more"] if u.startswith("/work/")])


class SpeedTests(TestCase):
    """Long lists stay quick: rows are capped (with "Show all"), and a page's
    query count doesn't grow with the number of tasks or projects."""

    def setUp(self):
        self.user = User.objects.create_superuser("dev", "d@example.com", PW)
        self.client.force_login(self.user)
        self.p = Project.objects.create(owner=self.user, name="Big", color="blue")
        tag = Tag.objects.create(owner=self.user, name="t")
        tasks = Task.objects.bulk_create([Task(owner=self.user, title=f"Backlog {i}", status="backlog", project=self.p, order=i) for i in range(60)])
        for t in tasks[:10]:
            t.tags.add(tag)

    def test_groups_are_capped_and_one_group_shows_in_full(self):
        r = self.client.get(reverse("work:tasks"))
        self.assertEqual(r.content.decode().count('<li class="wt-task'), 40)
        self.assertContains(r, "?group=backlog")
        r = self.client.get(reverse("work:tasks") + "?group=backlog")
        self.assertEqual(r.content.decode().count('<li class="wt-task'), 60)

    def test_query_count_does_not_grow_with_rows(self):
        def queries(url):
            from django.db import connection
            from django.test.utils import CaptureQueriesContext

            with CaptureQueriesContext(connection) as q:
                self.assertEqual(self.client.get(url).status_code, 200)
            return len(q)

        Task.objects.create(owner=self.user, title="Today", project=self.p, my_day=timezone.localdate()).tags.add(Tag.objects.get(name="t"))
        for url in (reverse("work:tasks"), reverse("work:project", args=[self.p.pk]), reverse("work:today"), reverse("work:projects")):
            with self.subTest(url):
                before = queries(url)
                more = Task.objects.bulk_create([Task(owner=self.user, title=f"More {i}", status="todo", project=self.p, my_day=timezone.localdate()) for i in range(20)])
                Project.objects.create(owner=self.user, name=f"Other {url}")
                self.assertLessEqual(queries(url), before + 1, url)
                Task.objects.filter(pk__in=[t.pk for t in more]).delete()

    def test_rows_are_light(self):
        r = self.client.get(reverse("work:tasks"))
        self.assertEqual(r.content.decode().count('id="work-task-menu"'), 1)    # one shared menu, not one per row
        self.assertNotIn("x-data", r.content.decode().split('<li class="wt-task', 1)[1].split("</li>", 1)[0])

    def test_totals_match_the_database_sums(self):
        now = timezone.now()
        for h in range(1, 30):
            TimeEntry.objects.create(owner=self.user, project=self.p, started_at=now - timedelta(hours=h * 5), ended_at=now - timedelta(hours=h * 5 - 1))
        today = timezone.localdate()
        t = services.totals(self.user, today - timedelta(days=20), today)
        self.assertEqual(t.seconds, 29 * 3600)
        self.assertEqual(sum(t.by_day.values()), t.seconds)
        self.assertEqual(sum(t.by_hour), t.seconds)
        self.assertEqual(services.tracked_by(self.user, "project_id"), {self.p.pk: 29 * 3600})
        self.assertEqual(sum(services.daily_seconds(self.user, today - timedelta(days=20), today).values()), 29 * 3600)
        self.assertEqual(len(t.entries), 29)    # the objects, loaded only when asked for


class LinkTests(TestCase):
    def test_labels(self):
        self.assertEqual(link_label("https://github.com/acme/api/pull/482"), "PR #482")
        self.assertEqual(link_label("https://gitlab.com/acme/api/-/merge_requests/7"), "MR !7")
        self.assertEqual(link_label("https://github.com/acme/api/issues/91"), "#91")
        self.assertEqual(link_label("https://acme.atlassian.net/browse/FIN-231"), "FIN-231")
        self.assertEqual(link_label("https://www.example.com/docs/x"), "example.com")

    def test_quick_add_keeps_a_pasted_link(self):
        p = services.parse_quick("Review https://github.com/acme/api/pull/12 #review", date(2026, 10, 12))
        self.assertEqual((p.title, p.link, p.tags), ("Review", "https://github.com/acme/api/pull/12", ["review"]))
        self.assertEqual(services.parse_quick("https://github.com/acme/api/pull/12").title, "PR #12")
        user = User.objects.create_superuser("dev", "d@example.com", PW)
        self.client.force_login(user)
        r = self.client.post(reverse("work:api_task_add"), {"text": "Fix it https://github.com/acme/api/issues/5"}).json()
        self.assertIn("#5", r["html"])
        t = Task.objects.get(pk=r["id"])
        self.client.post(reverse("work:api_task_update", args=[t.pk]), {"link": "javascript:alert(1)"})
        t.refresh_from_db()
        self.assertEqual(t.link, "https://github.com/acme/api/issues/5")    # only web links


class GoalTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser("dev", "d@example.com", PW)
        self.client.force_login(self.user)

    def test_form_has_colour_swatches(self):
        # Colour pickers must be real radio buttons (they were <option>s, so a new project or habit never saved).
        for name in ("goal_new", "project_new", "habit_new"):
            with self.subTest(name):
                self.assertContains(self.client.get(reverse(f"work:{name}")), 'type="radio" name="color"')
        r = self.client.post(reverse("work:project_new"), {"name": "New one", "color": "teal"})
        self.assertEqual(r.status_code, 302)

    def test_progress_from_number_milestones_or_tasks(self):
        r = self.client.post(reverse("work:goal_new"), {"title": "150 problems", "area": "learning", "color": "amber", "unit": "problems",
                                                        "start_value": "0", "target_value": "150"})
        g = Goal.objects.get(title="150 problems")
        self.assertRedirects(r, reverse("work:goal", args=[g.pk]))
        r = self.client.post(reverse("work:api_goal_value", args=[g.pk]), {"value": "57"}).json()
        self.assertEqual((r["value"], r["pct"]), ("57", 38))
        r = self.client.post(reverse("work:api_goal_value", args=[g.pk]), {"add": "93"}).json()
        self.assertTrue(r["reached"])

        g2 = Goal.objects.create(owner=self.user, title="Senior engineer")
        a = self.client.post(reverse("work:api_goal_step", args=[g2.pk]), {"text": "Design doc"}).json()
        self.client.post(reverse("work:api_goal_step", args=[g2.pk]), {"text": "Mentor"})
        r = self.client.post(reverse("work:api_goal_step", args=[g2.pk]), {"step": a["id"], "done": "1"}).json()
        self.assertEqual((r["pct"], r["steps"]), (50, [1, 2]))

        g3 = Goal.objects.create(owner=self.user, title="Ship v2")
        self.client.post(reverse("work:api_task_add"), {"text": "Release notes", "goal": g3.pk})
        t = Task.objects.create(owner=self.user, title="Deploy", goal=g3)
        services.set_done(t, True)
        self.assertEqual(services.with_progress([g3])[0].pct, 50)
        self.assertContains(self.client.get(reverse("work:goals")), "Ship v2")
        self.assertContains(self.client.get(reverse("work:goal", args=[g3.pk])), "Release notes")

    def test_reach_drop_delete(self):
        g = Goal.objects.create(owner=self.user, title="G")
        t = Task.objects.create(owner=self.user, title="Kept", goal=g)
        self.client.post(reverse("work:goal", args=[g.pk]), {"action": "done"})
        g.refresh_from_db()
        self.assertEqual((g.status, g.progress()), (GoalStatus.DONE, 100))
        self.assertTrue(g.completed_at)
        self.client.post(reverse("work:goal", args=[g.pk]), {"action": "delete"})
        self.assertFalse(Goal.objects.filter(pk=g.pk).exists())
        t.refresh_from_db()
        self.assertIsNone(t.goal)

    def test_private(self):
        other = User.objects.create_superuser("other", "o@example.com", PW)
        g = Goal.objects.create(owner=other, title="Secret goal")
        item = LearningItem.objects.create(owner=other, title="Secret book")
        self.assertEqual(self.client.get(reverse("work:goal", args=[g.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("work:api_goal_step", args=[g.pk]), {"text": "x"}).status_code, 404)
        self.assertEqual(self.client.post(reverse("work:api_learning_update", args=[item.pk]), {"add": "1"}).status_code, 404)
        self.assertNotContains(self.client.get(reverse("work:goals")), "Secret goal")
        self.assertEqual(self.client.get(reverse("work:api_search") + "?q=secret").json()["results"], [])


class LearningTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser("dev", "d@example.com", PW)
        self.client.force_login(self.user)

    def test_quick_add_progress_and_finish(self):
        r = self.client.post(reverse("work:api_learning_add"), {"text": "https://youtu.be/abc Simple Made Easy"}).json()
        item = LearningItem.objects.get(pk=r["id"])
        self.assertEqual((item.title, item.kind, item.url, item.status), ("Simple Made Easy", "video", "https://youtu.be/abc", "queued"))
        book = LearningItem.objects.create(owner=self.user, title="DDIA", total=590, progress=200)
        r = self.client.post(reverse("work:api_learning_update", args=[book.pk]), {"add": "10"}).json()
        self.assertEqual((r["progress"], r["status"]), (210, "active"))     # reading it → in progress
        r = self.client.post(reverse("work:api_learning_update", args=[book.pk]), {"status": "done"}).json()
        book.refresh_from_db()
        self.assertEqual((book.progress, book.percent, book.finished_on), (590, 100, timezone.localdate()))

    def test_form_fills_the_dates(self):
        r = self.client.post(reverse("work:learning_new"), {"title": "Clean Code", "kind": "book", "status": "done", "unit": "pages",
                                                            "progress": "0", "total": "400", "tags_text": "craft"})
        self.assertEqual(r.status_code, 302)
        item = LearningItem.objects.get(title="Clean Code")
        self.assertEqual((item.finished_on, item.started_on, item.progress), (timezone.localdate(), timezone.localdate(), 400))
        self.assertEqual(list(item.tags.values_list("name", flat=True)), ["craft"])


class ReviewCalendarExportTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser("dev", "d@example.com", PW)
        self.client.force_login(self.user)
        p = Project.objects.create(owner=self.user, name="FinTrack")
        t = Task.objects.create(owner=self.user, title="Ship 2FA", project=p, link="https://github.com/a/b/pull/9")
        services.set_done(t, True)
        Task.objects.create(owner=self.user, title="Due soon", due_date=timezone.localdate() + timedelta(days=2))
        JournalEntry.objects.create(owner=self.user, date=timezone.localdate(), wins="Shipped 2FA\n- Learnt MVCC", mood=4)
        Goal.objects.create(owner=self.user, title="Lead a project", status="done", completed_at=timezone.now())
        LearningItem.objects.create(owner=self.user, title="DDIA", status="done", finished_on=timezone.localdate())
        Note.objects.create(owner=self.user, title="Runbook", body="Restart the worker")
        Snippet.objects.create(owner=self.user, title="Prune", language="bash", code="docker system prune")

    def test_review_and_brag_document(self):
        r = self.client.get(reverse("work:review"))
        for text in ("Ship 2FA", "Learnt MVCC", "Lead a project", "DDIA", "Due soon"):
            self.assertContains(r, text)
        md = self.client.get(reverse("work:review") + "?export=md").content.decode()
        self.assertIn("## What I shipped", md)
        self.assertIn("- Ship 2FA (https://github.com/a/b/pull/9)", md)
        self.assertIn("- Learnt MVCC", md)

    def test_calendar_shows_due_tasks(self):
        day = timezone.localdate() + timedelta(days=2)
        r = self.client.get(reverse("work:calendar") + f"?month={day:%Y-%m}")
        self.assertContains(r, "Due soon")

    def test_export_everything(self):
        import io
        import json
        import zipfile

        r = self.client.get(reverse("work:export"))
        z = zipfile.ZipFile(io.BytesIO(r.content))
        data = json.loads(z.read("data.json"))
        models = {row["model"] for row in data}
        self.assertTrue({"productivity.task", "productivity.goal", "productivity.learningitem", "productivity.note"} <= models)
        self.assertIn("Restart the worker", z.read([n for n in z.namelist() if n.startswith("notes/")][0]).decode())
        self.assertEqual(z.read([n for n in z.namelist() if n.startswith("snippets/")][0]).decode(), "docker system prune")

    def test_share_target(self):
        r = self.client.get(reverse("work:share") + "?title=Bug&text=See+https://github.com/a/b/issues/3+please")
        self.assertContains(r, "https://github.com/a/b/issues/3")
        plain = User.objects.create_user("plain", "", PW)
        self.client.force_login(plain)
        self.assertRedirects(self.client.get(reverse("work:share") + "?url=https://x.y"), reverse("home"), fetch_redirect_response=False)

    def test_search_everywhere(self):
        r = self.client.get(reverse("work:api_search") + "?q=ddia").json()
        self.assertEqual([x["kind"] for x in r["results"]], ["learning"])
        r = self.client.get(reverse("search") + "?q=ship")
        self.assertContains(r, "Ship 2FA")                      # the app-wide search finds tasks too
        plain = User.objects.create_user("plain", "", PW)
        self.client.force_login(plain)
        self.assertNotContains(self.client.get(reverse("search") + "?q=ship"), "Ship 2FA")


class DailyFlowTests(TestCase):
    """Waiting on others, leftovers, capacity, wrap-up, bulk changes, note templates."""

    def setUp(self):
        self.user = User.objects.create_superuser("dev", "d@example.com", PW)
        self.client.force_login(self.user)
        self.today = timezone.localdate()

    def test_waiting_on_someone(self):
        t = Task.objects.create(owner=self.user, title="Merge auth PR")
        r = self.client.post(reverse("work:api_task_update", args=[t.pk]), {"waiting_for": "Rahim's review"}).json()
        self.assertIn("Rahim", r["html"])
        page = self.client.get(reverse("work:tasks")).content.decode()
        self.assertIn('data-group="waiting"', page)
        self.assertIn("Waiting on Rahim", self.client.get(reverse("work:journal")).content.decode().replace("&#x27;", "'"))   # in the standup
        self.assertContains(self.client.get(reverse("work:today")), "Waiting on others")

    def test_leftovers_and_capacity(self):
        Task.objects.create(owner=self.user, title="From yesterday", my_day=self.today - timedelta(days=1))
        for i in range(4):
            Task.objects.create(owner=self.user, title=f"Big {i}", my_day=self.today, estimate_minutes=120)
        s = WorkSettings.for_user(self.user)
        s.work_days = "0123456"
        s.save()
        r = self.client.get(reverse("work:today"))
        self.assertContains(r, "left from earlier days")
        self.assertContains(r, "wd-cap is-over")             # 8h planned > 6h day

    def test_bulk(self):
        a, b, c = (Task.objects.create(owner=self.user, title=x) for x in "abc")
        other = Task.objects.create(owner=User.objects.create_user("o", "", PW), title="not mine")
        ids = f"{a.pk},{b.pk},{other.pk}"
        self.assertEqual(self.client.post(reverse("work:api_task_bulk"), {"ids": ids, "action": "myday"}).json()["count"], 2)
        self.assertEqual(Task.objects.filter(my_day=self.today).count(), 2)
        self.client.post(reverse("work:api_task_bulk"), {"ids": ids, "action": "due", "value": "2026-12-01"})
        self.client.post(reverse("work:api_task_bulk"), {"ids": ids, "action": "priority", "value": "4"})
        a.refresh_from_db()
        self.assertEqual((str(a.due_date), a.priority), ("2026-12-01", 4))
        self.client.post(reverse("work:api_task_bulk"), {"ids": f"{a.pk}", "action": "tomorrow"})
        a.refresh_from_db()
        self.assertEqual(a.my_day, self.today + timedelta(days=1))
        self.client.post(reverse("work:api_task_bulk"), {"ids": ids, "action": "done"})
        self.assertEqual(Task.objects.filter(owner=self.user, status=Status.DONE).count(), 2)
        self.client.post(reverse("work:api_task_bulk"), {"ids": f"{c.pk},{other.pk}", "action": "delete"})
        self.assertFalse(Task.objects.filter(pk=c.pk).exists())
        self.assertTrue(Task.objects.filter(pk=other.pk).exists())       # someone else's is never touched
        self.assertEqual(self.client.post(reverse("work:api_task_bulk"), {"ids": "1", "action": "explode"}).status_code, 400)

    def test_wrapup_moves_to_tomorrow_and_plans(self):
        t = Task.objects.create(owner=self.user, title="Unfinished", my_day=self.today, due_date=self.today)
        r = self.client.get(reverse("work:wrapup"))
        self.assertContains(r, "Unfinished")
        self.client.post(reverse("work:api_task_bulk"), {"ids": t.pk, "action": "tomorrow"})
        t.refresh_from_db()
        self.assertEqual((t.my_day, t.due_date), (self.today + timedelta(days=1),) * 2)
        tomorrow = (self.today + timedelta(days=1)).isoformat()
        self.client.post(reverse("work:api_journal_save"), {"date": tomorrow, "plan": "Ship it"})
        self.assertEqual(JournalEntry.objects.get(owner=self.user, date=tomorrow).plan, "Ship it")

    def test_note_templates(self):
        r = self.client.get(reverse("work:notes") + "?new=1&template=adr")
        self.assertContains(r, "Decision record")
        self.assertContains(r, "Consequences")
        self.assertContains(self.client.get(reverse("work:notes") + "?new=1"), "template=meeting")


class FeedAndRestoreTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser("dev", "d@example.com", PW)
        self.client.force_login(self.user)

    def test_calendar_feed_needs_only_its_secret(self):
        Task.objects.create(owner=self.user, title="Release, v2; final", due_date=timezone.localdate() + timedelta(days=3))
        Task.objects.create(owner=self.user, title="Call client", remind_at=timezone.now() + timedelta(hours=2))
        Goal.objects.create(owner=self.user, title="Senior", target_date=timezone.localdate() + timedelta(days=90))
        self.client.post(reverse("work:settings"), {"action": "feed"})
        token = WorkSettings.objects.get(owner=self.user).feed_token
        self.assertGreaterEqual(len(token), 20)
        self.client.logout()
        r = self.client.get(reverse("work:feed", args=[token]))
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn("SUMMARY:Release\\, v2\\; final", body)
        self.assertIn("BEGIN:VALARM", body)
        self.assertIn("Senior", body)
        self.assertEqual(self.client.get(reverse("work:feed", args=["x" * 32])).status_code, 404)
        self.client.force_login(self.user)
        self.client.post(reverse("work:settings"), {"action": "feed_off"})
        self.client.logout()
        self.assertEqual(self.client.get(reverse("work:feed", args=[token])).status_code, 404)

    def test_restore_a_backup(self):
        import io

        from django.core.files.uploadedfile import SimpleUploadedFile

        p = Project.objects.create(owner=self.user, name="API")
        g = Goal.objects.create(owner=self.user, title="Ship", project=p)
        g.steps.create(text="Beta")
        t = Task.objects.create(owner=self.user, title="Write docs", project=p, goal=g)
        t.tags.add(Tag.objects.create(owner=self.user, name="docs"))
        t.checklist.create(text="Intro")
        TimeEntry.objects.create(owner=self.user, task=t, project=p, started_at=timezone.now() - timedelta(hours=1), ended_at=timezone.now())
        Note.objects.create(owner=self.user, title="N", body="b")
        h = Habit.objects.create(owner=self.user, name="Read")
        HabitCheck.objects.create(habit=h, date=timezone.localdate())
        JournalEntry.objects.create(owner=self.user, date=timezone.localdate(), wins="x")
        backup = self.client.get(reverse("work:export")).content

        fresh = User.objects.create_superuser("new", "n@example.com", PW)
        self.client.force_login(fresh)
        upload = SimpleUploadedFile("backup.zip", backup, content_type="application/zip")
        r = self.client.post(reverse("work:settings"), {"action": "restore", "backup": upload})
        self.assertEqual(r.status_code, 302)
        task = Task.objects.get(owner=fresh, title="Write docs")
        self.assertEqual((task.project.owner, task.project.name, task.goal.title), (fresh, "API", "Ship"))
        self.assertEqual(list(task.tags.values_list("name", flat=True)), ["docs"])
        self.assertEqual(task.checklist.count(), 1)
        self.assertEqual(task.goal.steps.count(), 1)
        self.assertEqual(TimeEntry.objects.get(owner=fresh).task, task)
        self.assertTrue(HabitCheck.objects.filter(habit__owner=fresh).exists())
        self.assertTrue(JournalEntry.objects.filter(owner=fresh).exists())
        self.assertEqual(Task.objects.filter(owner=self.user).count(), 1)        # the original is untouched

        bad = SimpleUploadedFile("x.json", b'[{"model": "auth.user", "pk": 1, "fields": {"username": "evil"}}]', content_type="application/json")
        self.client.post(reverse("work:settings"), {"action": "restore", "backup": bad})
        self.assertFalse(User.objects.filter(username="evil").exists())          # only tracker records are read
        junk = SimpleUploadedFile("x.zip", io.BytesIO(b"not a zip").getvalue())
        r = self.client.post(reverse("work:settings"), {"action": "restore", "backup": junk}, follow=True)
        self.assertContains(r, "isn&#x27;t a Productivity backup")


class DayPlannerTests(TestCase):
    """Time blocking, snoozing, smarter quick add and estimate accuracy."""

    def setUp(self):
        self.user = User.objects.create_superuser("dev", "d@example.com", PW)
        self.client.force_login(self.user)
        self.today = timezone.localdate()
        self.tomorrow = self.today + timedelta(days=1)

    def test_planner_page_and_scheduling(self):
        t = Task.objects.create(owner=self.user, title="Write the migration", estimate_minutes=45, my_day=self.today)
        r = self.client.get(reverse("work:plan"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual([x["id"] for x in r.context["plan"]["unplanned"]], [t.pk])
        when = f"{self.tomorrow.isoformat()}T10:30"
        res = self.client.post(reverse("work:api_task_update", args=[t.pk]), {"scheduled_at": when}).json()
        self.assertEqual(res["scheduled_at"], when)
        t.refresh_from_db()
        self.assertEqual(t.my_day, self.tomorrow)                     # planned for a day: on that day's list
        plan = self.client.get(reverse("work:plan"), {"date": self.tomorrow.isoformat()}).context["plan"]
        self.assertEqual(plan["blocks"][0]["start"], 10 * 60 + 30)
        self.assertEqual(plan["blocks"][0]["length"], 45)
        self.assertEqual(self.client.post(reverse("work:api_task_update", args=[t.pk]), {"scheduled_at": "soon"}).status_code, 400)
        self.client.post(reverse("work:api_task_update", args=[t.pk]), {"scheduled_at": ""})
        t.refresh_from_db()
        self.assertIsNone(t.scheduled_at)

    def test_fill_my_day_packs_tasks_around_fixed_blocks(self):
        s = WorkSettings.for_user(self.user)
        s.day_start, s.day_end = datetime.min.time().replace(hour=9), datetime.min.time().replace(hour=12)
        s.save()
        fixed = Task.objects.create(owner=self.user, title="Standup", estimate_minutes=30, my_day=self.tomorrow,
                                    scheduled_at=aware(self.tomorrow.year, self.tomorrow.month, self.tomorrow.day, 9, 30))
        big = Task.objects.create(owner=self.user, title="Big", estimate_minutes=120, my_day=self.tomorrow, priority=3)
        small = Task.objects.create(owner=self.user, title="Small", my_day=self.tomorrow)              # 30 minutes when not estimated
        huge = Task.objects.create(owner=self.user, title="Huge", estimate_minutes=600, my_day=self.tomorrow)
        waiting = Task.objects.create(owner=self.user, title="Blocked", my_day=self.tomorrow, waiting_for="QA")
        res = self.client.post(reverse("work:api_plan"), {"action": "fill", "date": self.tomorrow.isoformat()}).json()
        self.assertEqual(res["placed"], 2)
        self.assertEqual(res["left"], 1)
        for t in (big, small, huge, waiting, fixed):
            t.refresh_from_db()
        local = lambda t: timezone.localtime(t.scheduled_at).strftime("%H:%M")   # noqa: E731
        self.assertEqual(local(big), "10:00")            # 9:00–9:30 is too short for 2h, and 9:30 is standup
        self.assertEqual(local(small), "09:00")
        self.assertIsNone(huge.scheduled_at)
        self.assertIsNone(waiting.scheduled_at)
        self.client.post(reverse("work:api_plan"), {"action": "clear", "date": self.tomorrow.isoformat()})
        self.assertFalse(Task.objects.filter(owner=self.user, scheduled_at__isnull=False).exists())

    def test_planner_is_private(self):
        other = User.objects.create_superuser("other", "o@example.com", PW)
        theirs = Task.objects.create(owner=other, title="Not yours", my_day=self.today)
        r = self.client.get(reverse("work:plan"))
        self.assertNotContains(r, "Not yours")
        self.assertEqual(self.client.post(reverse("work:api_task_update", args=[theirs.pk]), {"scheduled_at": f"{self.today}T10:00"}).status_code, 404)

    def test_snooze_hides_until_the_day(self):
        t = Task.objects.create(owner=self.user, title="Read the RFC", my_day=self.today)
        later = self.today + timedelta(days=3)
        self.client.post(reverse("work:api_task_update", args=[t.pk]), {"my_day": later.isoformat()})
        open_today, _done = services.today_tasks(self.user, self.today)
        self.assertNotIn(t, open_today)
        groups = {key: items for key, _label, items, _n in self.client.get(reverse("work:tasks")).context["groups"]}
        self.assertIn(t, groups["later"])
        self.assertNotIn(t, groups.get("todo", []))
        self.assertIn(t, services.today_tasks(self.user, later)[0])

    def test_snoozing_a_task_due_today_moves_its_due_date(self):
        t = Task.objects.create(owner=self.user, title="Reply to Karim", due_date=self.today, my_day=self.today)
        keep = Task.objects.create(owner=self.user, title="Release", due_date=self.today + timedelta(days=10))
        for task in (t, keep):
            self.client.post(reverse("work:api_task_update", args=[task.pk]), {"my_day": self.tomorrow.isoformat(), "later": "1"})
        t.refresh_from_db(), keep.refresh_from_db()
        self.assertEqual((t.my_day, t.due_date), (self.tomorrow, self.tomorrow))
        self.assertEqual(keep.due_date, self.today + timedelta(days=10))      # a later deadline stays
        self.assertNotIn(t, services.today_tasks(self.user, self.today)[0])

    def test_snoozing_takes_it_off_the_old_timeline(self):
        t = Task.objects.create(owner=self.user, title="Plan", my_day=self.today, scheduled_at=timezone.now())
        self.client.post(reverse("work:api_task_update", args=[t.pk]), {"my_day": self.tomorrow.isoformat()})
        t.refresh_from_db()
        self.assertIsNone(t.scheduled_at)

    def test_quick_add_understands_times_repeats_and_snooze(self):
        p = services.parse_quick("Call client at 3pm tomorrow", self.today)
        self.assertEqual((p.title, str(p.at), p.due), ("Call client", "15:00:00", self.tomorrow))
        p = services.parse_quick("Standup every weekday at 10:00 ~15m", self.today)
        self.assertEqual((p.title, p.repeat, p.estimate, str(p.at)), ("Standup", "weekdays", 15, "10:00:00"))
        p = services.parse_quick("Fix #482 room 3 at noon", self.today)
        self.assertEqual(p.title, "Fix #482 room 3 at noon")          # not times: left in the title
        self.assertIsNone(p.at)
        p = services.parse_quick("Read paper snooze:+3d", self.today)
        self.assertEqual(p.later, self.today + timedelta(days=3))
        r = self.client.post(reverse("work:api_task_add"), {"text": "Review PRs every monday at 9:30am"}).json()
        t = Task.objects.get(pk=r["id"]) if "id" in r else Task.objects.get(title="Review PRs")
        self.assertEqual(t.repeat, "weekly")
        self.assertEqual(t.due_date.weekday(), 0)
        self.assertEqual(timezone.localtime(t.remind_at).strftime("%H:%M"), "09:30")
        self.assertEqual(timezone.localtime(t.remind_at).date(), t.due_date)

    def test_every_work_day_follows_my_work_days(self):
        thursday = date(2026, 10, 15)
        self.assertEqual(services.next_due(thursday, "weekdays", "60123"), date(2026, 10, 18))   # Sun–Thu week: Thursday → Sunday
        self.assertEqual(services.next_due(date(2026, 10, 16), "weekdays", "01234"), date(2026, 10, 19))

    def test_estimate_accuracy(self):
        for title, est, worked in (("A", 60, 90), ("B", 30, 30), ("C", 120, 240)):
            t = Task.objects.create(owner=self.user, title=title, estimate_minutes=est, status=Status.DONE, completed_at=timezone.now())
            start = timezone.now() - timedelta(hours=8)
            TimeEntry.objects.create(owner=self.user, task=t, started_at=start, ended_at=start + timedelta(minutes=worked))
        est = services.estimate_accuracy(self.user, self.today - timedelta(days=1), self.today)
        self.assertEqual(est["count"], 3)
        self.assertAlmostEqual(est["ratio"], 360 / 210)
        self.assertTrue(est["under"])
        self.assertEqual(est["misses"][0]["task"].title, "C")
        self.assertEqual(est["on_target"], 1)
        r = self.client.get(reverse("work:reports"), {"range": "week"})
        self.assertContains(r, "×1.7")

    def test_calendar_feed_has_planned_blocks(self):
        t = Task.objects.create(owner=self.user, title="Deep work on caching", estimate_minutes=90,
                                scheduled_at=timezone.now() + timedelta(hours=2))
        self.client.post(reverse("work:settings"), {"action": "feed"})
        token = WorkSettings.objects.get(owner=self.user).feed_token
        body = self.client.get(reverse("work:feed", args=[token])).content.decode()
        self.assertIn(f"UID:block-{t.pk}@fintrack-work", body)
        self.assertIn("Deep work on caching", body)

    def test_today_shows_the_next_block(self):
        Task.objects.create(owner=self.user, title="Pair with Rahim", my_day=self.today,
                            scheduled_at=timezone.now() + timedelta(minutes=5))
        r = self.client.get(reverse("work:today"))
        self.assertContains(r, "Pair with Rahim")
        self.assertIsNotNone(r.context["next_block"])

    def test_work_hours_setting(self):
        r = self.client.post(reverse("work:settings"), {"action": "settings", "s-week_start": 6, "s-focus_minutes": 25, "s-short_break_minutes": 5,
                                                         "s-long_break_minutes": 15, "s-long_break_every": 4, "s-sound": "chime", "s-volume": 70,
                                                         "s-long_timer_hours": 3, "s-idle_minutes": 15, "s-work_day_list": ["0", "1"],
                                                         "s-daily_target_hours": "6", "s-day_start": "08:30", "s-day_end": "08:00"})
        self.assertEqual(r.status_code, 200)            # ends before it starts: refused
        self.assertContains(r, "end after it starts")


class WeekAndNotesTests(TestCase):
    """Plan the week, to-dos in notes becoming tasks, and [[links]] between notes."""

    def setUp(self):
        self.user = User.objects.create_superuser("dev", "d@example.com", PW)
        self.client.force_login(self.user)
        self.today = timezone.localdate()

    def test_week_shows_days_and_moves_tasks(self):
        s = WorkSettings.for_user(self.user)
        start = services.week_start(self.today, s.week_start)
        later = start + timedelta(days=6) if start + timedelta(days=6) > self.today else self.today
        planned = Task.objects.create(owner=self.user, title="On a day", my_day=later, estimate_minutes=90)
        due = Task.objects.create(owner=self.user, title="Due that day", due_date=later)
        loose = Task.objects.create(owner=self.user, title="No day yet", priority=3)
        Task.objects.create(owner=self.user, title="Waiting one", waiting_for="QA")
        r = self.client.get(reverse("work:week"))
        self.assertEqual(r.status_code, 200)
        day = next(d for d in r.context["days"] if d["date"] == later)
        self.assertEqual({t.title for t in day["tasks"]}, {"On a day", "Due that day"})
        self.assertEqual(day["planned"], 90 * 60)
        self.assertEqual([t.title for t in r.context["backlog"]], ["No day yet"])
        self.client.post(reverse("work:api_task_update", args=[loose.pk]), {"my_day": later.isoformat()})
        self.client.post(reverse("work:api_task_update", args=[planned.pk]), {"my_day": ""})        # back to "not planned yet"
        loose.refresh_from_db(), planned.refresh_from_db()
        self.assertEqual((loose.my_day, planned.my_day), (later, None))
        r = self.client.get(reverse("work:week"), {"start": (start + timedelta(days=7)).isoformat()})
        self.assertEqual(r.context["start"], start + timedelta(days=7))
        res = self.client.post(reverse("work:api_task_add"), {"text": "Write tests ~1h", "my_day": later.isoformat()}).json()
        self.assertEqual(Task.objects.get(pk=res["id"]).my_day, later)
        self.assertIn('data-est="60"', res["card"])

    def test_week_is_private(self):
        other = User.objects.create_superuser("other", "o@example.com", PW)
        Task.objects.create(owner=other, title="Someone else's", my_day=self.today)
        self.assertNotContains(self.client.get(reverse("work:week")), "Someone else")

    def test_note_todos_become_tasks_once_and_tick_back(self):
        api = Project.objects.create(owner=self.user, name="API")
        note = Note.objects.create(owner=self.user, title="Sprint planning", project=api,
                                   body="## Action items\n- [ ] Fix token refresh #auth tomorrow ~1h\n- [x] Already done\n* [ ] Write the ADR\nNot a todo")
        r = self.client.post(reverse("work:api_note_action", args=[note.pk]), {"action": "todos"}).json()
        self.assertEqual(r["count"], 2)
        fix = Task.objects.get(title="Fix token refresh")
        self.assertEqual((fix.project, fix.from_note, fix.estimate_minutes), (api, note, 60))
        self.assertEqual(fix.due_date, self.today + timedelta(days=1))
        self.assertEqual(list(fix.tags.values_list("name", flat=True)), ["auth"])
        note.refresh_from_db()
        self.assertIn(f"- [ ] [Fix token refresh](/work/tasks/{fix.pk}/)", note.body)
        self.assertIn("- [x] Already done", note.body)
        self.assertEqual(r["body"], note.body)
        again = self.client.post(reverse("work:api_note_action", args=[note.pk]), {"action": "todos"})
        self.assertEqual(again.status_code, 400)                         # nothing new: no duplicates
        self.assertEqual(Task.objects.filter(owner=self.user).count(), 2)
        self.client.post(reverse("work:api_task_done", args=[fix.pk]), {"done": "1"})
        note.refresh_from_db()
        self.assertIn(f"- [x] [Fix token refresh](/work/tasks/{fix.pk}/)", note.body)
        self.client.post(reverse("work:api_task_done", args=[fix.pk]), {"done": "0"})
        note.refresh_from_db()
        self.assertIn(f"- [ ] [Fix token refresh](/work/tasks/{fix.pk}/)", note.body)

    def test_wiki_links_and_backlinks(self):
        adr = Note.objects.create(owner=self.user, title="ADR: Use Postgres", body="We chose Postgres.")
        Note.objects.create(owner=self.user, title="Sprint 12", body="See [[ADR: Use Postgres]] for why.")
        other = User.objects.create_superuser("other", "o@example.com", PW)
        Note.objects.create(owner=other, title="Theirs", body="[[ADR: Use Postgres]]")
        r = self.client.get(reverse("work:note_go"), {"title": "adr: use postgres"})
        self.assertRedirects(r, reverse("work:note", args=[adr.pk]))
        r = self.client.get(reverse("work:note_go"), {"title": "Caching plan"})
        self.assertEqual(r.status_code, 302)
        self.assertIn("new=1", r["Location"])
        page = self.client.get(r["Location"])
        self.assertEqual(page.context["note_data"]["title"], "Caching plan")
        self.assertFalse(Note.objects.filter(title="Caching plan").exists())   # only made when you write in it
        page = self.client.get(reverse("work:note", args=[adr.pk]))
        self.assertEqual([n.title for n in page.context["backlinks"]], ["Sprint 12"])
        self.assertIn("Sprint 12", page.context["titles"])
        self.assertNotIn("Theirs", page.context["titles"])

    def test_restore_keeps_note_links(self):
        note = Note.objects.create(owner=self.user, title="Retro", body="- [ ] Fix flaky test")
        services.note_todos_to_tasks(self.user, note)
        rows = __import__("json").loads(__import__("django.core.serializers", fromlist=["serialize"]).serialize(
            "json", list(Note.objects.filter(owner=self.user)) + list(Task.objects.filter(owner=self.user))))
        new = User.objects.create_superuser("new", "n@example.com", PW)
        services.restore(new, rows)
        task = Task.objects.get(owner=new)
        self.assertEqual(task.from_note.owner, new)
