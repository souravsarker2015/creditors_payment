"""A delete never ends on "page not found", and the box says what it touches in this very case.

The record's page opens after it's deleted (it says so, and can be restored), whatever still links to it; the box
stays until the next page comes (templates/partials/ask.html); and a delete sent twice just goes back where it was."""
from datetime import date, timedelta
from decimal import Decimal as D

from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils.translation import override

from apps.business.core.testing import make_farm
from apps.business.credit.models import Direction, PartyPayment
from apps.business.finance.models import Account
from apps.business.parties.models import Party
from apps.business.ponds.models import CultureCycle, LeasePayment, Pond
from apps.creditors.models import Creditor, Transaction
from apps.productivity.models import Project, Task


def lines(client, url):
    return client.get(reverse("delete_check"), {"url": url}).json()


class Farm(TestCase):
    def setUp(self):
        self.b, self.owner, self.staff = make_farm()
        self.client.force_login(self.owner)
        self.cash = Account.objects.create(business=self.b, name="Cash box", kind="cash", opening_balance=D("5000"))
        self.pond = Pond.objects.create(business=self.b, name="East pond")
        self.cycle = CultureCycle.objects.create(business=self.b, pond=self.pond, name="Boro", start_date=date.today() - timedelta(days=9))
        self.party = Party.objects.create(business=self.b, name="Karim", is_supplier=True)


class PageOfADeletedRecordTests(Farm):
    def test_a_deleted_pond_says_so_and_can_be_restored(self):
        self.pond.soft_delete()
        page = self.client.get(reverse("business:pond_detail", args=[self.pond.pk]))
        self.assertContains(page, "This pond is deleted")
        self.assertContains(page, reverse("business:ponds_restore", args=[self.pond.pk]))
        self.assertNotContains(page, reverse("business:ponds_edit", args=[self.pond.pk]))

    def test_a_deleted_account_still_shows_its_book_and_its_real_balance(self):
        self.cash.soft_delete()
        page = self.client.get(reverse("business:account_detail", args=[self.cash.pk]))
        self.assertContains(page, "This account is deleted")
        self.assertEqual(page.context["balance"], D("5000"))
        self.assertNotContains(page, reverse("business:transfer_add"))

    def test_a_deleted_person_keeps_their_statement(self):
        PartyPayment.objects.create(business=self.b, party=self.party, direction=Direction.OUT, date=date.today(), amount=D("200"), account=self.cash)
        self.party.soft_delete()
        page = self.client.get(reverse("business:party_statement", args=[self.party.pk]))
        self.assertContains(page, "This person is deleted")
        self.assertTrue(page.context["led"].entries)
        self.assertContains(page, reverse("business:suppliers_restore", args=[self.party.pk]))

    def test_someone_elses_deleted_record_stays_out_of_reach(self):
        other, owner, _ = make_farm("other")
        pond = Pond.objects.create(business=other, name="Theirs")
        pond.soft_delete()
        self.assertEqual(self.client.get(reverse("business:pond_detail", args=[pond.pk])).status_code, 404)

    def test_what_stays_can_still_be_deleted_after_what_it_belonged_to(self):
        """Each of these used to delete, then land on "page not found": the page it goes back to had gone."""
        pay = PartyPayment.objects.create(business=self.b, party=self.party, direction=Direction.OUT, date=date.today(), amount=D("200"), account=self.cash)
        lease = LeasePayment.objects.create(business=self.b, pond=self.pond, date=date.today(), amount=D("500"), account=self.cash)
        self.party.soft_delete()
        self.pond.soft_delete()
        for url in (reverse("business:payment_delete", args=[pay.pk]), reverse("business:lease_payment_delete", args=[lease.pk]),
                    reverse("business:cycle_delete", args=[self.cycle.pk])):
            self.assertEqual(self.client.post(url, follow=True).status_code, 200, url)


class CycleRestoreTests(Farm):
    def test_a_deleted_cycle_is_listed_on_its_pond_and_comes_back(self):
        self.client.post(reverse("business:cycle_delete", args=[self.cycle.pk]))
        self.assertContains(self.client.get(reverse("business:pond_detail", args=[self.pond.pk])), "Deleted cycles")
        page = self.client.get(reverse("business:cycle_detail", args=[self.cycle.pk]))
        self.assertContains(page, "This cycle is deleted")
        self.assertNotContains(page, reverse("business:cycle_edit", args=[self.cycle.pk]))
        self.client.post(reverse("business:cycle_restore", args=[self.cycle.pk]))
        self.assertTrue(CultureCycle.objects.filter(pk=self.cycle.pk).exists())

    def test_two_running_cycles_cant_come_of_it(self):
        self.cycle.soft_delete()
        CultureCycle.objects.create(business=self.b, pond=self.pond, name="New", start_date=date.today())
        self.client.post(reverse("business:cycle_restore", args=[self.cycle.pk]))
        self.assertFalse(CultureCycle.objects.filter(pk=self.cycle.pk).exists())

    def test_only_someone_who_can_delete_restores(self):
        self.cycle.soft_delete()
        self.client.force_login(self.staff)
        self.assertEqual(self.client.post(reverse("business:cycle_restore", args=[self.cycle.pk])).status_code, 403)


class SentTwiceTests(Farm):
    def send(self, url):
        return self.client.post(url, {"_ft_key": str(self.n), "_ft_user": self.owner.pk, "_ft_page": reverse("business:ponds")})

    def setUp(self):
        super().setUp()
        self.n = 1

    def test_a_delete_from_an_old_page_goes_back_there(self):
        url = reverse("business:ponds_delete", args=[self.pond.pk])
        self.assertEqual(self.send(url).status_code, 302)
        self.n = 2                     # (a new key: an old window, not the same click sent again)
        again = self.client.post(url, {"_ft_key": "2", "_ft_user": self.owner.pk, "_ft_page": reverse("business:ponds")}, follow=True)
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.request["PATH_INFO"], reverse("business:ponds"))
        self.assertContains(again, "already gone")

    def test_the_page_it_goes_back_to_is_only_ever_this_site(self):
        url = reverse("business:ponds_delete", args=[self.pond.pk])
        self.pond.soft_delete()
        back = self.client.post(url, {"_ft_key": "3", "_ft_user": self.owner.pk, "_ft_page": "https://example.com/"})
        self.assertEqual(back["Location"], "/")

    def test_the_same_click_sent_twice_is_still_one_delete(self):
        url = reverse("business:ponds_delete", args=[self.pond.pk])
        self.send(url)
        self.assertEqual(self.send(url)["Location"], reverse("business:ponds"))


class BusinessWarningTests(Farm):
    def url(self, name, pk):
        return reverse(f"business:{name}", args=[pk])

    def test_fish_in_the_pond(self):
        said = lines(self.client, self.url("ponds_delete", self.pond.pk))
        self.assertIn("Fish are in this pond now (Boro).", said["lines"])
        self.assertFalse(said["blocked"])

    def test_how_many_records_use_it(self):
        for n in range(3):
            LeasePayment.objects.create(business=self.b, pond=self.pond, date=date.today(), amount=D("10"), account=self.cash)
        said = lines(self.client, self.url("ponds_delete", self.pond.pk))["lines"]
        self.assertIn("4 records use it, and stay as they are.", said)       # (the cycle too)

    def test_money_left_in_an_account(self):
        said = lines(self.client, self.url("accounts_delete", self.cash.pk))["lines"]
        self.assertTrue(any("5,000" in line and "total money" in line for line in said), said)

    def test_the_default_account(self):
        self.cash.is_default = True
        self.cash.save()
        self.assertIn("This is your default account. Pick another one for new entries.", lines(self.client, self.url("accounts_delete", self.cash.pk))["lines"])

    def test_what_the_server_would_refuse_is_said_before_the_click(self):
        PartyPayment.objects.create(business=self.b, party=self.party, direction=Direction.OUT, date=date.today(), amount=D("200"), account=self.cash)
        said = lines(self.client, self.url("suppliers_delete", self.party.pk))
        self.assertTrue(said["blocked"])
        self.assertIn("still has a balance", said["lines"][0])

    def test_nothing_about_another_farm_or_without_the_right_to_delete(self):
        other, owner, _ = make_farm("other")
        theirs = Pond.objects.create(business=other, name="Theirs")
        self.assertEqual(lines(self.client, self.url("ponds_delete", theirs.pk))["lines"], [])
        self.client.force_login(self.staff)
        self.assertEqual(lines(self.client, self.url("ponds_delete", self.pond.pk))["lines"], [])


class PersonalWarningTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.me = User.objects.create_user("me", password="x")
        self.other = User.objects.create_user("other", password="x")
        self.client.force_login(self.me)

    def test_what_is_owed_and_what_goes_with_it(self):
        c = Creditor.objects.create(user=self.me, name="Rahim")
        Transaction.objects.create(creditor=c, transaction_type=Transaction.BORROW, amount=D("700"), date=date.today())
        said = lines(self.client, reverse("creditor_delete", args=[c.pk]))["lines"]
        self.assertTrue(any("700" in line for line in said), said)
        self.assertIn("1 entry goes with it.", said)

    def test_what_stays_is_told_apart_from_what_goes(self):
        p = Project.objects.create(owner=self.me, name="Site")
        Task.objects.create(owner=self.me, title="T", project=p, order=1)
        self.assertIn("1 entry stays, without it.", lines(self.client, reverse("work:project_delete", args=[p.pk]))["lines"])

    def test_someone_elses_record_says_nothing(self):
        c = Creditor.objects.create(user=self.other, name="Theirs")
        self.assertEqual(lines(self.client, reverse("creditor_delete", args=[c.pk]))["lines"], [])

    def test_a_page_with_nothing_to_say(self):
        self.assertEqual(lines(self.client, "/no/such/page/")["lines"], [])
        self.assertEqual(lines(self.client, "https://example.com/creditors/1/delete/")["lines"], [])

    def test_signed_out_it_gives_nothing(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("delete_check"), {"url": "/"}).status_code, 302)


class BoxTests(SimpleTestCase):
    def box(self):
        return render_to_string("partials/ask.html", {"active_dashboard": "business"})

    def test_it_stays_until_the_next_page_comes(self):
        self.assertIn("function hold()", self.box())
        self.assertIn("hold: true", self.box())

    def test_a_page_that_comes_back_is_usable_again(self):
        self.assertIn('addEventListener("pageshow", function () { FT.askDone(); })', self.box())

    def test_it_says_so_in_bangla(self):
        with override("bn"):
            self.assertIn("মুছে ফেলা হচ্ছে", self.box())
