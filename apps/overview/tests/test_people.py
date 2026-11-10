""""Both ways": someone in Creditors and in Debtors, the net, and setting one
balance off against the other."""
from datetime import timedelta
from decimal import Decimal as D

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.creditors.models import Creditor, Transaction as CreditorTx
from apps.debtors.models import Debtor, Transaction as DebtorTx
from apps.wallets.services import balances

from ..people import pairs, phone_key


class BothWaysTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("me", password="pw12345!")
        self.client.force_login(self.user)
        self.day = timezone.localdate() - timedelta(days=3)

    def owe(self, name, amount, phone=""):
        c = Creditor.objects.create(user=self.user, name=name, phone=phone)
        CreditorTx.objects.create(creditor=c, transaction_type=CreditorTx.BORROW, amount=D(amount), date=self.day)
        return c

    def owed(self, name, amount, phone=""):
        d = Debtor.objects.create(user=self.user, name=name, phone=phone)
        DebtorTx.objects.create(debtor=d, transaction_type=DebtorTx.LEND, amount=D(amount), date=self.day)
        return d

    def test_phone_numbers_match_whatever_the_prefix(self):
        self.assertEqual(phone_key("+880 1711-000000"), phone_key("01711000000"))

    def test_matches_by_phone_or_by_name_when_a_number_is_missing(self):
        self.owe("Karim Bhai", "5000", phone="+8801711000000")
        self.owed("Karim", "3000", phone="01711-000000")
        self.owe("rafi ", "100")
        self.owed("Rafi", "50", phone="01999999999")
        self.owe("Joy", "100", phone="01811111111")
        self.owed("Joy", "100", phone="01822222222")       # same name, different numbers: two people
        found = {(p.creditor.name, p.debtor.name) for p in pairs(self.user)}
        self.assertEqual(found, {("Karim Bhai", "Karim"), ("rafi ", "Rafi")})

    def test_the_net_and_the_page(self):
        self.owe("Karim", "5000")
        self.owed("Karim", "3000")
        pair = pairs(self.user)[0]
        self.assertEqual((pair.you_owe, pair.they_owe, pair.net, pair.can_set_off), (D("5000"), D("3000"), D("-2000"), D("3000")))
        r = self.client.get(reverse("people"))
        self.assertContains(r, "Overall, you owe them ৳2,000.")
        self.assertContains(r, "Set off ৳3,000 against each other")

    def test_setting_off_clears_the_smaller_side_on_both_and_moves_no_wallet(self):
        c = self.owe("Karim", "5000")
        d = self.owed("Karim", "3000")
        before = balances(self.user)
        r = self.client.post(reverse("people_set_off"), {"creditor": c.pk, "debtor": d.pk, "amount": "99999"})
        self.assertRedirects(r, reverse("people"))
        self.assertEqual((c.remaining, d.remaining), (D("2000"), D("0")))
        repay = c.transactions.get(transaction_type=CreditorTx.REPAY)
        self.assertEqual((repay.amount, repay.wallet_id), (D("3000"), None))
        self.assertEqual(balances(self.user), before)
        # Nothing left to set off: a second press changes nothing.
        self.client.post(reverse("people_set_off"), {"creditor": c.pk, "debtor": d.pk})
        self.assertEqual(c.transactions.count(), 2)

    def test_set_off_refuses_two_different_people_and_other_peoples_records(self):
        c = self.owe("Karim", "5000")
        d = self.owed("Rafi", "3000")
        self.client.post(reverse("people_set_off"), {"creditor": c.pk, "debtor": d.pk})
        self.assertEqual(c.transactions.count(), 1)
        other = User.objects.create_user("them", password="pw12345!")
        theirs = Debtor.objects.create(user=other, name="Karim")
        self.assertEqual(self.client.post(reverse("people_set_off"), {"creditor": c.pk, "debtor": theirs.pk}).status_code, 404)
        self.assertEqual(self.client.get(reverse("people_set_off")).status_code, 405)

    def test_the_creditor_page_shows_the_other_side(self):
        c = self.owe("Karim", "5000")
        self.owed("Karim", "3000")
        r = self.client.get(reverse("creditor_detail", args=[c.pk]))
        self.assertContains(r, "Karim is in both lists")
        self.assertContains(r, 'name="next" value="' + reverse("creditor_detail", args=[c.pk]))


class RecentEntriesTests(TestCase):
    def test_home_lists_bazar_shop_dues_and_contributions_too(self):
        from apps.contributors.models import Contribution, Contributor
        from apps.household.models import Purchase
        from apps.shops.models import Shop, Transaction as ShopTx

        user = User.objects.create_user("me", password="pw12345!")
        self.client.force_login(user)
        today = timezone.localdate()
        Purchase.objects.create(user=user, amount=D("300"), date=today)
        shop = Shop.objects.create(user=user, name="Mayer Doa Store")
        ShopTx.objects.create(shop=shop, transaction_type=ShopTx.PURCHASE, amount=D("800"), date=today - timedelta(days=1))
        giver = Contributor.objects.create(user=user, name="Uncle")
        Contribution.objects.create(contributor=giver, amount=D("1000"), date=today - timedelta(days=2))
        recent = self.client.get(reverse("home")).context["recent"]
        self.assertEqual([(r["title"], r["kind"], r["amount"]) for r in recent], [
            ("Bazar", "Bazar", D("-300")),
            ("Mayer Doa Store", "Bought on baki", D("-800")),
            ("Uncle", "Received", D("1000")),
        ])


class BanglaPagesTests(TestCase):
    """The new pages and messages read in Bangla too."""

    def test_new_pages_in_bangla(self):
        user = User.objects.create_user("bn_user", password="pw12345!")
        self.client.force_login(user)
        self.client.post(reverse("update_preferences"), {"language": "bn"})
        day = timezone.localdate() - timedelta(days=2)
        c = Creditor.objects.create(user=user, name="করিম")
        CreditorTx.objects.create(creditor=c, transaction_type=CreditorTx.BORROW, amount=D("5000"), date=day)
        d = Debtor.objects.create(user=user, name="করিম")
        DebtorTx.objects.create(debtor=d, transaction_type=DebtorTx.LEND, amount=D("2000"), date=day)
        self.assertContains(self.client.get(reverse("people")), "দুই দিকেই লেনদেন")
        page = self.client.get(reverse("creditor_detail", args=[c.pk]))
        self.assertContains(page, "করিম দুই তালিকাতেই আছেন")
        self.assertContains(page, "পুরোটা ·")
        self.assertContains(page, "এরপর আপনার দেনা ছিল")
        self.assertEqual(self.client.get(reverse("debtor_detail", args=[d.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("help")).status_code, 200)
