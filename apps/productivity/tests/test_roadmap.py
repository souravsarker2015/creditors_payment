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
