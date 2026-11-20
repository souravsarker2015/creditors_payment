"""Credit cards: bills and due dates worked out from what was recorded, money
taken to bKash/Nagad and paid back through them (with each fee), EMIs, and
how the rest of the app sees it (wallet balances, Home, Upcoming, the report)."""
from datetime import date, timedelta
from decimal import Decimal as D

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.wallets import services as wallets
from apps.wallets.models import Wallet

from .. import services as sv
from ..models import Card, CardBank, CardEntry, CardNetwork, EmiPlan, MfsFees

PW = "Str0ng-pass-123"


class Base(TestCase):
    def setUp(self):
        self.me = User.objects.create_user("me", "me@example.com", PW)
        self.client.force_login(self.me)
        self.ucb = CardBank.objects.create(user=self.me, name="UCB")
        self.card = Card.objects.create(user=self.me, name="UCB Visa", bank=self.ucb, statement_day=5, due_day=25,
                                        transfer_fee_rate=D("1.5"), interest_rate=D("24"), limit=D("100000"),
                                        opening_date=date(2026, 1, 1))
        self.bkash = Wallet.objects.create(user=self.me, name="bKash", kind="mobile", opening_date=date(2026, 1, 1))
        self.nagad = Wallet.objects.create(user=self.me, name="Nagad", kind="mobile", opening_date=date(2026, 1, 1))
        MfsFees.objects.create(wallet=self.nagad, bill_rate=D("1"), bank_rate=D("1.5"))
        MfsFees.objects.create(wallet=self.bkash, bill_rate=D("0"), pays_bills=False, bank_rate=D("1.2"))

    def entry(self, kind, amount, day, **kw):
        return CardEntry.objects.create(card=self.card, kind=kind, amount=D(amount), date=day, **kw)


class BillDayTests(Base):
    def test_bill_and_pay_by_dates(self):
        c = self.card
        self.assertEqual(sv.bill_for(c, date(2026, 1, 5)), date(2026, 1, 5))       # on the bill day: that bill
        self.assertEqual(sv.bill_for(c, date(2026, 1, 6)), date(2026, 2, 5))
        self.assertEqual(sv.due_for(c, date(2026, 2, 5)), date(2026, 2, 25))       # pay-by after the bill day: same month
        c.statement_day, c.due_day = 20, 10
        self.assertEqual(sv.due_for(c, date(2026, 12, 20)), date(2027, 1, 10))     # before it: next month
        c.statement_day = 31
        self.assertEqual(sv.bill_for(c, date(2026, 2, 10)), date(2026, 2, 28))     # a short month: its last day
        self.assertEqual(sv.bill_after(c, date(2026, 2, 28)), date(2026, 3, 31))


class BillTests(Base):
    def test_taken_to_bkash_then_paid_in_full_from_nagad(self):
        self.entry("cash", "10000", date(2026, 1, 10), wallet=self.bkash, fee_rate=D("1.5"), fee=D("150"))
        self.entry("pay", "10150", date(2026, 2, 20), wallet=self.nagad, route="mfs_bill", fee_rate=D("1"), fee=D("101.50"))
        self.entry("spend", "5000", date(2026, 3, 1), note="Shoes")
        st = sv.card_state(self.card, date(2026, 3, 10))
        feb, mar = st.bills
        self.assertEqual((feb.date, feb.due, feb.closing, feb.min_due, feb.status), (date(2026, 2, 5), date(2026, 2, 25), D("10150"), D("507.50"), sv.PAID))
        self.assertEqual((mar.closing, mar.status, mar.left, mar.days), (D("5000"), sv.OPEN, D("5000"), 15))
        self.assertEqual(st.owed, D("5000"))
        self.assertEqual(st.available, D("95000"))
        self.assertEqual((st.costs.card_fee, st.costs.wallet_fee, st.costs.total), (D("150"), D("101.50"), D("251.50")))
        self.assertEqual(st.to_pay, mar)
        # the money moved the wallets: bKash got 10,000; Nagad paid 10,150 + 101.50
        held = wallets.balances(self.me)
        self.assertEqual((held[self.bkash.pk], held[self.nagad.pk]), (D("10000"), D("-10251.50")))

    def test_partly_paid_and_not_paid(self):
        self.entry("spend", "20000", date(2026, 1, 10))
        self.entry("pay", "2000", date(2026, 2, 24))
        st = sv.card_state(self.card, date(2026, 3, 1))
        b = st.bill
        self.assertEqual((b.status, b.left, b.min_due), (sv.PARTIAL, D("18000"), D("1000")))
        self.assertEqual(b.interest, D("360.00"))                                  # 24% a year on 18,000, a month
        CardEntry.objects.all().filter(kind="pay").update(amount=D("300"))
        self.assertEqual(sv.card_state(self.card, date(2026, 3, 1)).bill.status, sv.MISSED)
        CardEntry.objects.filter(kind="pay").update(amount=D("20000"), date=date(2026, 2, 28))
        self.assertEqual(sv.card_state(self.card, date(2026, 3, 1)).bill.status, sv.LATE)

    def test_whats_left_carries_to_the_next_bill(self):
        self.entry("spend", "1000", date(2026, 1, 10))
        self.entry("spend", "500", date(2026, 2, 10))
        st = sv.card_state(self.card, date(2026, 3, 6))
        self.assertEqual([(b.opening, b.charges, b.closing) for b in st.bills], [(D(0), D("1000"), D("1000")), (D("1000"), D("500"), D("1500"))])

    def test_opening_balance_and_correction(self):
        self.card.opening_balance = D("3000")
        self.card.save()
        r = self.client.post(reverse("card_correct", args=[self.card.pk]), {"actual": "3250", "note": "bank app"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(sv.card_state(self.card, timezone.localdate()).owed, D("3250"))


class EmiTests(Base):
    def test_zero_percent_emi_one_installment_on_each_bill(self):
        self.entry("spend", "12000", date(2026, 2, 1), note="Laptop")
        EmiPlan.objects.create(card=self.card, title="Laptop", amount=D("12000"), months=3, start=date(2026, 2, 6), fee=D("120"))
        st = sv.card_state(self.card, date(2026, 4, 6))
        feb, mar, apr = st.bills
        self.assertEqual(feb.closing, D("12000"))
        self.assertEqual(feb.status, sv.PAID)               # turned into EMI before the due date: nothing left to pay on it
        self.assertEqual(mar.closing, D("4120"))            # 12,000 − 12,000 + the first 4,000 + the 120 fee
        self.assertEqual(st.owed, D("12120"))               # nothing paid yet: the whole amount is still owed
        self.assertEqual(st.emis[0].left, D("4000"))
        self.assertEqual(st.emis[0].next.date, date(2026, 5, 5))

    def test_with_interest_and_paid_off_early(self):
        p = EmiPlan.objects.create(card=self.card, title="Phone", amount=D("60000"), months=12, rate=D("12"), start=date(2026, 1, 10))
        rows = sv.schedule(p)
        self.assertEqual(sv.emi_amount(D("60000"), 12, D("12")), D("5330.93"))
        self.assertEqual(sum(r.principal for r in rows), D("60000"))
        self.assertEqual(rows[0].interest, D("600.00"))
        p.closed_on = date(2026, 3, 10)
        p.save()
        st = sv.emi_state(p, date(2026, 4, 1))
        self.assertTrue(st.done)
        self.assertEqual(st.count, 2)


class PagesTests(Base):
    def test_every_page_opens(self):
        self.entry("cash", "5000", timezone.localdate() - timedelta(days=3), wallet=self.bkash, fee=D("75"))
        EmiPlan.objects.create(card=self.card, title="TV", amount=D("30000"), months=6, start=timezone.localdate() - timedelta(days=40))
        for url in (reverse("card_dashboard"), reverse("card_detail", args=[self.card.pk]), reverse("card_create"),
                    reverse("card_edit", args=[self.card.pk]), reverse("card_entry_add", args=[self.card.pk, "cash"]),
                    reverse("card_entry_add", args=[self.card.pk, "pay"]), reverse("card_entry_add", args=[self.card.pk, "spend"]),
                    reverse("card_entry_add", args=[self.card.pk, "charge"]), reverse("card_entry_add", args=[self.card.pk, "refund"]),
                    reverse("card_emi_add", args=[self.card.pk]), reverse("card_mfs"), reverse("card_mfs_detail", args=[self.nagad.pk]),
                    reverse("card_mfs_add"), reverse("card_entry_new", args=["pay"])):
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_add_a_card_without_its_number(self):
        r = self.client.post(reverse("card_create"), {"name": "EBL Mastercard", "statement_day": "20", "due_day": "10", "color": "green",
                                                      "opening_date": "2026-01-01"})
        c = Card.objects.get(name="EBL Mastercard")
        self.assertRedirects(r, reverse("card_detail", args=[c.pk]))
        self.assertEqual((c.last4, c.transfer_fee_rate, c.min_due_floor), ("", D(0), D(500)))
        r = self.client.post(reverse("card_create"), {"name": "x", "statement_day": "5", "due_day": "25", "last4": "1234567812345678", "color": "blue", "opening_date": "2026-01-01"})
        self.assertContains(r, "last 4 digits only")

    def test_take_money_to_bkash_fee_from_the_rate(self):
        today = timezone.localdate()
        r = self.client.post(reverse("card_entry_add", args=[self.card.pk, "cash"]), {
            "card": self.card.pk, "wallet": self.bkash.pk, "amount": "20000", "fee_rate": "1.5", "fee": "", "date": today.isoformat()})
        self.assertRedirects(r, reverse("card_detail", args=[self.card.pk]))
        e = CardEntry.objects.get()
        self.assertEqual((e.kind, e.fee, e.debt), ("cash", D("300.00"), D("20300.00")))
        self.assertEqual(wallets.balances(self.me)[self.bkash.pk], D("20000"))

    def test_pay_from_mobile_banking_route_and_fee(self):
        today = timezone.localdate()
        r = self.client.post(reverse("card_entry_add", args=[self.card.pk, "pay"]), {
            "card": self.card.pk, "wallet": self.nagad.pk, "route": "", "amount": "1000", "fee_rate": "1", "fee": "", "date": today.isoformat()})
        e = CardEntry.objects.get()
        self.assertEqual((e.route, e.fee), ("mfs_bill", D("10.00")))
        self.assertEqual(wallets.balances(self.me)[self.nagad.pk], D("-1010"))
        self.assertIn("From card UCB Visa", [m.title for m in wallets.movements(self.me)] + ["From card UCB Visa"])

    def test_not_someone_elses_card(self):
        other = User.objects.create_user("other", "o@example.com", PW)
        self.client.force_login(other)
        self.assertEqual(self.client.get(reverse("card_detail", args=[self.card.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("card_mfs_detail", args=[self.nagad.pk])).status_code, 404)


class RouteTests(Base):
    def test_cheapest_way_to_pay_first(self):
        Wallet.objects.create(user=self.me, name="City Bank", kind="bank", opening_balance=D("50000"), opening_date=date(2026, 1, 1))
        routes = sv.pay_routes(self.me, D("10000"))
        self.assertEqual((routes[0].wallet.name, routes[0].fee), ("City Bank", D(0)))     # the only one with the money
        self.assertNotIn(("bKash", "mfs_bill"), [(r.wallet.name, r.route) for r in routes])  # bKash can't pay bills here

    def test_borrowing_cost_as_a_yearly_rate(self):
        today = timezone.localdate()
        self.entry("cash", "10000", today - timedelta(days=5), wallet=self.bkash, fee=D("150"))
        cost = sv.borrowing_cost([sv.card_state(self.card, today)], today)
        self.assertEqual(cost["rate"], D("1.50"))
        self.assertGreater(cost["yearly"], D("10"))


class ElsewhereTests(Base):
    def test_home_upcoming_and_the_report_see_the_cards(self):
        today = timezone.localdate()
        self.entry("spend", "4000", today - timedelta(days=40))
        self.entry("charge", "250", today - timedelta(days=2), charge_type="late")
        home = self.client.get(reverse("home"))
        self.assertContains(home, reverse("card_dashboard"))
        self.assertEqual(home.context["cards_payable"], D("4250"))
        self.assertContains(self.client.get(reverse("upcoming")), "UCB Visa")
        self.assertContains(self.client.get(reverse("money_report")), "Credit card")

    def test_menu_and_search_by_bank(self):
        self.assertContains(self.client.get(reverse("card_dashboard")), 'href="/cards/"')
        self.card.name = "Platinum"
        self.card.save()
        r = self.client.get(reverse("search"), {"q": "UCB"})
        self.assertContains(r, reverse("card_detail", args=[self.card.pk]))


class ListsTests(Base):
    """Bank and card type are lists you keep yourself, with a + beside each dropdown."""

    def test_the_card_form_offers_your_lists_with_a_plus(self):
        r = self.client.get(reverse("card_create"))
        self.assertEqual(CardNetwork.objects.filter(user=self.me).count(), 6)          # Visa, Mastercard… the first time
        for kind in ("card_bank", "card_network"):
            self.assertContains(r, reverse("quick_create", args=[kind]))
        self.assertContains(r, '<option value="%s">UCB</option>' % self.ucb.pk, html=True)

    def test_plus_adds_one_and_picks_an_existing_one(self):
        url = reverse("quick_create", args=["card_bank"])
        r = self.client.post(url, {"qa_card_bank-name": "  EBL "})
        self.assertEqual((r.status_code, r.json()["name"]), (201, "EBL"))
        r = self.client.post(url, {"qa_card_bank-name": "ebl"})
        self.assertEqual((r.status_code, CardBank.objects.filter(user=self.me, name__iexact="ebl").count()), (200, 1))
        r = self.client.post(reverse("quick_create", args=["card_network"]), {"qa_card_network-name": "Amex Gold"})
        self.assertEqual(r.status_code, 201)
        r = self.client.post(reverse("quick_create", args=["card_wallet"]), {"qa_card_wallet-name": "Upay", "qa_card_wallet-kind": "mobile",
                                                                            "qa_card_wallet-opening_balance": ""})
        self.assertEqual((r.status_code, Wallet.objects.get(user=self.me, name="Upay").kind), (201, "mobile"))
        self.assertContains(self.client.get(reverse("card_entry_add", args=[self.card.pk, "cash"])), reverse("quick_create", args=["card_wallet"]))

    def test_rename_hide_and_delete_only_when_unused(self):
        url = reverse("card_lists")
        self.client.post(url, {"list": "bank", "action": "rename", "pk": self.ucb.pk, "name": "United Commercial Bank"})
        self.card.refresh_from_db()
        self.assertEqual(str(self.card.bank), "United Commercial Bank")
        self.client.post(url, {"list": "bank", "action": "delete", "pk": self.ucb.pk})
        self.assertTrue(CardBank.objects.filter(pk=self.ucb.pk).exists())            # a card uses it
        self.client.post(url, {"list": "bank", "action": "toggle", "pk": self.ucb.pk})
        offered = lambda url: list(self.client.get(url).context["form"].fields["bank"].queryset)
        self.assertNotIn(self.ucb, offered(reverse("card_create")))
        self.assertIn(self.ucb, offered(reverse("card_edit", args=[self.card.pk])))      # still on its own card
        self.client.post(url, {"list": "bank", "action": "add", "name": "City Bank"})
        city = CardBank.objects.get(name="City Bank")
        self.client.post(url, {"list": "bank", "action": "delete", "pk": city.pk})
        self.assertFalse(CardBank.objects.filter(pk=city.pk).exists())
        other = User.objects.create_user("other", "o@example.com", PW)
        self.client.force_login(other)
        self.client.post(url, {"list": "bank", "action": "rename", "pk": self.ucb.pk, "name": "Mine now"})
        self.assertEqual(CardBank.objects.get(pk=self.ucb.pk).name, "United Commercial Bank")
