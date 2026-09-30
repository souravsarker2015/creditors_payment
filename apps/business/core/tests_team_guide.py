"""Team logins made from the app, the "+ add" popups, and the How-it-works guide."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.business.core.models import Dashboard, Membership, Role, UserDashboardAccess
from apps.business.core.testing import make_farm
from apps.business.ponds.models import Pond

User = get_user_model()


class TeamLoginTests(TestCase):
    def setUp(self):
        self.b, self.owner, self.staff = make_farm()
        self.client.force_login(self.owner)
        self.url = reverse("business:team")

    def create(self, **over):
        data = {"tab": "create", "full_name": "Rahim Mia", "username": "rahim.farm",
                "password1": "PondFish2026", "password2": "PondFish2026", "role": Role.DATA_ENTRY}
        data.update(over)
        return self.client.post(self.url, data)

    def test_owner_makes_a_login_that_works(self):
        self.assertEqual(self.create().status_code, 302)
        user = User.objects.get(username="rahim.farm")
        self.assertEqual(user.first_name, "Rahim Mia")
        self.assertTrue(user.check_password("PondFish2026"))
        m = Membership.objects.get(business=self.b, user=user)
        self.assertEqual(m.role, Role.DATA_ENTRY)
        self.assertTrue(m.account_created)
        self.assertTrue(UserDashboardAccess.objects.filter(user=user, dashboard__code="business").exists())

    def test_the_new_person_can_sign_in_and_reach_the_farm(self):
        self.create()
        c = self.client_class()
        self.assertTrue(c.login(username="rahim.farm", password="PondFish2026"))
        self.assertEqual(c.get(reverse("business:home")).status_code, 200)

    def test_weak_passwords_are_refused(self):
        for password in ("12345678", "short", "password"):
            r = self.create(password1=password, password2=password)
            self.assertEqual(r.status_code, 200, password)
        self.assertFalse(User.objects.filter(username="rahim.farm").exists())

    def test_passwords_must_match(self):
        self.assertEqual(self.create(password2="Different2026").status_code, 200)
        self.assertFalse(User.objects.filter(username="rahim.farm").exists())

    def test_username_must_be_free_whatever_the_case(self):
        User.objects.create_user("Rahim.Farm", password="x")
        r = self.create()
        self.assertEqual(r.status_code, 200)
        self.assertIn("username", r.context["create_form"].errors)
        self.assertEqual(User.objects.filter(username__iexact="rahim.farm").count(), 1)

    def test_a_space_in_the_username_is_refused(self):
        self.assertEqual(self.create(username="rahim mia").status_code, 200)
        self.assertFalse(User.objects.filter(username="rahim mia").exists())

    def test_nobody_can_be_made_an_owner(self):
        r = self.create(role=Role.OWNER)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(User.objects.filter(username="rahim.farm").exists())

    def test_someone_who_already_has_an_account_can_be_added(self):
        friend = User.objects.create_user("friend", password="TheirOwn2026")
        r = self.client.post(self.url, {"tab": "existing", "username": "friend", "role": Role.VIEWER})
        self.assertEqual(r.status_code, 302)
        m = Membership.objects.get(business=self.b, user=friend)
        self.assertEqual(m.role, Role.VIEWER)
        self.assertFalse(m.account_created)      # not made here: no password button

    def test_owner_can_reset_a_login_made_here(self):
        self.create()
        m = Membership.objects.get(user__username="rahim.farm")
        r = self.client.post(reverse("business:member_password", args=[m.pk]),
                             {"password1": "NewPond9876", "password2": "NewPond9876"})
        self.assertEqual(r.status_code, 302)
        m.user.refresh_from_db()
        self.assertTrue(m.user.check_password("NewPond9876"))

    def test_owner_cannot_reset_an_account_someone_brought(self):
        friend = User.objects.create_user("friend", password="TheirOwn2026")
        m = Membership.objects.create(business=self.b, user=friend, role=Role.VIEWER)
        self.client.post(reverse("business:member_password", args=[m.pk]),
                         {"password1": "Hijacked2026", "password2": "Hijacked2026"})
        friend.refresh_from_db()
        self.assertTrue(friend.check_password("TheirOwn2026"))

    def test_a_weak_reset_is_refused(self):
        self.create()
        m = Membership.objects.get(user__username="rahim.farm")
        self.client.post(reverse("business:member_password", args=[m.pk]), {"password1": "1234", "password2": "1234"})
        m.user.refresh_from_db()
        self.assertTrue(m.user.check_password("PondFish2026"))

    def test_staff_cannot_make_logins_or_reset_passwords(self):
        self.create()
        m = Membership.objects.get(user__username="rahim.farm")
        self.client.force_login(self.staff)
        self.assertNotEqual(self.client.get(self.url).status_code, 200)
        self.client.post(reverse("business:member_password", args=[m.pk]), {"password1": "Sneaky2026x", "password2": "Sneaky2026x"})
        m.user.refresh_from_db()
        self.assertTrue(m.user.check_password("PondFish2026"))

    def test_another_farm_cannot_reset_our_person(self):
        self.create()
        m = Membership.objects.get(user__username="rahim.farm")
        _other, owner2, _s = make_farm(owner_name="other")
        self.client.force_login(owner2)
        r = self.client.post(reverse("business:member_password", args=[m.pk]), {"password1": "Sneaky2026x", "password2": "Sneaky2026x"})
        self.assertEqual(r.status_code, 404)
        m.user.refresh_from_db()
        self.assertTrue(m.user.check_password("PondFish2026"))


class QuickAddTests(TestCase):
    """The "+" beside a dropdown creates the record and hands it back."""

    def setUp(self):
        self.b, self.owner, self.staff = make_farm()
        self.client.force_login(self.owner)

    def add(self, _kind, **fields):
        data = {f"qa_{_kind}-{k}": v for k, v in fields.items()}
        return self.client.post(reverse("business:quick_add", args=[_kind]), data)

    def test_every_kind_can_be_added(self):
        cases = {
            "account": {"name": "Cash box", "kind": "cash"},
            "category": {"name": "Medicine", "type": "expense", "scope": "business"},
            "species": {"name": "Silver Barb"},
            "market": {"name": "New Aarot"},
            "supplier": {"name": "Hatchery One"},
            "buyer": {"name": "Paikar One"},
            "party": {"name": "Both Ways Trading", "role": "both"},
            "feed": {"name": "Starter 30%", "bag_size": "25"},
            "pond": {"name": "New Pond", "area": "40"},
            "deduction_type": {"name": "Weighing fee", "method": "fixed"},
        }
        for kind, fields in cases.items():
            r = self.add(kind, **fields)
            self.assertEqual(r.status_code, 201, f"{kind}: {r.content[:200]}")
            body = r.json()
            self.assertTrue(body["ok"] and body["id"], kind)
            self.assertEqual(body["kind"], kind)

    def test_a_new_feed_hands_back_its_bag_size(self):
        body = self.add("feed", name="Grower 28%", bag_size="30", default_price="1500").json()
        self.assertEqual(Decimal(body["extra"]["bag_kg"]), Decimal("30"))
        self.assertEqual(Decimal(body["extra"]["price"]), Decimal("1500"))

    def test_a_new_fish_hands_back_its_unit(self):
        self.assertTrue(self.add("species", name="Pangas Two").json()["extra"]["unit"])

    def test_a_person_can_be_both_buyer_and_supplier(self):
        from apps.business.parties.models import Party

        self.add("party", name="Two Ways", role="both")
        p = Party.objects.get(business=self.b, name="Two Ways")
        self.assertTrue(p.is_buyer and p.is_supplier)

    def test_a_new_pond_starts_empty_with_its_unit(self):
        self.add("pond", name="Quick Pond", area="50")
        pond = Pond.objects.get(business=self.b, name="Quick Pond")
        self.assertEqual(pond.status, "empty")
        self.assertEqual(pond.area_unit.symbol, "dec")

    def test_an_existing_name_is_selected_instead_of_duplicated(self):
        self.add("market", name="Jessore Aarot")
        r = self.add("market", name="jessore aarot")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])

    def test_staff_cannot_add_what_their_role_forbids(self):
        self.client.force_login(self.staff)          # data entry: no manage_settings
        self.assertEqual(self.add("pond", name="Sneaky Pond").status_code, 403)
        self.assertFalse(Pond.objects.filter(name="Sneaky Pond").exists())

    def test_an_unknown_kind_is_404(self):
        self.assertEqual(self.client.post(reverse("business:quick_add", args=["nonsense"])).status_code, 404)

    def test_the_plus_is_hidden_when_the_role_cannot_add(self):
        self.client.force_login(self.staff)
        html = self.client.get(reverse("business:transaction_add")).content.decode()
        self.assertNotIn('data-qa="account"', html)   # data entry can't see money


class GuideTests(TestCase):
    def setUp(self):
        self.b, self.owner, self.staff = make_farm()
        self.client.force_login(self.owner)

    def test_the_guide_shows_every_stage(self):
        r = self.client.get(reverse("business:guide"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual([s["number"] for s in r.context["stages"]], [1, 2, 3, 4, 5])
        self.assertTrue(all(s["steps"] for s in r.context["stages"]))

    def test_every_link_in_the_guide_works(self):
        r = self.client.get(reverse("business:guide"))
        for stage in r.context["stages"]:
            for step in stage["steps"]:
                if step["url"]:
                    # 302 is fine: a page may send you somewhere more useful (e.g. bulk
                    # feeding when no cycle is running) — what matters is no 404 or 500.
                    self.assertIn(self.client.get(step["url"]).status_code, (200, 302), step["url"])

    def test_every_feeds_into_points_at_a_real_step(self):
        from apps.business.core.guide import STAGES

        keys = {s.key for stage in STAGES for s in stage.steps}
        for stage in STAGES:
            for step in stage.steps:
                for fed in step.feeds:
                    self.assertIn(fed, keys, f"{step.key} feeds unknown {fed}")

    def test_answers_reference_real_steps(self):
        r = self.client.get(reverse("business:guide"))
        for answer in r.context["answers"]:
            self.assertTrue(answer["from"], answer["question"])

    def test_staff_see_only_what_they_may_do(self):
        self.client.force_login(self.staff)          # data entry only
        r = self.client.get(reverse("business:guide"))
        shown = {s["key"] for stage in r.context["stages"] for s in stage["steps"]}
        self.assertIn("feeding", shown)              # they enter data
        self.assertNotIn("money", shown)             # but not money
        self.assertNotIn("ponds", shown)             # nor settings


class DoubleSubmitTests(TestCase):
    """The guard that stops a second click creating a second record."""

    def setUp(self):
        self.b, self.owner, self.staff = make_farm()
        self.client.force_login(self.owner)

    def test_the_guard_is_on_every_page(self):
        """It lives in the base template, so business and personal pages both have it."""
        for url in (reverse("business:home"), reverse("business:ponds_add"), reverse("creditor_list")):
            html = self.client.get(url).content.decode()
            self.assertIn('form.dataset.submitting', html, url)
            self.assertIn('pageshow', html, url)     # Back button unlocks the form again

    def test_a_form_that_fails_validation_comes_back_usable(self):
        r = self.client.post(reverse("business:ponds_add"), {"name": ""})
        self.assertEqual(r.status_code, 200)
        # no form comes back already marked as "being sent"
        self.assertNotIn('<form data-submitting', r.content.decode())
        self.assertNotIn('data-submitting="1"', r.content.decode())
