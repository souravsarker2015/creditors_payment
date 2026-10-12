"""Cycle targets: the plan worked out from them, and how the cycle is doing against it."""
from datetime import date, timedelta
from decimal import Decimal as D

from django.urls import reverse

from . import forecast, plan, services
from .models import CultureCycle
from .tests_wait import WaitBase, ago

TODAY = date.today()


class TargetTests(WaitBase):
    """1,000 Rui at 20 g, 100 dead, 500 kg of feed at ৳50, 400 g each today and growing 10 g a day."""

    def setUp(self):
        super().setUp()
        self.weigh(30, "100")
        self.weigh(0, "400")

    def set(self, **kw):
        values = {"target_size_g": 1000, "target_survival": 80, "target_fcr": D("1.6"), "target_price": D("250"),
                  "budget": D("60000"), "expected_harvest": TODAY + timedelta(days=60)}
        values.update(kw)
        CultureCycle.objects.filter(pk=self.cycle.pk).update(**values)
        return CultureCycle.objects.get(pk=self.cycle.pk)

    def lines(self, cycle):
        s = services.summarize(cycle)
        f = forecast.for_cycle(cycle)
        return {l.key: l for l in plan.compare(cycle, s, f, services.wait_plan(s, f))}

    def test_the_plan(self):
        cycle = self.set()
        s = services.summarize(cycle)
        self.assertEqual(plan.planned_kg(cycle, s), D("800"))          # 1,000 × 80% × 1 kg
        self.assertEqual(plan.planned_feed_kg(cycle, s), D("1248"))    # (800 − 20) × 1.6
        self.assertEqual(plan.planned_profit(cycle, s), D("140000"))   # 800 × ৳250 − ৳60,000

    def test_on_track(self):
        got = self.lines(self.set())
        self.assertEqual(got["survival"].now, "90%")
        self.assertEqual(got["fcr"].now, "≈ 1.47")
        self.assertEqual(got["size"].now, "400 g")
        self.assertEqual(got["harvest"].now, "≈ 900 kg")
        self.assertIn("47% spent, 50% of the time gone", got["cost"].note)
        self.assertEqual(got["profit"].now, "≈ ৳1,63,925")             # 900 kg × ৳250 − ৳28,000 − ৳33,075 more feed
        self.assertEqual({k: l.tone for k, l in got.items()},
                         {"survival": "good", "fcr": "good", "size": "good", "harvest": "good", "cost": "good", "profit": "good"})

    def test_slipping_and_off(self):
        got = self.lines(self.set(target_survival=95, target_fcr=D("1.3"), budget=D("30000"), expected_harvest=TODAY + timedelta(days=20)))
        self.assertEqual(got["survival"].tone, "warn")                  # 90% against 95%
        self.assertEqual(got["fcr"].tone, "critical")                   # 1.47 against 1.3
        self.assertEqual(got["size"].tone, "critical")                  # ready 40 days after the plan
        self.assertIn("40 days after the planned harvest", got["size"].note)
        self.assertEqual(got["cost"].tone, "warn")                      # 93% spent with 75% of the time gone

    def test_only_the_targets_set(self):
        self.assertEqual(self.lines(CultureCycle.objects.get(pk=self.cycle.pk)), {})
        got = self.lines(self.set(target_size_g=None, target_survival=None, target_price=None, budget=None, target_fcr=D("1.6")))
        self.assertEqual(list(got), ["fcr"])

    def test_targets_page_starts_with_usual_values(self):
        r = self.client.get(reverse("business:cycle_targets", args=[self.cycle.pk]))
        form = r.context["form"]
        self.assertEqual(form.initial["target_size_g"], 1000)            # Rui's selling size
        self.assertEqual(form.initial["target_survival"], 80)
        self.assertEqual(form.initial["target_fcr"], D("1.6"))
        self.assertEqual(form.initial["budget"], D("72000"))             # (fingerlings + 1,248 kg feed at ৳50) + 10%
        self.assertContains(r, "What this plan means")

    def test_save_and_see_it_on_the_cycle(self):
        url = reverse("business:cycle_detail", args=[self.cycle.pk])
        self.assertContains(self.client.get(url), "Set targets for this cycle")
        r = self.client.post(reverse("business:cycle_targets", args=[self.cycle.pk]),
                             {"target_size_g": "1000", "target_survival": "80", "target_fcr": "1.6", "target_price": "250",
                              "budget": "60000", "expected_harvest": (TODAY + timedelta(days=60)).isoformat()}, follow=True)
        self.assertContains(r, "Targets saved")
        self.assertContains(r, "Plan vs now")
        self.assertContains(r, 'data-plan-line="profit" data-state="good"')
        self.assertNotContains(r, "Set targets for this cycle")

    def test_harvest_must_follow_the_start(self):
        r = self.client.post(reverse("business:cycle_targets", args=[self.cycle.pk]), {"expected_harvest": ago(90).isoformat()})
        self.assertContains(r, "must come after the cycle starts")

    def test_viewers_cannot_set_targets(self):
        from apps.business.core.models import Membership, Role

        Membership.objects.filter(user=self.staff).update(role=Role.VIEWER)
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse("business:cycle_targets", args=[self.cycle.pk])).status_code, 403)
