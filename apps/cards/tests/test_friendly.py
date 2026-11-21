"""Credit cards made easy to use: every record, EMI and mobile banking wallet can be opened (details), edited,
recorded again and deleted, from wherever it's listed, and you come back to where you were; a guide and
five getting-started steps that tick themselves for someone new."""
from datetime import timedelta
from decimal import Decimal as D

from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone

from apps.trash.models import DeletedItem
from apps.wallets import services as wallets
from apps.wallets.models import Wallet

from ..models import Card, CardEntry, EmiPlan, MfsFees
from .test_cards import PW, Base


class GuideTests(Base):
    def test_a_new_user_sees_the_five_steps_and_the_guide(self):
        new = User.objects.create_user("new", "n@example.com", PW)
        self.client.force_login(new)
        r = self.client.get(reverse("card_dashboard"))
        steps = r.context["steps"]
        self.assertEqual((steps["done"], steps["total"]), (0, 5))
        self.assertTrue(steps["rows"][0]["next"])
        self.assertContains(r, "Welcome! Start in 5 short steps")
        self.assertContains(r, reverse("card_create"))
        g = self.client.get(reverse("card_guide"))
        for part in ('id="what-to-tap"', 'id="words"', 'id="example"', 'id="pay"', "Minimum payment", "Take money to bKash / Nagad"):
            self.assertContains(g, part)

    def test_the_steps_tick_themselves(self):
        steps = self.client.get(reverse("card_dashboard")).context["steps"]
        self.assertEqual([s["done"] for s in steps["rows"]], [True, True, True, False, False])
        self.entry("cash", "1000", timezone.localdate(), wallet=self.bkash)
        self.entry("pay", "1000", timezone.localdate(), wallet=self.bkash)
        r = self.client.get(reverse("card_dashboard"))
        self.assertTrue(r.context["steps"]["all"])
        self.assertNotContains(r, "Getting started")                     # done: out of the way


class RecordTests(Base):
    def setUp(self):
        super().setUp()
        self.today = timezone.localdate()
        self.cash = self.entry("cash", "20000", self.today - timedelta(days=3), wallet=self.bkash, fee_rate=D("1.5"), fee=D("300"), note="Rent")

    def test_details_say_what_it_did_and_which_bill(self):
        r = self.client.get(reverse("card_entry_detail", args=[self.cash.pk]))
        self.assertEqual(r.context["card_change"], D("20300"))
        self.assertEqual(r.context["wallet_change"], D("20000"))
        self.assertIsNotNone(r.context["on_bill"] or r.context["later"])
        self.assertContains(r, "Rent")
        self.assertContains(r, reverse("card_entry_edit", args=[self.cash.pk]))
        self.assertContains(r, f"?copy={self.cash.pk}")
        pay = self.entry("pay", "5000", self.today, wallet=self.nagad, fee=D("50"), route="mfs_bill")
        r = self.client.get(reverse("card_entry_detail", args=[pay.pk]))
        self.assertEqual((r.context["card_change"], r.context["wallet_change"]), (D("-5000"), D("-5050")))

    def test_every_list_opens_the_details(self):
        detail = reverse("card_entry_detail", args=[self.cash.pk])
        for url in (reverse("card_dashboard"), reverse("card_detail", args=[self.card.pk]), reverse("card_records"),
                    reverse("card_mfs_detail", args=[self.bkash.pk])):
            r = self.client.get(url)
            self.assertContains(r, detail, msg_prefix=url)
            self.assertContains(r, reverse("card_entry_delete", args=[self.cash.pk]), msg_prefix=url)
        self.assertContains(self.client.get(reverse("wallet_detail", args=[self.bkash.pk])), detail)   # the wallet's own history too

    def test_edit_comes_back_to_where_it_was_opened(self):
        records = reverse("card_records") + "?card=%s" % self.card.pk
        r = self.client.post(reverse("card_entry_edit", args=[self.cash.pk]) + "?next=" + records.replace("?", "%3F").replace("=", "%3D"), {
            "card": self.card.pk, "wallet": self.bkash.pk, "amount": "25000", "fee_rate": "1.5", "fee": "", "date": self.cash.date.isoformat(),
            "note": "Rent", "next": records})
        self.assertRedirects(r, records, fetch_redirect_response=False)
        self.cash.refresh_from_db()
        self.assertEqual((self.cash.amount, self.cash.fee), (D("25000"), D("375.00")))
        r = self.client.post(reverse("card_entry_edit", args=[self.cash.pk]), {
            "card": self.card.pk, "wallet": self.bkash.pk, "amount": "25000", "fee_rate": "1.5", "fee": "375", "date": self.cash.date.isoformat(),
            "next": "https://evil.example.com/"})
        self.assertRedirects(r, reverse("card_entry_detail", args=[self.cash.pk]), fetch_redirect_response=False)   # never another site

    def test_delete_from_a_list_undo_brings_it_back(self):
        records = reverse("card_records")
        r = self.client.post(reverse("card_entry_delete", args=[self.cash.pk]), {"next": records})
        self.assertRedirects(r, records, fetch_redirect_response=False)
        self.assertFalse(CardEntry.objects.filter(pk=self.cash.pk).exists())
        self.assertEqual(wallets.balances(self.me).get(self.bkash.pk, D(0)), D(0))
        item = DeletedItem.objects.get(user=self.me)
        self.client.post(reverse("trash_restore", args=[item.pk]))
        self.assertTrue(CardEntry.objects.filter(pk=self.cash.pk, wallet=self.bkash).exists())

    def test_delete_from_its_own_page_goes_to_the_card(self):
        r = self.client.post(reverse("card_entry_delete", args=[self.cash.pk]), {"next": reverse("card_entry_detail", args=[self.cash.pk])})
        self.assertRedirects(r, reverse("card_detail", args=[self.card.pk]) + "?tab=records", fetch_redirect_response=False)

    def test_record_again_fills_the_form_dated_today(self):
        r = self.client.get(reverse("card_entry_new", args=["cash"]) + f"?copy={self.cash.pk}")
        form = r.context["form"]
        self.assertEqual((str(form["amount"].value()), form["wallet"].value(), form["note"].value()), ("20000.00", self.bkash.pk, "Rent"))
        self.assertEqual(form["date"].value(), self.today)
        other = User.objects.create_user("other", "o@example.com", PW)
        self.client.force_login(other)
        Card.objects.create(user=other, name="Mine", statement_day=1, due_day=20)
        r = self.client.get(reverse("card_entry_new", args=["cash"]) + f"?copy={self.cash.pk}")
        self.assertNotEqual(r.context["form"]["note"].value(), "Rent")          # not someone else's record

    def test_save_and_add_another(self):
        r = self.client.post(reverse("card_entry_add", args=[self.card.pk, "spend"]), {
            "card": self.card.pk, "amount": "1200", "date": self.today.isoformat(), "note": "Shoes", "another": "1"})
        self.assertRedirects(r, reverse("card_entry_add", args=[self.card.pk, "spend"]), fetch_redirect_response=False)
        self.assertTrue(CardEntry.objects.filter(kind="spend", note="Shoes").exists())

    def test_records_filters_and_totals(self):
        self.entry("spend", "4000", self.today - timedelta(days=1), note="Daraz laptop bag")
        self.entry("pay", "10000", self.today, wallet=self.nagad, fee=D("100"), route="mfs_bill")
        url = reverse("card_records")
        r = self.client.get(url)
        self.assertEqual(r.context["count"], 3)
        self.assertEqual(r.context["totals"], {"taken": D("20000"), "spent": D("4000"), "paid": D("10000"), "costs": D("400")})
        self.assertEqual(self.client.get(url, {"kind": "spend"}).context["count"], 1)
        self.assertEqual(self.client.get(url, {"q": "daraz"}).context["count"], 1)
        self.assertEqual(self.client.get(url, {"wallet": self.nagad.pk}).context["count"], 1)
        self.assertEqual(self.client.get(url, {"start": self.today.isoformat()}).context["count"], 1)
        self.assertEqual(self.client.get(url, {"card": "999999"}).context["count"], 0)
        self.assertEqual(self.client.get(url, {"start": "not a date", "kind": "nonsense"}).status_code, 200)

    def test_card_page_tabs(self):
        for tab in ("overview", "bills", "records", "emis", "details", "nonsense"):
            r = self.client.get(reverse("card_detail", args=[self.card.pk]), {"tab": tab})
            self.assertEqual(r.context["tab"], tab if tab != "nonsense" else "overview")
        self.assertEqual(r.context["rows"][0].group, "cash")


class EmiDetailTests(Base):
    def test_details_edit_and_delete(self):
        p = EmiPlan.objects.create(card=self.card, title="Laptop", amount=D("60000"), months=12, start=timezone.localdate() - timedelta(days=70))
        r = self.client.get(reverse("card_emi_detail", args=[p.pk]))
        self.assertContains(r, "Laptop")
        self.assertEqual(len(r.context["st"].rows), 12)
        self.assertContains(r, reverse("card_emi_edit", args=[p.pk]))
        r = self.client.post(reverse("card_emi_edit", args=[p.pk]), {"card": self.card.pk, "title": "Laptop", "amount": "60000", "months": "6",
                                                                     "rate": "", "fee": "", "start": p.start.isoformat()})
        self.assertRedirects(r, reverse("card_emi_detail", args=[p.pk]), fetch_redirect_response=False)
        p.refresh_from_db()
        self.assertEqual(p.months, 6)
        self.assertContains(self.client.get(reverse("card_detail", args=[self.card.pk])), reverse("card_emi_detail", args=[p.pk]))
        r = self.client.post(reverse("card_emi_delete", args=[p.pk]), {"next": reverse("card_emi_detail", args=[p.pk])})
        self.assertRedirects(r, reverse("card_detail", args=[self.card.pk]) + "?tab=emis", fetch_redirect_response=False)
        self.assertFalse(EmiPlan.objects.filter(pk=p.pk).exists())


class MobileBankingTests(Base):
    def test_edit_name_and_charges_in_one_form(self):
        r = self.client.post(reverse("card_mfs_edit", args=[self.nagad.pk]), {
            "name": "Nagad (personal)", "kind": "mobile", "number": "01700000000", "opening_balance": "500", "opening_date": "2026-01-01",
            "fees-pays_bills": "on", "fees-bill_rate": "0.75", "fees-bank_rate": "1"})
        self.assertRedirects(r, reverse("card_mfs_detail", args=[self.nagad.pk]), fetch_redirect_response=False)
        self.nagad.refresh_from_db()
        self.assertEqual((self.nagad.name, self.nagad.number), ("Nagad (personal)", "01700000000"))
        self.assertEqual(MfsFees.objects.get(wallet=self.nagad).bill_rate, D("0.75"))

    def test_stop_using_and_delete_keeps_card_records(self):
        e = self.entry("cash", "1000", timezone.localdate(), wallet=self.nagad)
        self.client.post(reverse("card_mfs_toggle", args=[self.nagad.pk]))
        self.nagad.refresh_from_db()
        self.assertFalse(self.nagad.is_active)
        r = self.client.post(reverse("card_mfs_delete", args=[self.nagad.pk]))
        self.assertRedirects(r, reverse("card_mfs"), fetch_redirect_response=False)
        e.refresh_from_db()
        self.assertIsNone(e.wallet_id)                                       # the record stays, without the wallet
        self.client.post(reverse("trash_restore", args=[DeletedItem.objects.get(user=self.me).pk]))
        e.refresh_from_db()
        self.assertEqual(e.wallet_id, self.nagad.pk)                         # undo puts the link back

    def test_charges_form_never_sends_you_to_another_site(self):
        r = self.client.post(reverse("card_mfs_detail", args=[self.nagad.pk]) + "?next=https://evil.example.com/",
                             {"pays_bills": "on", "bill_rate": "1", "bank_rate": "1"})
        self.assertRedirects(r, reverse("card_mfs_detail", args=[self.nagad.pk]), fetch_redirect_response=False)

    def test_only_your_own(self):
        other = User.objects.create_user("other", "o@example.com", PW)
        self.client.force_login(other)
        for name in ("card_mfs_edit",):
            self.assertEqual(self.client.get(reverse(name, args=[self.nagad.pk])).status_code, 404)
        for name in ("card_mfs_toggle", "card_mfs_delete"):
            self.assertEqual(self.client.post(reverse(name, args=[self.nagad.pk])).status_code, 404)
        self.assertTrue(Wallet.objects.filter(pk=self.nagad.pk, is_active=True).exists())
        e = self.entry("cash", "1000", timezone.localdate(), wallet=self.bkash)
        self.assertEqual(self.client.get(reverse("card_entry_detail", args=[e.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("card_records")).context["count"], 0)


class DeleteQuestionTests(Base):
    def test_the_delete_question_says_what_is_still_owed(self):
        self.entry("spend", "3000", timezone.localdate())
        r = self.client.get(reverse("delete_check"), {"url": reverse("card_delete", args=[self.card.pk])})
        self.assertTrue(any("3,000" in line for line in r.json()["lines"]), r.json())
        r = self.client.get(reverse("delete_check"), {"url": reverse("card_mfs_delete", args=[self.nagad.pk])})
        self.assertEqual(r.status_code, 200)


class CardFormTests(Base):
    def test_the_optional_parts_fold_but_open_on_an_error(self):
        r = self.client.get(reverse("card_create"))
        groups = r.context["form"].groups()
        self.assertEqual([g[3] for g in groups], [False, False, False, False, True, True, True])
        self.assertFalse(groups[4][4])
        r = self.client.post(reverse("card_create"), {"name": "X", "statement_day": "5", "due_day": "25", "color": "blue",
                                                      "opening_date": "2026-01-01", "last4": "12"})
        self.assertTrue(r.context["form"].groups()[4][4])                    # "Look and number" opens to show the error
