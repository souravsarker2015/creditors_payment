"""Lists show everything: long text folds behind “More”, long histories by month, notes in rows, a readable activity log."""
from datetime import date, timedelta
from decimal import Decimal as D

from django.test import TestCase
from django.urls import reverse

from apps.business.feed.models import FeedProduct, FeedUsage
from apps.business.parties.models import Party
from apps.business.ponds.models import CultureCycle, Pond
from apps.core.templatetags.ui import by_month, sum_attr

from .audit_display import describe, tidy
from .models import AuditLog, Unit
from .testing import make_farm

TODAY = date.today()


class FilterTests(TestCase):
    def test_by_month_keeps_order_and_splits_months(self):
        class R:
            def __init__(self, d, kg):
                self.date, self.kg = d, kg
        rows = [R(date(2026, 10, 5), D("2")), R(date(2026, 10, 1), D("3")), R(date(2026, 9, 30), None)]
        groups = by_month(rows)
        self.assertEqual([g["month"] for g in groups], [date(2026, 10, 1), date(2026, 9, 1)])
        self.assertEqual(sum_attr(groups[0]["items"], "kg"), D("5"))
        self.assertEqual(len(by_month([("buy", date(2026, 1, 2), None)], 1)), 1)

    def test_tidy_numbers(self):
        self.assertEqual(tidy("Floating feed 28% 6.000000 kg"), "Floating feed 28% 6 kg")
        self.assertEqual(tidy("60.500"), "60.5")
        self.assertEqual(tidy("Pond P-1"), "Pond P-1")


class PageTests(TestCase):
    def setUp(self):
        self.b, self.owner, _ = make_farm()
        self.client.force_login(self.owner)

    def test_activity_log_is_readable(self):
        p = Party.objects.create(business=self.b, name="Karim", is_supplier=True)
        p.name, p.phone = "Karim Traders", "01711"
        p.save()
        entry = describe([AuditLog.objects.filter(business=self.b, action="update").first()])[0]
        labels = [c[0] for c in entry.change_list]
        self.assertIn("Name", labels)
        self.assertIn("Phone", labels)
        r = self.client.get(reverse("business:activity"))
        self.assertContains(r, "2 changes")
        self.assertContains(r, "Karim Traders")
        self.assertNotContains(r, "is_deleted")

    def test_all_feedings_shown_by_month(self):
        kg = Unit.objects.get(business=self.b, symbol="kg")
        cycle = CultureCycle.objects.create(business=self.b, pond=Pond.objects.create(business=self.b, name="East"), start_date=TODAY - timedelta(days=100))
        feed = FeedProduct.objects.create(business=self.b, name="Grower", bag_size=D("25"), bag_unit=kg)
        for n in range(90):
            FeedUsage.objects.create(business=self.b, cycle=cycle, date=TODAY - timedelta(days=n), product=feed, quantity=D("10"), unit=kg)
        r = self.client.get(reverse("business:cycle_detail", args=[cycle.pk]))
        self.assertEqual(len(r.context["feedings"]), 90)
        self.assertContains(r, 'class="month-group"', count=None)
        self.assertGreaterEqual(r.content.decode().count('class="month-group"'), 3)

    def test_notes_show_in_rows(self):
        Party.objects.create(business=self.b, name="Hatchery", is_supplier=True, notes="Delivers on Tuesdays")
        r = self.client.get(reverse("business:suppliers"))
        self.assertContains(r, 'class="row-note" data-clamp="2">Delivers on Tuesdays')

    def test_more_button_script_on_every_page(self):
        self.assertContains(self.client.get(reverse("business:home")), "clamp-more")
