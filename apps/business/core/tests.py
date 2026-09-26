from decimal import Decimal

from django.contrib.auth.models import User
from django.template import Context, Template
from django.test import TestCase
from django.urls import reverse

from .access import create_business
from .models import AuditLog, Dashboard, Membership, Role, Unit, UserDashboardAccess
from .templatetags.business import bdt, group_bd, num
from .units import ConversionError, convert, seed_units, to_base


def grant(user, code, default=False):
    return UserDashboardAccess.objects.create(user=user, dashboard=Dashboard.objects.get(code=code), is_default=default)


class ExistingUsersUnaffectedTests(TestCase):
    """The business module must not change anything for today's users."""

    def test_new_users_get_personal_as_default_and_nothing_else(self):
        u = User.objects.create_user("alice", password="pw12345!")
        self.assertEqual(list(u.dashboard_access.values_list("dashboard__code", "is_default")), [("personal", True)])

    def test_login_still_lands_on_creditors_dashboard(self):
        User.objects.create_user("alice", password="pw12345!")
        r = self.client.post(reverse("login"), {"username": "alice", "password": "pw12345!"}, follow=True)
        self.assertEqual(r.redirect_chain[-1][0], reverse("dashboard"))
        self.assertEqual(r.status_code, 200)

    def test_personal_pages_and_topbar_unchanged(self):
        User.objects.create_user("alice", password="pw12345!")
        self.client.login(username="alice", password="pw12345!")
        for name in ["dashboard", "networth", "expense_dashboard", "goal_list"]:
            r = self.client.get(reverse(name))
            self.assertEqual(r.status_code, 200, name)
            self.assertNotContains(r, "dash-switch")  # only one dashboard → no switcher

    def test_business_is_403_without_access(self):
        User.objects.create_user("alice", password="pw12345!")
        self.client.login(username="alice", password="pw12345!")
        r = self.client.get(reverse("business:home"))
        self.assertEqual(r.status_code, 403)
        self.assertContains(r, "business dashboard", status_code=403)


class SwitchingAndDefaultsTests(TestCase):
    def setUp(self):
        self.u = User.objects.create_user("owner", password="pw12345!")
        grant(self.u, "business")
        self.client.login(username="owner", password="pw12345!")

    def test_first_visit_asks_to_set_up_the_farm_then_seeds_units(self):
        self.assertRedirects(self.client.get(reverse("business:home")), reverse("business:setup"))
        r = self.client.post(reverse("business:setup"), {"name": "Rahman Fish Farm", "mon_kg": "37.5"}, follow=True)
        self.assertContains(r, "Rahman Fish Farm")
        m = Membership.objects.get(user=self.u)
        self.assertEqual(m.role, Role.OWNER)
        self.assertEqual(Unit.objects.get(business=m.business, symbol="mon").factor, Decimal("37.5"))
        self.assertTrue(Unit.objects.filter(business=m.business, symbol="bigha").exists())

    def test_switcher_shows_with_two_dashboards_and_default_redirects_after_login(self):
        create_business(self.u, "Farm")
        r = self.client.get(reverse("dashboard"))
        self.assertContains(r, "dash-switch")
        self.client.post(reverse("business:default_dashboard"), {"dashboard": "business", "next": "/"})
        self.client.logout()
        r = self.client.post(reverse("login"), {"username": "owner", "password": "pw12345!"}, follow=True)
        self.assertEqual(r.redirect_chain[-1][0], reverse("business:home"))
        # …but only right after login: visiting personal pages afterwards works normally
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)

    def test_staff_without_personal_access_are_kept_in_the_business_area(self):
        staff = User.objects.create_user("staff", password="pw12345!")
        UserDashboardAccess.objects.filter(user=staff).delete()
        grant(staff, "business", default=True)
        self.client.login(username="staff", password="pw12345!")
        self.assertRedirects(self.client.get(reverse("networth")), reverse("business:home"), fetch_redirect_response=False)
        self.assertRedirects(self.client.get(reverse("expense_list")), reverse("business:home"), fetch_redirect_response=False)
        # account pages still work
        self.assertEqual(self.client.get(reverse("logout")).status_code, 302)

    def test_no_dashboards_at_all_gets_a_friendly_page(self):
        nobody = User.objects.create_user("nobody", password="pw12345!")
        UserDashboardAccess.objects.filter(user=nobody).delete()
        self.client.login(username="nobody", password="pw12345!")
        self.assertContains(self.client.get(reverse("dashboard")), "No dashboards", status_code=403)


class RolesTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("owner", password="pw12345!")
        grant(self.owner, "business")
        self.biz = create_business(self.owner, "Farm")
        self.staff = User.objects.create_user("staff", password="pw12345!")

    def add(self, role):
        grant(self.staff, "business")
        return Membership.objects.create(business=self.biz, user=self.staff, role=role)

    def test_owner_adds_staff_which_grants_the_dashboard(self):
        self.client.login(username="owner", password="pw12345!")
        self.client.post(reverse("business:team"), {"username": "STAFF", "role": "data_entry"})
        self.assertTrue(Membership.objects.filter(business=self.biz, user=self.staff, role="data_entry").exists())
        self.assertTrue(UserDashboardAccess.objects.filter(user=self.staff, dashboard__code="business").exists())

    def test_data_entry_cannot_open_settings_or_team(self):
        self.add(Role.DATA_ENTRY)
        self.client.login(username="staff", password="pw12345!")
        self.assertEqual(self.client.get(reverse("business:home")).status_code, 200)
        self.assertEqual(self.client.get(reverse("business:units")).status_code, 200)       # can read units
        for name in ["business:team", "business:profile", "business:activity", "business:unit_add"]:
            self.assertEqual(self.client.get(reverse(name)).status_code, 403, name)
        unit = Unit.objects.get(business=self.biz, symbol="mon")
        self.assertEqual(self.client.post(reverse("business:unit_delete", args=[unit.pk])).status_code, 403)

    def test_owner_cannot_be_demoted_or_removed(self):
        self.client.login(username="owner", password="pw12345!")
        m = Membership.objects.get(user=self.owner)
        self.client.post(reverse("business:member_role", args=[m.pk]), {"role": "viewer"})
        self.client.post(reverse("business:member_remove", args=[m.pk]))
        m.refresh_from_db()
        self.assertEqual(m.role, Role.OWNER)

    def test_other_business_records_are_invisible(self):
        other = User.objects.create_user("other", password="pw12345!")
        theirs = create_business(other, "Their Farm")
        self.client.login(username="owner", password="pw12345!")
        their_unit = Unit.objects.get(business=theirs, symbol="mon")
        self.assertEqual(self.client.get(reverse("business:unit_edit", args=[their_unit.pk])).status_code, 404)
        their_member = Membership.objects.get(business=theirs)
        self.assertEqual(self.client.post(reverse("business:member_remove", args=[their_member.pk])).status_code, 404)

    def test_access_admin_is_staff_only_and_updates_grants(self):
        self.client.login(username="owner", password="pw12345!")
        self.assertEqual(self.client.get(reverse("business:access_admin")).status_code, 302)  # to login
        admin = User.objects.create_superuser("root", password="pw12345!")
        self.client.login(username="root", password="pw12345!")
        self.assertContains(self.client.get(reverse("business:access_admin")), "staff")
        self.client.post(reverse("business:access_update", args=[self.staff.pk]), {"dashboards": ["business"], "default": "business"})
        self.assertEqual(list(self.staff.dashboard_access.values_list("dashboard__code", "is_default")), [("business", True)])


class UnitTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("owner", password="pw12345!")
        grant(self.owner, "business")
        self.biz = create_business(self.owner, "Farm")
        self.u = {u.symbol: u for u in Unit.objects.filter(business=self.biz)}

    def test_conversions(self):
        self.assertEqual(convert(5, self.u["mon"], self.u["kg"]), Decimal("200"))
        self.assertEqual(convert(100, self.u["kg"], self.u["mon"]), Decimal("2.5"))
        self.assertEqual(convert(2, self.u["bigha"], self.u["dec"]), Decimal("66"))
        self.assertEqual(to_base(3, self.u["hali"]), Decimal("12"))
        with self.assertRaises(ConversionError):
            convert(1, self.u["kg"], self.u["pcs"])

    def test_seed_is_idempotent_and_keeps_edits(self):
        mon = self.u["mon"]
        mon.factor = Decimal("37.32")
        mon.save()
        self.assertEqual(seed_units(self.biz), 0)
        mon.refresh_from_db()
        self.assertEqual(mon.factor, Decimal("37.32"))

    def test_add_edit_soft_delete_restore_through_the_ui_with_audit(self):
        self.client.login(username="owner", password="pw12345!")
        self.client.post(reverse("business:unit_add"), {"name": "Seer", "name_bn": "সের", "symbol": "seer", "unit_type": "weight", "factor": "0.933", "notes": ""})
        seer = Unit.objects.get(business=self.biz, symbol="seer")
        self.assertFalse(seer.is_base)
        self.assertEqual(seer.created_by, self.owner)
        dup = self.client.post(reverse("business:unit_add"), {"name": "X", "symbol": "SEER", "unit_type": "weight", "factor": "1"})
        self.assertIn("symbol", dup.context["form"].errors)
        self.client.post(reverse("business:unit_edit", args=[self.u["mon"].pk]), {"name": "Mon", "name_bn": "মণ", "symbol": "mon", "factor": "38", "notes": ""})
        self.client.post(reverse("business:unit_delete", args=[seer.pk]))
        self.assertFalse(Unit.objects.filter(pk=seer.pk).exists())
        self.assertTrue(Unit.all_objects.filter(pk=seer.pk, is_deleted=True).exists())
        self.client.post(reverse("business:unit_restore", args=[seer.pk]))
        self.assertTrue(Unit.objects.filter(pk=seer.pk).exists())
        actions = list(AuditLog.objects.filter(business=self.biz, object_repr__in=["Seer", "Mon"]).values_list("action", flat=True))
        for a in ("create", "update", "delete", "restore"):
            self.assertIn(a, actions)
        change = AuditLog.objects.get(business=self.biz, action="update", object_id=str(self.u["mon"].pk))
        self.assertEqual(change.changes["factor"], ["40.000000", "38"])
        self.assertEqual(change.user, self.owner)

    def test_base_unit_is_protected(self):
        self.client.login(username="owner", password="pw12345!")
        kg = self.u["kg"]
        self.client.post(reverse("business:unit_delete", args=[kg.pk]))
        self.client.post(reverse("business:unit_edit", args=[kg.pk]), {"name": "Kilo", "symbol": "kg", "factor": "5", "unit_type": "count"})
        kg.refresh_from_db()
        self.assertEqual((kg.is_deleted, kg.factor, kg.unit_type, kg.name), (False, 1, "weight", "Kilo"))


class FormattingTests(TestCase):
    def test_bangladeshi_grouping(self):
        self.assertEqual(group_bd("125000"), "1,25,000")
        self.assertEqual(group_bd("12500000"), "1,25,00,000")
        self.assertEqual(group_bd("999"), "999")
        self.assertEqual(bdt(Decimal("125000")), "৳1,25,000")
        self.assertEqual(bdt(Decimal("-1234.5")), "−৳1,234.50")
        self.assertEqual(num(Decimal("1250.500")), "1,250.5")

    def test_qty_shows_the_conversion(self):
        owner = User.objects.create_user("o", password="pw12345!")
        biz = create_business(owner, "Farm")
        mon = Unit.objects.get(business=biz, symbol="mon")
        html = Template("{% load business %}{% qty 5 unit %}").render(Context({"unit": mon}))
        self.assertIn("5 mon", html)
        self.assertIn("= 200 kg", html)


class SeedingIsNotAuditedTests(TestCase):
    def test_starter_units_do_not_flood_the_activity_log(self):
        owner = User.objects.create_user("o", password="pw12345!")
        biz = create_business(owner, "Farm")
        self.assertGreater(Unit.objects.filter(business=biz).count(), 10)
        self.assertFalse(AuditLog.objects.filter(business=biz).exists())


class DeleteBusinessTests(TestCase):
    def test_deleting_a_whole_business_cleans_up(self):
        owner = User.objects.create_user("o", password="pw12345!")
        biz = create_business(owner, "Farm")
        unit = Unit.objects.get(business=biz, symbol="mon")
        unit.name = "Mon!"
        unit.save()                               # leaves an audit row behind
        Unit.all_objects.filter(business=biz, symbol="g").delete()  # a hard delete is logged
        self.assertTrue(AuditLog.objects.filter(business=biz, changes__permanently=[False, True]).exists())
        biz.delete()
        self.assertFalse(Unit.all_objects.filter(business_id=biz.pk).exists())
        self.assertFalse(AuditLog.objects.filter(business_id=biz.pk).exists())

    def test_deleting_businesses_in_bulk(self):
        owner = User.objects.create_user("o", password="pw12345!")
        for name in ("A", "B"):
            b = create_business(owner, name)
            Unit.all_objects.filter(business=b, symbol="g").delete()
        from .models import Business
        Business.objects.all().delete()
        self.assertFalse(Business.objects.exists())
        self.assertFalse(AuditLog.objects.exists())
