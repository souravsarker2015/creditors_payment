"""Advances (dadon): a buyer pays before the harvest; the fish sold to them pays it back."""
from datetime import date, timedelta
from decimal import Decimal as D
from urllib.parse import unquote

from django.test import TestCase
from django.urls import reverse

from apps.business.core.models import Unit
from apps.business.core.testing import make_farm
from apps.business.finance.models import Account
from apps.business.parties.models import Party
from apps.business.ponds.models import CultureCycle, Pond, Stocking
from apps.business.sales.models import FishSale, FishSaleLine
from apps.business.species.models import Species

from . import services
from .models import Direction, PartyPayment

TODAY = date.today()


class AdvanceTests(TestCase):
    def setUp(self):
        self.b, self.owner, self.staff = make_farm()
        self.client.force_login(self.owner)
        self.kg = Unit.objects.get(business=self.b, symbol="kg")
        self.rui = Species.objects.get(business=self.b, name="Rui")
        self.karim = Party.objects.create(business=self.b, name="Karim Paikar", phone="01711223344", is_buyer=True)
        self.cycle = CultureCycle.objects.create(business=self.b, pond=Pond.objects.create(business=self.b, name="Boro Pukur"), start_date=TODAY - timedelta(days=90))
        Stocking.objects.create(business=self.b, cycle=self.cycle, date=TODAY - timedelta(days=90), species=self.rui, count=1000)
        self.cash = Account.objects.get(business=self.b, name="Cash")

    def take(self, amount="100000", days_ago=10, **extra):
        data = {"party": self.karim.pk, "amount": amount, "date": (TODAY - timedelta(days=days_ago)).isoformat(), "account": self.cash.pk,
                "advance_cycle": self.cycle.pk, "agreed_rate": "250", "expected_kg": "400", "expected_on": (TODAY + timedelta(days=5)).isoformat()}
        data.update(extra)
        return self.client.post(reverse("business:advance_add"), data, follow=True)

    def sell(self, kg, rate="250", received="0"):
        sale = FishSale.objects.create(business=self.b, date=TODAY, buyer=self.karim, cycle=self.cycle, received_now=D(received))
        FishSaleLine.objects.create(business=self.b, sale=sale, species=self.rui, quantity=D(kg), unit=self.kg, rate=D(rate))
        sale.recalc()
        return sale

    def test_taking_an_advance(self):
        r = self.take()
        self.assertContains(r, "Advance of ৳1,00,000 from Karim Paikar saved")
        p = PartyPayment.objects.get()
        self.assertTrue(p.is_advance)
        self.assertEqual(p.direction, Direction.IN)
        led = services.ledger(self.karim)
        self.assertEqual(led.balance, D("-100000"))                     # we owe them fish
        self.assertEqual(led.entries[0].title, "Advance (dadon) received")
        self.assertIn("for the fish of Boro Pukur", led.entries[0].detail)
        self.assertEqual(led.entries[0].url, reverse("business:advance_edit", args=[p.pk]))

    def test_fish_sold_pays_it_back(self):
        self.take()
        sale = self.sell("240")                                          # ৳60,000 of fish
        a = services.advances(self.b)[0]
        self.assertEqual(a.open, D("40000"))
        self.assertEqual(a.settled_pct, 60)
        self.assertEqual(a.kg_left, D("160"))
        self.assertEqual(services.ledger(self.karim).due_on(("sale", sale.pk)), 0)   # nothing due on the sale
        self.sell("200")                                                 # ৳50,000 more: paid back, ৳10,000 now owed to us
        self.assertEqual(services.advances(self.b), [])
        self.assertEqual(services.ledger(self.karim).balance, D("10000"))

    def test_a_buyer_who_owes_you_settles_that_first(self):
        self.sell("100")                                                 # they owe ৳25,000
        r = self.take("40000")
        self.assertContains(r, "Karim Paikar owed you ৳25,000, so this settles that first. ৳15,000 is left as an advance")
        self.assertEqual(services.advances(self.b)[0].open, D("15000"))
        r = self.take("5000")
        self.assertEqual(sum(a.open for a in services.advances(self.b)), D("20000"))

    def test_all_of_it_to_old_dues(self):
        self.sell("400")                                                 # they owe ৳1,00,000
        r = self.take("30000")
        self.assertContains(r, "Nothing is left as an advance; they still owe ৳70,000")
        self.assertEqual(services.advances(self.b), [])

    def test_oldest_advance_paid_back_first(self):
        self.take("50000", days_ago=20)
        self.take("30000", days_ago=5)
        self.sell("200")                                                 # ৳50,000
        open_ = services.advances(self.b)
        self.assertEqual([(a.amount, a.open) for a in open_], [(D("30000"), D("30000"))])

    def test_shown_in_baki_on_the_pond_and_today(self):
        self.take()
        r = self.client.get(reverse("business:dues"))
        self.assertContains(r, "Advances (dadon) to pay back in fish")
        self.assertContains(r, reverse("business:sale_add") + "?advance=")
        r = self.client.get(reverse("business:cycle_detail", args=[self.cycle.pk]))
        self.assertContains(r, "Fish promised from this pond")
        self.assertContains(r, "৳1,00,000 advance (dadon) to pay back")
        r = self.client.get(reverse("business:home"))
        self.assertContains(r, "Fish promised to Karim Paikar")
        self.client.force_login(self.staff)                             # data entry: no money
        r = self.client.get(reverse("business:cycle_detail", args=[self.cycle.pk]))
        self.assertContains(r, "Fish promised from this pond")
        self.assertNotContains(r, "৳1,00,000 advance")

    def test_not_due_soon_is_not_a_task(self):
        self.take(expected_on=(TODAY + timedelta(days=30)).isoformat())
        self.assertNotContains(self.client.get(reverse("business:home")), "Fish promised to Karim Paikar")

    def test_sell_starts_from_the_advance(self):
        self.take()
        self.sell("240")
        p = PartyPayment.objects.get()
        r = self.client.get(reverse("business:sale_add") + f"?advance={p.pk}")
        form = r.context["form"]
        self.assertEqual(form.initial["buyer"], self.karim.pk)
        self.assertEqual(form.initial["cycle"], self.cycle.pk)
        line = r.context["lines"].initial_extra[0]
        self.assertEqual(line["rate"], "250")
        self.assertEqual(line["quantity"], "160")                        # what's still owed
        self.assertIn("They have ৳40,000 of advance (dadon) with you", r.context["buyer_advances"][str(self.karim.pk)])
        self.assertContains(r, 'id="buyer-advances"')

    def test_editing_goes_to_the_advance_form(self):
        self.take()
        p = PartyPayment.objects.get()
        r = self.client.get(reverse("business:payment_edit", args=[p.pk]))
        self.assertRedirects(r, reverse("business:advance_edit", args=[p.pk]))
        r = self.client.get(reverse("business:advance_edit", args=[p.pk]))
        self.assertContains(r, "still to be paid back in fish")
        self.client.post(reverse("business:advance_edit", args=[p.pk]), {"party": self.karim.pk, "amount": "120000", "date": p.date.isoformat()})
        p.refresh_from_db()
        self.assertEqual(p.amount, D("120000"))
        self.assertTrue(p.is_advance)

    def test_memo_says_what_is_left(self):
        self.take()
        sale = self.sell("240")
        wa = self.client.get(reverse("business:sale_detail", args=[sale.pk])).context["wa"]
        self.assertIn("Your advance (dadon) left with us: ৳40,000", unquote(wa))

    def test_checks(self):
        r = self.take(amount="")
        self.assertContains(r, "Enter the amount")
        r = self.take(expected_on=(TODAY - timedelta(days=30)).isoformat())
        self.assertContains(r, "can&#x27;t be before the advance")
        self.assertFalse(PartyPayment.objects.exists())

    def test_other_farms_cannot_see_it(self):
        self.take()
        other, other_owner, _ = make_farm("other")
        self.client.force_login(other_owner)
        p = PartyPayment.objects.get()
        self.assertEqual(self.client.get(reverse("business:advance_edit", args=[p.pk])).status_code, 404)
        self.assertEqual(services.advances(other), [])
