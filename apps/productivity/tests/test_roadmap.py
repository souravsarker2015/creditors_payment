"""Roadmaps: pieces of work and milestones in time and in lanes, whose progress, hours and likely finish
come from the tasks linked to them — and nobody but their owner can see or change them."""
import json
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .. import roadmap as rmp
from ..models import (
    Goal, GoalStep, Health, Roadmap, RoadmapItem, RoadmapLane, RoadmapStatus, RoadmapUpdate, Status, Task, TimeEntry,
)

PW = "Str0ng-pass-123"


class Base(TestCase):
    def setUp(self):
        self.me = User.objects.create_superuser("me", "me@example.com", PW)
        self.client.force_login(self.me)
        self.today = timezone.localdate()
        self.rm = Roadmap.objects.create(owner=self.me, title="Product")
        self.lane = RoadmapLane.objects.create(roadmap=self.rm, name="Features")

    def piece(self, **kw):
        kw.setdefault("title", "Payments")
        return RoadmapItem.objects.create(roadmap=self.rm, lane=self.lane, **kw)

    def row(self, item):
        return rmp.one(item, self.today)

    def api(self, item, **data):
        return self.client.post(reverse("work:api_roadmap_item", args=[item.pk]), data)

    def rm_api(self, **data):
        return self.client.post(reverse("work:api_roadmap", args=[self.rm.pk]), data)


class ProgressTests(Base):
    def test_progress_comes_from_tasks_weighted_by_points(self):
        it = self.piece()
        Task.objects.create(owner=self.me, title="Big", points=8, roadmap_item=it, status=Status.DONE, completed_at=timezone.now())
        Task.objects.create(owner=self.me, title="Small", points=2, roadmap_item=it)
        r = self.row(it)
        self.assertEqual((r["progress"], r["from"], r["tasks"]), (80, "tasks", {"done": 1, "total": 2, "open": 1}))

    def test_then_its_goal_then_by_hand_and_done_is_done(self):
        g = Goal.objects.create(owner=self.me, title="Ship v2")
        GoalStep.objects.create(goal=g, text="a", done=True)
        GoalStep.objects.create(goal=g, text="b")
        it = self.piece(goal=g, progress=10)
        self.assertEqual((self.row(it)["progress"], self.row(it)["from"]), (50, "goal"))
        it.goal = None
        it.save()
        self.assertEqual((self.row(it)["progress"], self.row(it)["from"]), (10, "manual"))
        it.status = RoadmapStatus.DONE
        it.save()
        self.assertEqual(self.row(it)["progress"], 100)

    def test_hours_tracked_on_its_tasks_add_up(self):
        it = self.piece()
        t = Task.objects.create(owner=self.me, title="Build", roadmap_item=it)
        start = timezone.now() - timedelta(hours=3)
        TimeEntry.objects.create(owner=self.me, task=t, started_at=start, ended_at=start + timedelta(minutes=90))
        self.assertEqual(self.row(it)["minutes"], 90)


class HealthTests(Base):
    def test_late_is_off_track(self):
        it = self.piece(status=RoadmapStatus.ACTIVE, start_date=self.today - timedelta(days=20), end_date=self.today - timedelta(days=1))
        self.assertEqual(self.row(it)["auto"], Health.OFF_TRACK)

    def test_well_behind_the_time_gone_by_is_at_risk(self):
        it = self.piece(status=RoadmapStatus.ACTIVE, start_date=self.today - timedelta(days=30), end_date=self.today + timedelta(days=10), progress=10)
        self.assertEqual(self.row(it)["auto"], Health.AT_RISK)
        it.progress = 70
        it.save()
        self.assertEqual(self.row(it)["auto"], Health.ON_TRACK)
        it.progress = None          # nothing measured yet (no tasks, no goal, nothing set): not called behind
        it.save()
        self.assertEqual(self.row(it)["auto"], Health.ON_TRACK)

    def test_the_pace_says_when_it_will_be_done(self):
        it = self.piece(status=RoadmapStatus.ACTIVE, start_date=self.today, end_date=self.today + timedelta(days=5))
        Task.objects.create(owner=self.me, title="Done lately", roadmap_item=it, status=Status.DONE, completed_at=timezone.now() - timedelta(days=3))
        for i in range(3):
            Task.objects.create(owner=self.me, title=f"Open {i}", roadmap_item=it)
        r = self.row(it)
        self.assertEqual(r["likely"], (self.today + timedelta(days=84)).isoformat())     # 3 open at 1 per 28 days
        self.assertEqual(r["auto"], Health.AT_RISK)

    def test_an_update_sets_its_health_and_deleting_it_goes_back(self):
        it = self.piece()
        r = self.api(it, action="update", health="at_risk", text="Waiting on the bank")
        self.assertEqual(r.json()["item"]["health"], "at_risk")
        up = RoadmapUpdate.objects.get(item=it)
        self.assertEqual((up.text, up.health), ("Waiting on the bank", "at_risk"))
        self.assertEqual(self.api(it, action="update", health="", text="").status_code, 400)
        r = self.api(it, action="update_delete", update=up.pk)
        self.assertEqual(r.json()["item"]["health"], "")


class ChangesTests(Base):
    def test_saving_fields(self):
        it = self.piece()
        g = Goal.objects.create(owner=self.me, title="G")
        r = self.api(it, action="save", title="  Card payments ", start=str(self.today), end=str(self.today + timedelta(days=9)),
                     status="active", impact="4", effort="9", color="teal", goal=g.pk, horizon="later").json()["item"]
        self.assertEqual((r["title"], r["status"], r["horizon"], r["impact"], r["effort"], r["color"], r["goal"]),
                         ("Card payments", "active", "now", 4, None, "teal", g.pk))      # in progress is "now"; effort 9 isn't 1–5
        self.assertEqual(self.api(it, action="save", start=str(self.today), end=str(self.today - timedelta(days=1))).status_code, 400)
        self.assertEqual(self.api(it, action="save", title=" ").status_code, 400)
        self.assertEqual(self.api(it, action="save", start="soon").status_code, 400)
        it.refresh_from_db()
        self.assertEqual(it.title, "Card payments")

    def test_done_is_stamped_and_a_milestone_is_one_day(self):
        it = self.piece()
        self.api(it, action="save", status="done")
        it.refresh_from_db()
        self.assertIsNotNone(it.completed_at)
        r = self.api(it, action="save", kind="milestone", start=str(self.today), end=str(self.today + timedelta(days=4))).json()["item"]
        self.assertEqual(r["start"], r["end"])

    def test_waiting_on_each_other_is_refused(self):
        a, b, c = self.piece(title="A"), self.piece(title="B"), self.piece(title="C")
        self.assertEqual(self.api(b, action="save", deps=f"{a.pk}").json()["item"]["deps"], [a.pk])
        self.api(c, action="save", deps=f"{b.pk}")
        self.assertEqual(self.api(a, action="save", deps=f"{c.pk}").status_code, 400)
        self.assertEqual(self.api(a, action="save", deps=f"{a.pk}").json()["item"]["deps"], [])

    def test_tasks_added_linked_ticked_and_unlinked(self):
        it = self.piece()
        r = self.api(it, action="task_add", title="Stripe keys").json()
        t = Task.objects.get(pk=r["task"]["id"])
        self.assertEqual((t.roadmap_item, r["item"]["tasks"]["total"]), (it, 1))
        other = Task.objects.create(owner=self.me, title="Refunds")
        found = self.api(it, action="task_search", q="ref").json()["tasks"]
        self.assertEqual([x["id"] for x in found], [other.pk])
        self.assertEqual(self.api(it, action="task_link", task=other.pk).json()["item"]["tasks"]["total"], 2)
        r = self.api(it, action="task_done", task=t.pk, done="1").json()
        self.assertEqual((r["task"]["done"], r["item"]["progress"]), (True, 50))
        self.api(it, action="task_unlink", task=other.pk)
        self.assertEqual(self.row(it)["progress"], 100)
        detail = self.client.get(reverse("work:api_roadmap_item", args=[it.pk])).json()
        self.assertEqual([x["title"] for x in detail["tasks"]], ["Stripe keys"])

    def test_a_repeating_task_keeps_its_place_on_the_roadmap(self):
        from .. import services

        it = self.piece()
        t = Task.objects.create(owner=self.me, title="Weekly demo", roadmap_item=it, repeat="weekly", due_date=self.today)
        nxt = services.set_done(t, True)
        self.assertEqual(nxt.roadmap_item, it)

    def test_lanes_and_new_pieces(self):
        lane = self.rm_api(action="lane_add", name="Mobile", color="pink").json()["lane"]
        r = self.rm_api(action="item_add", title="Offline mode", lane=lane["id"], start=str(self.today), end=str(self.today + timedelta(days=13))).json()["item"]
        self.assertEqual((r["lane"], r["start"]), (lane["id"], str(self.today)))
        self.assertEqual(self.rm_api(action="item_add", title="").status_code, 400)
        self.assertEqual(self.rm_api(action="item_add", title="Bad", start="2026-05-05", end="2026-05-01").status_code, 400)
        self.assertEqual(RoadmapItem.objects.filter(title="Bad").count(), 0)
        self.rm_api(action="lane_delete", lane=lane["id"])
        self.assertIsNone(RoadmapItem.objects.get(pk=r["id"]).lane)

    def test_delete_goes_to_recently_deleted_and_comes_back(self):
        it = self.piece()
        t = Task.objects.create(owner=self.me, title="Stays", roadmap_item=it)
        undo = self.api(it, action="delete").json()["undo"]
        self.assertFalse(RoadmapItem.objects.filter(pk=it.pk).exists())
        t.refresh_from_db()
        self.assertIsNone(t.roadmap_item)
        self.client.post(undo)
        self.assertTrue(RoadmapItem.objects.filter(pk=it.pk).exists())


class PagesTests(Base):
    def test_starting_points(self):
        for key in rmp.TEMPLATES:
            r = self.client.post(reverse("work:roadmaps"), {"title": "", "template": key})
            rm = Roadmap.objects.filter(owner=self.me).latest("pk")
            self.assertRedirects(r, reverse("work:roadmap", args=[rm.pk]))
            self.assertGreaterEqual(rm.lanes.count(), 1)
        product = Roadmap.objects.get(owner=self.me, title="Product roadmap")
        self.assertEqual(product.items.filter(kind="milestone").count(), 1)
        self.assertTrue(all(i.start_date and i.end_date and i.start_date <= i.end_date for i in product.items.all()))

    def test_the_pages(self):
        self.piece(start_date=self.today, end_date=self.today + timedelta(days=9), status=RoadmapStatus.ACTIVE)
        html = self.client.get(reverse("work:roadmaps")).content.decode()
        self.assertIn("Product", html)
        self.assertIn("1 in progress", html)
        html = self.client.get(reverse("work:roadmap", args=[self.rm.pk])).content.decode()
        data = json.loads(html.split('id="roadmap-data" type="application/json">')[1].split("</script>")[0])
        self.assertEqual([i["title"] for i in data["items"]], ["Payments"])
        self.assertEqual(len(data["momentum"]), rmp.MOMENTUM_WEEKS)
        self.assertIn('id="roadmap-text"', html)
        csv = self.client.get(reverse("work:roadmap_export", args=[self.rm.pk])).content.decode("utf-8-sig")
        self.assertIn("Payments,Piece of work,Features,In progress", csv)

    def test_copy_archive_and_delete(self):
        a, b = self.piece(title="A"), self.piece(title="B")
        b.depends_on.add(a)
        url = self.rm_api(action="duplicate").json()["url"]
        copy = Roadmap.objects.exclude(pk=self.rm.pk).get(owner=self.me)
        self.assertEqual(url, reverse("work:roadmap", args=[copy.pk]))
        cb = copy.items.get(title="B")
        self.assertEqual([d.title for d in cb.depends_on.all()], ["A"])
        self.assertNotEqual(cb.depends_on.get().pk, a.pk)
        self.assertEqual(cb.lane.roadmap, copy)
        self.assertTrue(self.rm_api(action="archive").json()["archived"])
        self.rm_api(action="delete")
        self.assertFalse(Roadmap.objects.filter(pk=self.rm.pk).exists())

    def test_a_task_can_be_put_on_a_roadmap_from_its_page(self):
        it = self.piece()
        t = Task.objects.create(owner=self.me, title="Button")
        html = self.client.get(reverse("work:task", args=[t.pk])).content.decode()
        self.assertIn("Product › Payments", html)
        self.client.post(reverse("work:api_task_update", args=[t.pk]), {"roadmap_item": it.pk})
        t.refresh_from_db()
        self.assertEqual(t.roadmap_item, it)
        self.assertIn(f"?item={it.pk}", self.client.get(reverse("work:task", args=[t.pk])).content.decode())

    def test_found_by_search(self):
        self.piece(title="Quarterly launch")
        r = self.client.get(reverse("search") + "?q=quarterly")
        self.assertContains(r, "Quarterly launch")


class OnlyMineTests(Base):
    def test_someone_else_cant_see_or_change_it(self):
        it = self.piece()
        mine = Task.objects.create(owner=self.me, title="Mine")
        other = User.objects.create_superuser("other", "o@example.com", PW)
        self.client.force_login(other)
        self.assertEqual(self.client.get(reverse("work:roadmap", args=[self.rm.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("work:roadmap_export", args=[self.rm.pk])).status_code, 404)
        self.assertEqual(self.api(it, action="save", title="Mine now").status_code, 404)
        self.assertEqual(self.rm_api(action="delete").status_code, 404)
        self.assertEqual(self.client.get(reverse("work:api_roadmap_item", args=[it.pk])).status_code, 404)
        theirs = Roadmap.objects.create(owner=other, title="Theirs")
        their_item = RoadmapItem.objects.create(roadmap=theirs, title="T")
        self.assertEqual(self.client.post(reverse("work:api_roadmap_item", args=[their_item.pk]), {"action": "task_link", "task": mine.pk}).status_code, 404)
        self.client.post(reverse("work:api_roadmap_item", args=[their_item.pk]), {"action": "save", "deps": str(it.pk), "lane": self.lane.pk})
        their_item.refresh_from_db()
        self.assertEqual((list(their_item.depends_on.all()), their_item.lane), ([], None))
        self.rm.title = "Zebra plan"
        self.rm.save()
        self.assertNotContains(self.client.get(reverse("work:roadmaps")), "Zebra plan")


class PlanAndSlipTests(Base):
    """The saved plan (a baseline), what waits on a piece being pushed along, and several changed at once."""

    def test_saving_the_plan_shows_how_far_each_piece_moved(self):
        it = self.piece(start_date=self.today, end_date=self.today + timedelta(days=9))
        r = self.rm_api(action="plan_save").json()
        self.assertTrue(r["baseline"])
        self.assertEqual(r["items"][0]["planEnd"], (self.today + timedelta(days=9)).isoformat())
        self.api(it, action="save", end=(self.today + timedelta(days=14)).isoformat())
        row = self.row(it)
        self.assertEqual((row["planEnd"], row["end"]), ((self.today + timedelta(days=9)).isoformat(), (self.today + timedelta(days=14)).isoformat()))
        csv = self.client.get(reverse("work:roadmap_export", args=[self.rm.pk])).content.decode("utf-8-sig")
        self.assertIn("Planned end", csv)
        self.assertIn((self.today + timedelta(days=9)).isoformat(), csv)
        self.rm.refresh_from_db()
        copy = rmp.duplicate(self.rm)
        self.assertIsNotNone(copy.baseline_at)
        self.assertEqual(copy.items.get().plan_end, self.today + timedelta(days=9))
        self.rm_api(action="plan_forget")
        self.rm.refresh_from_db()
        it.refresh_from_db()
        self.assertEqual((self.rm.baseline_at, it.plan_end), (None, None))

    def test_what_waits_on_it_is_pushed_after_it_in_a_chain(self):
        d = lambda n: self.today + timedelta(days=n)       # noqa: E731
        a = self.piece(title="A", start_date=d(0), end_date=d(10))
        b = self.piece(title="B", start_date=d(5), end_date=d(8))        # starts before A ends
        c = self.piece(title="C", start_date=d(9), end_date=d(12))       # starts before B will end
        done = self.piece(title="Done", start_date=d(2), end_date=d(3), status=RoadmapStatus.DONE)
        far = self.piece(title="Far", start_date=d(40), end_date=d(45))  # already well after
        b.depends_on.add(a)
        c.depends_on.add(b)
        done.depends_on.add(a)
        far.depends_on.add(a)
        r = self.api(a, action="push").json()
        self.assertEqual(sorted(i["title"] for i in r["items"]), ["B", "C"])
        self.assertEqual(r["before"][str(b.pk)], [d(5).isoformat(), d(8).isoformat()])
        for x in (b, c, done, far):
            x.refresh_from_db()
        self.assertEqual((b.start_date, b.end_date), (d(11), d(14)))
        self.assertEqual((c.start_date, c.end_date), (d(15), d(18)))
        self.assertEqual((done.start_date, far.start_date), (d(2), d(40)))

    def test_several_at_once_and_only_on_this_roadmap(self):
        a, b = self.piece(title="A"), self.piece(title="B")
        other = Roadmap.objects.create(owner=self.me, title="Other")
        elsewhere = RoadmapItem.objects.create(roadmap=other, title="Elsewhere")
        r = self.rm_api(action="bulk", ids=f"{a.pk},{b.pk},{elsewhere.pk}", status="active", lane="").json()
        self.assertEqual(sorted(i["title"] for i in r["items"]), ["A", "B"])
        for x in (a, b, elsewhere):
            x.refresh_from_db()
        self.assertEqual((a.status, a.horizon, a.lane, b.status), ("active", "now", None, "active"))
        self.assertEqual(elsewhere.status, "planned")
        r = self.rm_api(action="bulk_delete", ids=f"{a.pk},{b.pk}").json()
        self.assertEqual((r["count"], len(r["undo"])), (2, 2))
        self.assertFalse(RoadmapItem.objects.filter(pk__in=[a.pk, b.pk]).exists())
        for u in r["undo"]:
            self.client.post(u)
        self.assertEqual(RoadmapItem.objects.filter(pk__in=[a.pk, b.pk]).count(), 2)
        self.assertEqual(self.rm_api(action="bulk", ids="", status="done").status_code, 400)

    def test_finishing_it_can_finish_its_open_tasks(self):
        it = self.piece()
        for title in ("a", "b"):
            Task.objects.create(owner=self.me, title=title, roadmap_item=it)
        r = self.api(it, action="tasks_close").json()
        self.assertEqual((r["count"], r["item"]["tasks"]["open"], r["item"]["progress"]), (2, 0, 100))


class ElsewhereTests(Base):
    """Roadmaps show up where the rest of the day's work is: Today, goals, projects, the review and the calendar."""

    def test_today_shows_milestones_coming_and_work_in_trouble(self):
        self.piece(title="Launch day", kind="milestone", start_date=self.today + timedelta(days=3), end_date=self.today + timedelta(days=3))
        self.piece(title="Late one", status=RoadmapStatus.ACTIVE, start_date=self.today - timedelta(days=20), end_date=self.today - timedelta(days=2))
        self.piece(title="Fine one", status=RoadmapStatus.ACTIVE, start_date=self.today, end_date=self.today + timedelta(days=30))
        self.piece(title="Far milestone", kind="milestone", start_date=self.today + timedelta(days=60), end_date=self.today + timedelta(days=60))
        html = self.client.get(reverse("work:today")).content.decode()
        self.assertIn("Launch day", html)
        self.assertIn("in 3 days", html)
        self.assertIn("Late one", html)
        self.assertIn("2 days late", html)
        self.assertNotIn("Fine one", html)
        self.assertNotIn("Far milestone", html)
        self.rm.is_archived = True
        self.rm.save()
        self.assertNotIn("Launch day", self.client.get(reverse("work:today")).content.decode())

    def test_goal_and_project_pages_list_their_pieces(self):
        from ..models import Project

        g = Goal.objects.create(owner=self.me, title="Ship v2")
        p = Project.objects.create(owner=self.me, name="App")
        self.piece(title="Payments", goal=g, project=p)
        self.assertContains(self.client.get(reverse("work:goal", args=[g.pk])), "Payments")
        self.assertContains(self.client.get(reverse("work:project", args=[p.pk])), "On roadmaps")

    def test_review_calendar_and_feed(self):
        from ..models import WorkSettings

        it = self.piece(title="Payments", start_date=self.today, end_date=self.today + timedelta(days=4))
        self.api(it, action="save", status="done")
        html = self.client.get(reverse("work:review") + "?preset=week").content.decode()
        self.assertIn("Roadmap pieces finished", html)
        self.assertIn("Payments", html)
        self.assertIn("Payments (Product)", self.client.get(reverse("work:review") + "?preset=week&export=md").content.decode())
        self.piece(title="Beta out", kind="milestone", start_date=self.today, end_date=self.today)
        self.assertContains(self.client.get(reverse("work:calendar")), "Beta out")
        token = WorkSettings.for_user(self.me).new_feed_token()
        self.assertIn("Beta out", self.client.get(reverse("work:feed", args=[token])).content.decode())


class JsonTests(Base):
    """A timeline roadmap as JSON: downloaded, imported again, or written by an AI assistant."""

    def test_download_then_import_gives_the_same_roadmap(self):
        a = self.piece(start_date=self.today, end_date=self.today + timedelta(days=13), status=RoadmapStatus.ACTIVE, impact=4, effort=2,
                       description="Cards and wallets")
        b = self.piece(title="Launch", kind="milestone", start_date=self.today + timedelta(days=20), end_date=self.today + timedelta(days=20))
        b.depends_on.add(a)
        RoadmapItem.objects.create(roadmap=self.rm, title="Someday")
        r = self.client.get(reverse("work:roadmap_json", args=[self.rm.pk]))
        self.assertIn("product.timeline-roadmap.json", r["Content-Disposition"])
        data = json.loads(r.content)
        self.assertEqual((data["format"], data["lanes"][0]["name"]), ("timeline-roadmap", "Features"))
        self.assertEqual(data["lanes"][0]["items"][1]["waitsOn"], ["payments"])
        self.assertEqual(data["items"][0]["title"], "Someday")
        r = self.client.post(reverse("work:api_roadmap_import"), {"text": json.dumps(data)}).json()
        copy = Roadmap.objects.exclude(pk=self.rm.pk).get()
        self.assertEqual(r["url"], reverse("work:roadmap", args=[copy.pk]))
        pay = copy.items.get(title="Payments")
        self.assertEqual((pay.start_date, pay.end_date, pay.status, pay.impact, pay.effort, pay.lane.name, pay.description),
                         (a.start_date, a.end_date, "active", 4, 2, "Features", "Cards and wallets"))
        self.assertEqual(list(copy.items.get(title="Launch").depends_on.all()), [pay])
        self.assertIsNone(copy.items.get(title="Someday").lane)

    def test_what_an_ai_assistant_writes_weeks_from_now_and_loose_words(self):
        fields, lanes, items = rmp.build(rmp.EXAMPLE, self.today)
        monday = self.today - timedelta(days=self.today.weekday())
        mvp = items[0]
        self.assertEqual((mvp["start"], mvp["end"]), (monday, monday + timedelta(days=34)))
        launch = [i for i in items if i["key"] == "launch"][0]
        self.assertEqual((launch["kind"], launch["start"], launch["end"]), ("milestone", monday + timedelta(weeks=10), monday + timedelta(weeks=10)))
        _f, _l, items = rmp.build({"title": "x", "items": [{"title": "A", "status": "In progress", "type": "Release", "color": "neon"}]})
        self.assertEqual((items[0]["status"], items[0]["kind"], items[0]["horizon"], items[0]["color"]), ("active", "milestone", "now", ""))

    def test_mistakes_say_where(self):
        cases = [({"lanes": []}, "title"), ({"title": "x"}, "lanes"), ({"title": "x", "lanes": [{"items": []}]}, "Lane 1"),
                 ({"title": "x", "lanes": [{"name": "A", "items": [{"title": "a"}, {}]}]}, "Lane 1 › item 2"),
                 ({"title": "x", "items": [{"title": "a", "start": "soon"}]}, "2027-01-31"),
                 ({"title": "x", "items": [{"title": "a", "waitsOn": ["b"]}]}, "“b”"),
                 ({"title": "x", "items": [{"id": "a", "title": "a", "waitsOn": ["b"]}, {"id": "b", "title": "b", "waitsOn": ["a"]}]}, "circle"),
                 ({"title": "x", "items": [{"id": "a", "title": "a"}, {"id": "a", "title": "b"}]}, "twice")]
        for spec, said in cases:
            with self.subTest(said=said), self.assertRaises(rmp.Invalid) as e:
                rmp.build(spec)
            self.assertIn(said, str(e.exception))

    def test_one_import_box_takes_either_kind(self):
        from .. import paths as lp
        from ..models import LearningPath

        url = reverse("work:api_roadmap_import")
        chat = "Sure! Here it is:\n```json\n" + json.dumps(rmp.EXAMPLE) + "\n```\nGood luck!"
        r = self.client.post(url, {"text": chat, "check": "1"}).json()
        self.assertEqual((r["info"]["kind"], r["info"]["lanes"], r["info"]["items"], r["info"]["milestones"]), ("timeline", 2, 4, 1))
        self.assertIn("2 lanes", r["info"]["summary"])
        r = self.client.post(reverse("work:api_path_import"), {"text": json.dumps(lp.EXAMPLE), "check": "1"}).json()
        self.assertEqual(r["info"]["kind"], "learning")
        r = self.client.post(url, {"text": json.dumps(lp.EXAMPLE)}).json()     # a learning roadmap given on the Roadmaps page
        self.assertEqual(r["url"], reverse("work:path", args=[LearningPath.objects.get().pk]))
        r = self.client.post(reverse("work:api_path_import"), {"text": chat}).json()
        self.assertEqual(r["url"], reverse("work:roadmap", args=[Roadmap.objects.get(title=rmp.EXAMPLE["title"]).pk]))
        r = self.client.post(url, {"text": '{"title": "x", "lanes": [{"name": ""}]}', "check": "1"})
        self.assertEqual((r.status_code, r.json()["ok"]), (200, False))
        self.assertEqual(json.loads(self.client.get(reverse("work:roadmap_example")).content)["format"], "timeline-roadmap")

    def test_the_list_pages_lead_to_each_other_and_to_import(self):
        html = self.client.get(reverse("work:roadmaps")).content.decode()
        for text in ("Learning roadmaps", "Import JSON", "Backend developer", "Rust: beginner to senior", reverse("work:api_roadmap_import"), "timeline-roadmap"):
            self.assertIn(text, html)
        html = self.client.get(reverse("work:paths")).content.decode()
        for text in ("Timeline roadmaps", "Import JSON", "Make one with ChatGPT or Claude", "timeline-roadmap", "learning-roadmap"):
            self.assertIn(text, html)
        html = self.client.get(reverse("work:roadmap", args=[self.rm.pk])).content.decode()
        self.assertIn(reverse("work:roadmap_json", args=[self.rm.pk]), html)

    def test_someone_elses_cant_be_downloaded(self):
        other = User.objects.create_superuser("other", "o@example.com", PW)
        self.client.force_login(other)
        self.assertEqual(self.client.get(reverse("work:roadmap_json", args=[self.rm.pk])).status_code, 404)
