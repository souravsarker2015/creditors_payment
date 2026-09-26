"""Phase 4: the baki ledger, payments, statements and the due list."""
from datetime import date, timedelta
from decimal import Decimal as D

from django.test import TestCase
from django.urls import reverse

from apps.business.core.models import Role, Unit
from apps.business.core.testing import make_farm
from apps.business.feed.models import FeedPurchase
from apps.business.markets.models import Market
from apps.business.parties.models import OpeningType, Party
from apps.business.ponds.models import CultureCycle, Pond, Stocking
from apps.business.sales.models import FishSale
from apps.business.species.models import Species

from . import services
from .models import Direction, PartyPayment


def ago(n):
    return date.today() - timedelta(days=n)


class BakiBase(TestCase):
    def setUp(self):
        self.b, self.owner, self.staff = make_farm()
        self.client.force_login(self.owner)
        self.buyer = Party.objects.create(business=self.b, name="Hasan Aratdar", is_buyer=True, phone="01712-345678")
        self.supplier = Party.objects.create(business=self.b, name="Mollah Feed", is_supplier=True)

    def sale(self, net, received=0, days=0, buyer=None):
        return FishSale.objects.create(business=self.b, date=ago(days), buyer=buyer or self.buyer, gross=net, net=net, received_now=received)

    def feed(self, total, paid=0, days=0):
        return FeedPurchase.objects.create(business=self.b, date=ago(days), supplier=self.supplier, subtotal=total, total=total, paid_now=paid)

    def pay(self, party, amount, direction=Direction.IN, days=0, **kw):
        return PartyPayment.objects.create(business=self.b, party=party, direction=direction, date=ago(days), amount=amount, **kw)

    def led(self, party):
        return services.ledger(party)


class LedgerTests(BakiBase):
    def test_sale_on_baki_makes_the_buyer_owe(self):
        self.sale(10000, received=4000)
        led = self.led(self.buyer)
        self.assertEqual(led.balance, D("6000"))
        self.assertTrue(led.owes_me)

    def test_feed_on_baki_makes_me_owe_the_supplier(self):
        self.feed(25000, paid=5000)
        self.assertEqual(self.led(self.supplier).balance, D("-20000"))

    def test_opening_balances_count_both_ways(self):
        a = Party.objects.create(business=self.b, name="A", is_buyer=True, opening_balance=3000, opening_type=OpeningType.RECEIVABLE)
        z = Party.objects.create(business=self.b, name="Z", is_supplier=True, opening_balance=7000, opening_type=OpeningType.PAYABLE)
        self.assertEqual((self.led(a).balance, self.led(z).balance), (D("3000"), D("-7000")))

    def test_payments_and_discount_settle_the_balance(self):
        self.sale(10050, days=5)
        self.pay(self.buyer, 10000, discount=50)
        led = self.led(self.buyer)
        self.assertEqual(led.balance, 0)
        self.assertEqual(led.open_items, [])

    def test_payments_settle_the_oldest_bill_first(self):
        old = self.sale(5000, days=70)
        new = self.sale(8000, days=10)
        self.pay(self.buyer, 6000)
        led = self.led(self.buyer)
        self.assertEqual(led.due_on(("sale", old.pk)), 0)
        self.assertEqual(led.due_on(("sale", new.pk)), D("7000"))

    def test_a_payment_for_a_particular_sale_settles_that_one(self):
        old = self.sale(5000, days=70)
        new = self.sale(8000, days=10)
        self.pay(self.buyer, 6000, sale=new)
        led = self.led(self.buyer)
        self.assertEqual(led.due_on(("sale", new.pk)), D("2000"))
        self.assertEqual(led.due_on(("sale", old.pk)), D("5000"))

    def test_extra_on_a_linked_payment_goes_to_the_oldest_bill(self):
        old = self.sale(5000, days=70)
        new = self.sale(3000, days=10)
        self.pay(self.buyer, 4000, sale=new)
        led = self.led(self.buyer)
        self.assertEqual((led.due_on(("sale", new.pk)), led.due_on(("sale", old.pk))), (0, D("4000")))

    def test_ageing_buckets(self):
        self.sale(1000, days=5)
        self.sale(2000, days=45)
        self.sale(3000, days=75)
        self.sale(4000, days=120)
        led = self.led(self.buyer)
        self.assertEqual(led.buckets, [D("1000"), D("2000"), D("3000"), D("4000")])
        self.assertEqual(led.oldest_days, 120)
        self.assertEqual(sum(led.buckets), led.balance)

    def test_someone_who_is_both_buyer_and_supplier_nets_out(self):
        self.supplier.is_buyer = True
        self.supplier.save()
        self.feed(20000, days=30)
        self.sale(12000, days=3, buyer=self.supplier)
        led = self.led(self.supplier)
        self.assertEqual(led.balance, D("-8000"))
        self.assertEqual(sum(led.buckets), D("8000"))

    def test_stocking_on_baki_counts_for_the_hatchery(self):
        pond = Pond.objects.create(business=self.b, name="East")
        cycle = CultureCycle.objects.create(business=self.b, pond=pond, start_date=ago(10))
        rui = Species.objects.get(business=self.b, name="Rui")
        Stocking.objects.create(business=self.b, cycle=cycle, date=ago(10), species=rui, count=1000, supplier=self.supplier, cost=15000, paid_now=5000)
        self.assertEqual(self.led(self.supplier).balance, D("-10000"))

    def test_deleted_records_drop_out(self):
        s = self.sale(9000)
        p = self.pay(self.buyer, 4000)
        p.soft_delete()
        self.assertEqual(self.led(self.buyer).balance, D("9000"))
        s.soft_delete()
        self.assertEqual(self.led(self.buyer).balance, 0)

    def test_running_balance_on_each_row(self):
        self.sale(10000, days=3)
        self.pay(self.buyer, 4000, days=2)
        self.sale(2000, received=2000, days=1)
        self.assertEqual([e.balance for e in self.led(self.buyer).entries], [D("10000"), D("6000"), D("6000")])

    def test_totals_across_the_farm(self):
        self.sale(10000)
        self.feed(3000)
        t = services.totals(self.b)
        self.assertEqual((t["receivable"], t["payable"], t["receivable_count"], t["payable_count"]), (D("10000"), D("3000"), 1, 1))

    def test_whatsapp_number(self):
        self.assertEqual(services.whatsapp_number("01712-345678"), "8801712345678")
        self.assertEqual(services.whatsapp_number("+880 1712 345678"), "8801712345678")
        self.assertEqual(services.whatsapp_number("123"), "")


class PaymentPageTests(BakiBase):
    def post(self, **data):
        base = {"party": self.buyer.pk, "direction": "in", "date": date.today().isoformat(), "amount": "", "discount": "", "against": ""}
        return self.client.post(reverse("business:payment_add"), {**base, **data})

    def test_record_a_payment_and_land_on_the_statement(self):
        self.sale(10000, days=3)
        r = self.post(amount="4000")
        self.assertRedirects(r, reverse("business:party_statement", args=[self.buyer.pk]))
        self.assertEqual(self.led(self.buyer).balance, D("6000"))

    def test_link_a_payment_to_a_sale(self):
        s = self.sale(10000, days=3)
        self.post(amount="10000", against=f"sale:{s.pk}")
        self.assertEqual(PartyPayment.objects.get().sale, s)

    def test_cannot_link_someone_elses_bill(self):
        other = Party.objects.create(business=self.b, name="Other", is_buyer=True)
        s = self.sale(10000, buyer=other)
        r = self.post(amount="100", against=f"sale:{s.pk}")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(PartyPayment.objects.exists())

    def test_needs_an_amount_and_no_future_date(self):
        self.assertEqual(self.post(amount="").status_code, 200)
        self.assertEqual(self.post(amount="10", date=(date.today() + timedelta(days=2)).isoformat()).status_code, 200)
        self.assertFalse(PartyPayment.objects.exists())

    def test_settling_in_full_clears_the_follow_up(self):
        self.sale(3000)
        self.buyer.follow_up_on = date.today()
        self.buyer.save()
        self.post(amount="3000")
        self.buyer.refresh_from_db()
        self.assertIsNone(self.buyer.follow_up_on)

    def test_discount_only_is_allowed(self):
        self.sale(50)
        self.post(discount="50")
        self.assertEqual(self.led(self.buyer).balance, 0)

    def test_form_prefills_from_the_link(self):
        s = self.sale(10000)
        r = self.client.get(reverse("business:payment_add") + f"?party={self.buyer.pk}&dir=in&against=sale:{s.pk}")
        self.assertEqual(r.context["form"]["against"].value(), f"sale:{s.pk}")
        self.assertContains(r, "owes you")

    def test_data_entry_staff_can_record_but_not_see_the_due_list(self):
        self.client.force_login(self.staff)
        self.sale(1000)
        r = self.post(amount="1000")
        self.assertRedirects(r, reverse("business:payment_add"))
        self.assertEqual(self.client.get(reverse("business:dues")).status_code, 403)

    def test_delete_and_restore(self):
        self.sale(1000)
        p = self.pay(self.buyer, 1000)
        self.client.post(reverse("business:payment_delete", args=[p.pk]))
        self.assertEqual(self.led(self.buyer).balance, D("1000"))
        self.client.post(reverse("business:payment_restore", args=[p.pk]))
        self.assertEqual(self.led(self.buyer).balance, 0)

    def test_other_farms_cannot_touch_payments(self):
        b2, owner2, _s = make_farm("other")
        p = self.pay(self.buyer, 100)
        self.client.force_login(owner2)
        self.assertEqual(self.client.get(reverse("business:payment_edit", args=[p.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("business:party_statement", args=[self.buyer.pk])).status_code, 404)


class PagesTests(BakiBase):
    def test_due_list_shows_both_sides(self):
        self.sale(10000, days=40)
        self.feed(3000)
        r = self.client.get(reverse("business:dues"))
        self.assertContains(r, "Hasan Aratdar")
        self.assertContains(r, "wa.me/8801712345678")
        r = self.client.get(reverse("business:dues") + "?side=pay")
        self.assertContains(r, "Mollah Feed")
        self.assertNotContains(r, "Hasan Aratdar")

    def test_follow_up_shows_on_the_due_list(self):
        self.sale(500)
        self.client.post(reverse("business:party_follow_up", args=[self.buyer.pk]), {"follow_up_on": date.today().isoformat(), "follow_up_note": "After Friday"})
        self.assertContains(self.client.get(reverse("business:dues")), "After Friday")
        self.client.post(reverse("business:party_follow_up", args=[self.buyer.pk]), {"clear": "1"})
        self.buyer.refresh_from_db()
        self.assertIsNone(self.buyer.follow_up_on)

    def test_statement_brings_balance_forward(self):
        self.sale(10000, days=60)
        self.pay(self.buyer, 3000, days=5)
        r = self.client.get(reverse("business:party_statement", args=[self.buyer.pk]) + f"?from={ago(10).isoformat()}")
        self.assertEqual(r.context["brought"], D("10000"))
        self.assertEqual(r.context["closing"], D("7000"))
        self.assertEqual(len(r.context["rows"]), 1)

    def test_sale_page_counts_later_payments(self):
        s = self.sale(10000, received=2000)
        self.pay(self.buyer, 5000, sale=s)
        r = self.client.get(reverse("business:sale_detail", args=[s.pk]))
        self.assertEqual(r.context["due_now"], D("3000"))
        self.assertContains(r, "Receive payment")

    def test_sales_list_due_filter_uses_later_payments(self):
        paid = self.sale(1000, days=2)
        due = self.sale(2000, days=1)
        self.pay(self.buyer, 1000)
        r = self.client.get(reverse("business:sales") + "?period=all&due=1")
        self.assertEqual([s.pk for s in r.context["page_obj"]], [due.pk])
        self.assertEqual(r.context["due_total"], D("2000"))
        self.assertNotEqual(paid.pk, due.pk)

    def test_party_list_shows_live_balance_and_blocks_delete(self):
        self.sale(4500)
        r = self.client.get(reverse("business:buyers"))
        self.assertContains(r, "4,500")
        self.client.post(reverse("business:buyers_delete", args=[self.buyer.pk]))
        self.buyer.refresh_from_db()
        self.assertFalse(self.buyer.is_deleted)

    def test_home_shows_the_baki_card(self):
        self.sale(7000, days=100)
        r = self.client.get(reverse("business:home"))
        self.assertEqual(r.context["baki"]["receivable"], D("7000"))


class SaleNeedsBuyerForDueTests(TestCase):
    def setUp(self):
        self.b, self.owner, _staff = make_farm()
        self.client.force_login(self.owner)
        self.kg = Unit.objects.get(business=self.b, symbol="kg")
        self.rui = Species.objects.get(business=self.b, name="Rui")
        self.market = Market.objects.create(business=self.b, name="Mesua")

    def sell(self, **extra):
        data = {"date": ago(1).isoformat(), "market": self.market.pk, "buyer": "", "lines-TOTAL_FORMS": "1", "lines-INITIAL_FORMS": "0",
                "lines-0-species": self.rui.pk, "lines-0-quantity": "10", "lines-0-unit": self.kg.pk, "lines-0-rate": "200",
                "deds-TOTAL_FORMS": "0", "deds-INITIAL_FORMS": "0", **extra}
        return self.client.post(reverse("business:sale_add"), data)

    def test_cash_sale_without_buyer_is_fine(self):
        self.assertEqual(self.sell(received_now="2000").status_code, 302)

    def test_baki_sale_needs_a_buyer(self):
        r = self.sell(received_now="500")
        self.assertEqual(r.status_code, 200)
        self.assertIn("buyer", r.context["form"].errors)
        self.assertFalse(FishSale.objects.exists())


class DataEntryRoleTests(TestCase):
    def test_viewer_cannot_record_payments(self):
        b, owner, viewer = make_farm(staff_role=Role.VIEWER)
        self.client.force_login(viewer)
        self.assertEqual(self.client.get(reverse("business:payment_add")).status_code, 403)
