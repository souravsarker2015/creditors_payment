"""Productivity: who can open it, privacy, every page, the timer, quick add,
tasks, notes, habits, focus, reports and working offline."""
from datetime import date, datetime, timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.business.core.models import Dashboard, UserDashboardAccess

from . import services
from .models import Habit, HabitCheck, JournalEntry, Note, Project, Snippet, Status, Tag, Task, TimeEntry, WorkSettings

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
                 "snippet_new", "habits", "habit_new", "journal", "reports", "settings", "help"]
        for name in names:
            with self.subTest(name):
                r = self.client.get(reverse(f"work:{name}"))
                self.assertEqual(r.status_code, 200)
                self.assertContains(r, 'id="work-config"')
        for url in [reverse("work:task", args=[self.t.pk]), reverse("work:project", args=[self.p.pk]), reverse("work:project_edit", args=[self.p.pk]),
                    reverse("work:note", args=[self.n.pk]), reverse("work:tasks") + "?view=board", reverse("work:tasks") + "?done=1&q=write",
                    reverse("work:reports") + "?range=30", reverse("work:reports") + "?range=custom&from=2026-01-01&to=2026-02-01",
                    reverse("work:notes") + "?new=1", reverse("work:time") + "?week=2026-01-05", reverse("work:journal") + "?date=2026-01-05"]:
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
        self.assertEqual(nxt.due_date, date(2026, 10, 12))      # skips the weekend
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
                                                        "s-long_break_every": "3", "s-sound": "bell", "s-volume": "40", "s-long_timer_hours": "4"})
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
