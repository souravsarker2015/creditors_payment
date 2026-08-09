from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import HouseholdCategory, HouseholdMember, Purchase, Settlement


class PurchaseModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="bazaruser", password="secret123")

    def test_purchase_can_be_created_without_buyer_or_category(self):
        purchase = Purchase.objects.create(
            user=self.user,
            amount=Decimal("150.00"),
            date=date(2026, 8, 1),
        )
        self.assertIsNone(purchase.buyer)
        self.assertIsNone(purchase.category)
        self.assertEqual(purchase.description, "")

    def test_member_balance_due_reflects_purchases_minus_settlements(self):
        member = HouseholdMember.objects.create(user=self.user, name="Rahim")
        Purchase.objects.create(user=self.user, buyer=member, amount=Decimal("500.00"), date=date(2026, 8, 1))
        Purchase.objects.create(user=self.user, buyer=member, amount=Decimal("300.00"), date=date(2026, 8, 2))
        Settlement.objects.create(member=member, amount=Decimal("400.00"), date=date(2026, 8, 3))

        self.assertEqual(member.total_spent, Decimal("800.00"))
        self.assertEqual(member.total_settled, Decimal("400.00"))
        self.assertEqual(member.balance_due, Decimal("400.00"))
        self.assertFalse(member.is_settled)

    def test_member_with_no_purchases_is_settled(self):
        member = HouseholdMember.objects.create(user=self.user, name="Karim")
        self.assertEqual(member.balance_due, 0)
        self.assertTrue(member.is_settled)


class HouseholdViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="bazarview", password="secret123")
        self.client.force_login(self.user)

        self.category = HouseholdCategory.objects.create(user=self.user, name="Vegetables")
        self.member = HouseholdMember.objects.create(user=self.user, name="Salma")

        Purchase.objects.create(
            user=self.user,
            category=self.category,
            buyer=self.member,
            amount=Decimal("200.00"),
            date=date(2026, 8, 1),
            description="Potatoes and onions",
        )
        Purchase.objects.create(
            user=self.user,
            amount=Decimal("120.00"),
            date=date(2026, 7, 15),
        )

    def test_dashboard_loads(self):
        response = self.client.get(reverse("household_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_spent"], Decimal("320.00"))

    def test_purchase_list_groups_purchases_by_month(self):
        response = self.client.get(reverse("household_list"))
        self.assertEqual(response.status_code, 200)
        months = list(response.context["page_obj"])
        self.assertEqual(len(months), 2)
        totals = {m["month"].month: m["total"] for m in months}
        self.assertEqual(totals[8], Decimal("200.00"))
        self.assertEqual(totals[7], Decimal("120.00"))

    def test_month_detail_shows_only_that_months_purchases(self):
        response = self.client.get(reverse("household_month_detail", args=[2026, 8]))
        self.assertEqual(response.status_code, 200)
        purchases = list(response.context["purchases"])
        self.assertEqual(len(purchases), 1)
        self.assertEqual(purchases[0].amount, Decimal("200.00"))

    def test_month_detail_invalid_month_returns_404(self):
        response = self.client.get(reverse("household_month_detail", args=[2026, 13]))
        self.assertEqual(response.status_code, 404)

    def test_can_add_purchase_via_month_detail_post(self):
        response = self.client.post(
            reverse("household_month_detail", args=[2026, 8]),
            {
                "amount": "75.00",
                "date": "2026-08-10",
                "category": "",
                "buyer": "",
                "description": "Fish",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            Purchase.objects.filter(user=self.user, amount=Decimal("75.00"), description="Fish").exists()
        )

    def test_purchase_scoped_to_owning_user(self):
        other_user = User.objects.create_user(username="otherbazar", password="secret123")
        other_purchase = Purchase.objects.create(
            user=other_user, amount=Decimal("999.00"), date=date(2026, 8, 5)
        )
        response = self.client.get(reverse("household_purchase_edit", args=[other_purchase.pk]))
        self.assertEqual(response.status_code, 404)

    def test_member_list_shows_balance_due(self):
        Settlement.objects.create(member=self.member, amount=Decimal("50.00"), date=date(2026, 8, 2))
        response = self.client.get(reverse("household_member_list"))
        self.assertEqual(response.status_code, 200)
        members = {m.name: m for m in response.context["page_obj"]}
        self.assertEqual(members["Salma"].balance_due, Decimal("150.00"))

    def test_can_settle_member_via_detail_post(self):
        response = self.client.post(
            reverse("household_member_detail", args=[self.member.pk]),
            {"amount": "200.00", "date": "2026-08-05", "note": "Paid back in cash"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self.member.is_settled)

    def test_category_list_shows_total_spent(self):
        response = self.client.get(reverse("household_category_list"))
        self.assertEqual(response.status_code, 200)
        categories = {c["name"]: c for c in response.context["categories"]}
        self.assertEqual(categories["Vegetables"]["total_amt"], Decimal("200.00"))
