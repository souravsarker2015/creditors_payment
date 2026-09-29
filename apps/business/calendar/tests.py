"""The farm calendar: Bangla dates, repeats, what shows up, and the pages."""
from datetime import date, time, timedelta
from decimal import Decimal as D

from django.test import TestCase
from django.urls import reverse
from django.utils import translation

from apps.business.core.models import Unit
from apps.business.core.testing import make_farm
from apps.business.parties.models import Party
from apps.business.ponds.models import CultureCycle, Pond, Stocking, WaterTest
from apps.business.sales.models import FishSale, FishSaleLine
from apps.business.species.models import Species

from . import bangla as bn
from .models import CalendarEvent, Repeat
from .services import collect, holiday_items, occurrences, todays_events


class BanglaCalendarTests(TestCase):
    def test_national_days_fall_on_their_bangla_dates(self):
        cases = {date(2026, 4, 14): (1433, 1, 1), date(2026, 2, 21): (1432, 11, 8), date(2026, 3, 26): (1432, 12, 12),
                 date(2025, 12, 16): (1432, 9, 1), date(2026, 4, 13): (1432, 12, 30)}
        for d, (y, m, day) in cases.items():
            b = bn.to_bangla(d)
            self.assertEqual((b.year, b.month, b.day), (y, m, day), d)

    def test_month_lengths(self):
        self.assertEqual([bn.month_length(1433, m) for m in range(1, 13)], [31] * 6 + [30] * 4 + [29, 30])
        self.assertEqual(bn.month_length(1430, 11), 30)     # Falgun 1430 holds 29 February 2024

    def test_every_day_converts_back(self):
        d = date(2019, 1, 1)
        while d < date(2032, 1, 1):
            b = bn.to_bangla(d)
            self.assertEqual(bn.from_bangla(b.year, b.month, b.day), d)
            d += timedelta(days=1)

    def test_impossible_dates_are_refused(self):
        with self.assertRaises(ValueError):
            bn.from_bangla(1433, 11, 30)     # Falgun 1433 has 29 days
        with self.assertRaises(ValueError):
            bn.from_bangla(1433, 13, 1)

    def test_formats_and_digits(self):
        b = bn.to_bangla(date(2026, 9, 29))
        self.assertEqual(b.format(bangla=True), "১৪ আশ্বিন ১৪৩৩")
        self.assertEqual(b.format(bangla=False), "14 Ashwin 1433")
        self.assertEqual(b.season_name(False), "Autumn")
        self.assertEqual(bn.bn_digits("07:30"), "০৭:৩০")


class RepeatTests(TestCase):
    def ev(self, **kw):
        return CalendarEvent(title="x", **kw)

    def dates(self, e, start, end):
        return list(occurrences(e, start, end))

    def test_one_off_and_several_days(self):
        self.assertEqual(self.dates(self.ev(date=date(2026, 9, 3)), date(2026, 9, 1), date(2026, 9, 30)), [date(2026, 9, 3)])
        e = self.ev(date=date(2026, 8, 30), end_date=date(2026, 9, 2))
        self.assertEqual(self.dates(e, date(2026, 9, 1), date(2026, 9, 30)), [date(2026, 9, 1), date(2026, 9, 2)])

    def test_weekly_starts_from_the_first_date(self):
        e = self.ev(date=date(2026, 9, 3), repeat=Repeat.WEEKLY)
        self.assertEqual(self.dates(e, date(2026, 9, 1), date(2026, 9, 30)), [date(2026, 9, d) for d in (3, 10, 17, 24)])
        self.assertEqual(self.dates(e, date(2026, 12, 1), date(2026, 12, 8)), [date(2026, 12, 3)])

    def test_monthly_on_the_31st_uses_the_last_day(self):
        e = self.ev(date=date(2026, 1, 31), repeat=Repeat.MONTHLY)
        self.assertEqual(self.dates(e, date(2026, 2, 1), date(2026, 4, 30)), [date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30)])

    def test_yearly_on_29_february(self):
        e = self.ev(date=date(2024, 2, 29), repeat=Repeat.YEARLY)
        self.assertEqual(self.dates(e, date(2025, 1, 1), date(2028, 12, 31)), [date(2025, 2, 28), date(2026, 2, 28), date(2027, 2, 28), date(2028, 2, 29)])

    def test_every_year_on_a_bangla_date(self):
        e = self.ev(date=date(2024, 4, 14), repeat=Repeat.BN_YEARLY)     # 1 Boishakh
        self.assertEqual(self.dates(e, date(2026, 1, 1), date(2027, 12, 31)), [date(2026, 4, 14), date(2027, 4, 14)])

    def test_every_bangla_month(self):
        e = self.ev(date=date(2026, 4, 14), repeat=Repeat.BN_MONTHLY)     # the 1st of each Bangla month
        got = self.dates(e, date(2026, 9, 1), date(2026, 11, 30))
        self.assertEqual(got, [date(2026, 9, 16), date(2026, 10, 17), date(2026, 11, 16)])
        self.assertTrue(all(bn.to_bangla(d).day == 1 for d in got))

    def test_repeat_until_stops_it(self):
        e = self.ev(date=date(2026, 9, 1), repeat=Repeat.WEEKLY, repeat_until=date(2026, 9, 15))
        self.assertEqual(self.dates(e, date(2026, 9, 1), date(2026, 9, 30)), [date(2026, 9, 1), date(2026, 9, 8), date(2026, 9, 15)])

    def test_nothing_before_the_first_date(self):
        e = self.ev(date=date(2026, 9, 20), repeat=Repeat.MONTHLY)
        self.assertEqual(self.dates(e, date(2026, 8, 1), date(2026, 9, 10)), [])


class CalendarBase(TestCase):
    def setUp(self):
        self.b, self.owner, self.staff = make_farm()
        self.client.force_login(self.owner)
        self.today = date.today()
        self.pond = Pond.objects.create(business=self.b, name="East")
        self.cycle = CultureCycle.objects.create(business=self.b, pond=self.pond, start_date=self.today - timedelta(days=40))
        self.rui = Species.objects.get(business=self.b, name="Rui")
        self.kg = Unit.objects.get(business=self.b, symbol="kg")

    def event(self, **kw):
        kw.setdefault("date", self.today)
        kw.setdefault("title", "Lime the pond")
        return CalendarEvent.objects.create(business=self.b, **kw)


class CollectTests(CalendarBase):
    def kinds(self, money=True):
        return {i.kind for i in collect(self.b, self.today - timedelta(days=5), self.today + timedelta(days=5), money=money)}

    def test_farm_records_show_up(self):
        Stocking.objects.create(business=self.b, cycle=self.cycle, date=self.today, species=self.rui, count=100)
        sale = FishSale.objects.create(business=self.b, date=self.today)
        FishSaleLine.objects.create(business=self.b, sale=sale, species=self.rui, quantity=D("10"), unit=self.kg, rate=D("300"))
        sale.recalc()
        self.event()
        self.assertTrue({"pond", "sale", "mine"} <= self.kinds())

    def test_bad_water_is_red(self):
        WaterTest.objects.create(business=self.b, cycle=self.cycle, date=self.today, oxygen=D("2"))
        item = next(i for i in collect(self.b, self.today, self.today) if i.kind == "pond")
        self.assertEqual(item.tone, "critical")

    def test_money_matters_only_for_people_who_may_see_money(self):
        Party.objects.create(business=self.b, name="Hasan", is_buyer=True, follow_up_on=self.today)
        self.assertIn("due", self.kinds(money=True))
        self.assertNotIn("due", self.kinds(money=False))

    def test_sale_amounts_hidden_without_money(self):
        sale = FishSale.objects.create(business=self.b, date=self.today)
        FishSaleLine.objects.create(business=self.b, sale=sale, species=self.rui, quantity=D("10"), unit=self.kg, rate=D("300"))
        sale.recalc()
        item = next(i for i in collect(self.b, self.today, self.today, money=False) if i.kind == "sale")
        self.assertEqual(item.detail, "")

    def test_national_days(self):
        names = [i.title for i in holiday_items(date(2026, 1, 1), date(2026, 12, 31))]
        self.assertEqual(len(names), 8)
        self.assertIn("Victory Day", names)

    def test_deleted_events_are_gone(self):
        e = self.event()
        e.soft_delete()
        self.assertNotIn("mine", self.kinds())

    def test_other_farms_stay_out(self):
        other, _o, _s = make_farm(owner_name="other")
        self.event()
        self.assertEqual([i for i in collect(other, self.today, self.today) if i.kind != "holiday"], [])


class CalendarPageTests(CalendarBase):
    def test_month_both_calendars_agenda_and_year(self):
        self.event(time=time(7, 30))
        for q in ("?cal=en", "?cal=bn", "?view=agenda", "?view=year", "?view=year&cal=bn", "?cal=bn&y=1433&m=11", "?week=mon"):
            r = self.client.get(reverse("business:calendar") + q)
            self.assertEqual(r.status_code, 200, q)
        self.assertContains(self.client.get(reverse("business:calendar") + "?view=month"), "Lime the pond")

    def test_bangla_month_covers_its_own_days(self):
        r = self.client.get(reverse("business:calendar") + "?cal=bn&view=month&y=1433&m=11")    # Falgun 1433
        cells = [c for row in r.context["weeks"] for c in row if c["in_month"]]
        self.assertEqual((cells[0]["date"], cells[-1]["date"]), (date(2027, 2, 14), date(2027, 3, 14)))

    def test_bad_input_falls_back_quietly(self):
        r = self.client.get(reverse("business:calendar") + "?cal=xx&view=zz&y=abc&m=40&day=2026-99-01&week=fri")
        self.assertEqual(r.status_code, 200)

    def test_choices_are_remembered(self):
        self.client.get(reverse("business:calendar") + "?cal=bn&view=agenda&week=sun")
        r = self.client.get(reverse("business:calendar"))
        self.assertEqual((r.context["cal"], r.context["view"], r.context["week"]), ("bn", "agenda", "sun"))

    def test_bangla_page_uses_bangla_digits(self):
        with translation.override("bn"):
            r = self.client.get(reverse("business:calendar") + "?cal=bn", headers={"accept-language": "bn"})
        self.assertTrue(any(ch in r.context["title"] for ch in "০১২৩৪৫৬৭৮৯"))

    def test_staff_do_not_see_money_filters(self):
        self.client.force_login(self.staff)
        r = self.client.get(reverse("business:calendar"))
        self.assertNotIn("due", [f["key"] for f in r.context["filters"]])


class EventTests(CalendarBase):
    def test_add_from_the_calendar(self):
        r = self.client.post(reverse("business:calendar_add"), {"title": "Pay lease", "date": self.today.isoformat(), "category": "money",
                                                                "repeat": "monthly", "next": "/business/calendar/?day=" + self.today.isoformat()})
        self.assertRedirects(r, "/business/calendar/?day=" + self.today.isoformat(), fetch_redirect_response=False)
        e = CalendarEvent.objects.get()
        self.assertEqual((e.title, e.repeat, e.business), ("Pay lease", "monthly", self.b))

    def test_outside_next_links_are_ignored(self):
        r = self.client.post(reverse("business:calendar_add"), {"title": "x", "date": self.today.isoformat(), "category": "work", "next": "https://evil.example/"})
        self.assertTrue(r["Location"].startswith("/business/calendar/"))

    def test_end_before_start_is_refused(self):
        self.client.post(reverse("business:calendar_add"), {"title": "x", "date": self.today.isoformat(), "category": "work",
                                                            "end_date": (self.today - timedelta(days=1)).isoformat()})
        self.assertFalse(CalendarEvent.objects.exists())

    def test_repeating_events_are_one_day_long(self):
        self.client.post(reverse("business:calendar_add"), {"title": "x", "date": self.today.isoformat(), "category": "work", "repeat": "weekly",
                                                            "end_date": (self.today + timedelta(days=2)).isoformat()})
        self.assertFalse(CalendarEvent.objects.exists())

    def test_tick_a_to_do(self):
        e = self.event(category="task")
        r = self.client.post(reverse("business:calendar_done", args=[e.pk]), headers={"x-requested-with": "fetch"})
        self.assertEqual(r.json(), {"done": True})
        e.refresh_from_db()
        self.assertTrue(e.done)

    def test_edit_and_remove(self):
        e = self.event()
        r = self.client.post(reverse("business:calendar_edit", args=[e.pk]), {"title": "Lime both ponds", "date": self.today.isoformat(), "category": "work"})
        self.assertEqual(r.status_code, 302)
        e.refresh_from_db()
        self.assertEqual(e.title, "Lime both ponds")
        self.client.post(reverse("business:calendar_delete", args=[e.pk]))
        self.assertFalse(CalendarEvent.objects.filter(pk=e.pk).exists())

    def test_data_entry_staff_can_add_but_not_remove(self):
        e = self.event()
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse("business:calendar_add")).status_code, 200)
        self.assertNotEqual(self.client.post(reverse("business:calendar_delete", args=[e.pk])).status_code, 302)
        self.assertTrue(CalendarEvent.objects.filter(pk=e.pk).exists())

    def test_another_farm_cannot_touch_it(self):
        e = self.event()
        _other, owner, _s = make_farm(owner_name="other")
        self.client.force_login(owner)
        self.assertEqual(self.client.get(reverse("business:calendar_edit", args=[e.pk])).status_code, 404)

    def test_todo_waits_on_the_home_page_until_done(self):
        e = self.event(category="task", date=self.today - timedelta(days=3), title="Fix the net")
        self.assertEqual([i.title for i in todays_events(self.b)], ["Fix the net"])
        self.assertContains(self.client.get(reverse("business:home")), "Fix the net")
        e.done = True
        e.save()
        self.assertEqual(todays_events(self.b), [])

    def test_calendar_file(self):
        self.event(title="Lime, then wait; check", time=time(6, 0))
        r = self.client.get(reverse("business:calendar_ics"))
        text = r.content.decode()
        self.assertEqual(r["Content-Type"], "text/calendar; charset=utf-8")
        self.assertTrue(text.startswith("BEGIN:VCALENDAR\r\n"))
        self.assertIn("SUMMARY:Lime\\, then wait\\; check", text)
        self.assertIn(f"DTSTART:{self.today:%Y%m%d}T060000", text)
        self.assertTrue(all(len(line.encode()) <= 75 for line in text.split("\r\n")))
