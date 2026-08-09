from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Shop, ShopCategory, Transaction


class ShopCategoryTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="shopuser", password="secret123")
        self.client.force_login(self.user)

        self.grocery_shop = Shop.objects.create(
            user=self.user,
            name="Rahim General Store",
            category=ShopCategory.GROCERY,
        )
        self.pharmacy_shop = Shop.objects.create(
            user=self.user,
            name="City Pharmacy",
            category=ShopCategory.PHARMACY,
        )

        Transaction.objects.create(
            shop=self.grocery_shop,
            transaction_type=Transaction.PURCHASE,
            amount=Decimal("1000.00"),
            date=date(2026, 4, 1),
        )
        Transaction.objects.create(
            shop=self.grocery_shop,
            transaction_type=Transaction.PAYMENT,
            amount=Decimal("200.00"),
            date=date(2026, 4, 2),
        )
        Transaction.objects.create(
            shop=self.pharmacy_shop,
            transaction_type=Transaction.PURCHASE,
            amount=Decimal("500.00"),
            date=date(2026, 4, 3),
        )
        Transaction.objects.create(
            shop=self.pharmacy_shop,
            transaction_type=Transaction.PAYMENT,
            amount=Decimal("100.00"),
            date=date(2026, 4, 4),
        )

    def test_shop_default_category_is_other(self):
        shop = Shop.objects.create(user=self.user, name="Default Category Shop")
        self.assertEqual(shop.category, ShopCategory.OTHER)

    def test_shop_remaining_and_is_paid(self):
        self.assertEqual(self.grocery_shop.total_due, Decimal("1000.00"))
        self.assertEqual(self.grocery_shop.total_paid, Decimal("200.00"))
        self.assertEqual(self.grocery_shop.remaining, Decimal("800.00"))
        self.assertFalse(self.grocery_shop.is_paid)

    def test_shop_with_no_transactions_is_paid(self):
        shop = Shop.objects.create(user=self.user, name="New Shop")
        self.assertEqual(shop.remaining, 0)
        self.assertTrue(shop.is_paid)

    def test_dashboard_without_category_is_unfiltered(self):
        response = self.client.get(reverse("shop_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_due"], Decimal("1500.00"))
        self.assertEqual(response.context["total_paid"], Decimal("300.00"))
        self.assertEqual(response.context["remaining"], Decimal("1200.00"))
        self.assertCountEqual(
            response.context["shop_labels"], ["Rahim General Store", "City Pharmacy"]
        )
        self.assertEqual(len(response.context["recent_transactions"]), 4)

    def test_dashboard_with_exclude_category_filter(self):
        response = self.client.get(
            reverse("shop_dashboard"),
            {"category": ShopCategory.GROCERY, "filter_type": "exclude"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_due"], Decimal("500.00"))
        self.assertEqual(response.context["total_paid"], Decimal("100.00"))
        self.assertEqual(response.context["shop_labels"], ["City Pharmacy"])

    def test_shop_list_with_include_category_filter(self):
        response = self.client.get(
            reverse("shop_list"), {"category": ShopCategory.GROCERY, "filter_type": "include"}
        )
        self.assertEqual(response.status_code, 200)
        shops = list(response.context["page_obj"])
        self.assertEqual(len(shops), 1)
        self.assertEqual(shops[0].name, "Rahim General Store")

    def test_shop_list_search_by_name_is_case_insensitive(self):
        response = self.client.get(reverse("shop_list"), {"q": "pharmacy"})
        self.assertEqual(response.status_code, 200)
        shops = list(response.context["page_obj"])
        self.assertEqual([s.name for s in shops], ["City Pharmacy"])

    def test_shop_list_search_combines_with_category_filter(self):
        response = self.client.get(
            reverse("shop_list"), {"q": "pharmacy", "category": ShopCategory.GROCERY}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["page_obj"]), [])

    def test_shop_list_payment_status_paid_filter(self):
        paid_shop = Shop.objects.create(user=self.user, name="Fully Paid Shop")
        Transaction.objects.create(
            shop=paid_shop,
            transaction_type=Transaction.PURCHASE,
            amount=Decimal("400.00"),
            date=date(2026, 4, 5),
        )
        Transaction.objects.create(
            shop=paid_shop,
            transaction_type=Transaction.PAYMENT,
            amount=Decimal("400.00"),
            date=date(2026, 4, 6),
        )

        response = self.client.get(reverse("shop_list"), {"payment_status": "PAID"})
        self.assertEqual(response.status_code, 200)
        shops = list(response.context["page_obj"])
        self.assertEqual([s.name for s in shops], ["Fully Paid Shop"])

    def test_shop_list_payment_status_unpaid_filter(self):
        paid_shop = Shop.objects.create(user=self.user, name="Fully Paid Shop")
        Transaction.objects.create(
            shop=paid_shop,
            transaction_type=Transaction.PURCHASE,
            amount=Decimal("400.00"),
            date=date(2026, 4, 5),
        )
        Transaction.objects.create(
            shop=paid_shop,
            transaction_type=Transaction.PAYMENT,
            amount=Decimal("400.00"),
            date=date(2026, 4, 6),
        )

        response = self.client.get(reverse("shop_list"), {"payment_status": "UNPAID"})
        self.assertEqual(response.status_code, 200)
        shops = list(response.context["page_obj"])
        self.assertCountEqual(
            [s.name for s in shops], ["Rahim General Store", "City Pharmacy"]
        )

    def test_shop_list_payment_status_is_independent_of_category_filter_type(self):
        """Regression test: payment_status must not be silently flipped by the
        category include/exclude toggle (`filter_type`)."""
        paid_shop = Shop.objects.create(
            user=self.user, name="Fully Paid Shop", category=ShopCategory.GROCERY
        )
        Transaction.objects.create(
            shop=paid_shop,
            transaction_type=Transaction.PURCHASE,
            amount=Decimal("400.00"),
            date=date(2026, 4, 5),
        )
        Transaction.objects.create(
            shop=paid_shop,
            transaction_type=Transaction.PAYMENT,
            amount=Decimal("400.00"),
            date=date(2026, 4, 6),
        )

        response = self.client.get(
            reverse("shop_list"),
            {
                "payment_status": "PAID",
                "category": ShopCategory.PHARMACY,
                "filter_type": "exclude",
            },
        )
        self.assertEqual(response.status_code, 200)
        shops = list(response.context["page_obj"])
        # City Pharmacy is excluded by category; of the remaining shops, only
        # the fully-paid one should show up for payment_status=PAID.
        self.assertEqual([s.name for s in shops], ["Fully Paid Shop"])

    def test_shop_list_pagination(self):
        for i in range(15):
            Shop.objects.create(user=self.user, name=f"Extra Shop {i:02d}")

        response = self.client.get(reverse("shop_list"))
        self.assertEqual(response.status_code, 200)
        page_obj = response.context["page_obj"]
        self.assertEqual(page_obj.paginator.num_pages, 2)
        self.assertEqual(len(list(page_obj)), 9)

        response_page_2 = self.client.get(reverse("shop_list"), {"page": 2})
        self.assertEqual(response_page_2.status_code, 200)
        self.assertEqual(len(list(response_page_2.context["page_obj"])), 8)

    def test_shop_detail_add_transaction(self):
        response = self.client.post(
            reverse("shop_detail", args=[self.grocery_shop.pk]),
            {
                "transaction_type": Transaction.PURCHASE,
                "amount": "150.00",
                "date": "2026-04-10",
                "note": "Rice and oil",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            Transaction.objects.filter(
                shop=self.grocery_shop, amount=Decimal("150.00"), note="Rice and oil"
            ).exists()
        )

    def test_shop_scoped_to_owning_user(self):
        other_user = User.objects.create_user(username="othershop", password="secret123")
        other_shop = Shop.objects.create(user=other_user, name="Someone Else's Shop")
        response = self.client.get(reverse("shop_detail", args=[other_shop.pk]))
        self.assertEqual(response.status_code, 404)


class ShopDueDateTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="shop_duedate_user", password="secret123")
        self.today = timezone.now().date()

    def _shop_with_balance(self, due_date=None, purchased=Decimal("500.00"), paid=Decimal("0.00")):
        shop = Shop.objects.create(
            user=self.user, name="Test Shop", category=ShopCategory.GROCERY, due_date=due_date
        )
        Transaction.objects.create(
            shop=shop, transaction_type=Transaction.PURCHASE, amount=purchased, date=self.today - timedelta(days=30)
        )
        if paid > 0:
            Transaction.objects.create(
                shop=shop, transaction_type=Transaction.PAYMENT, amount=paid, date=self.today - timedelta(days=1)
            )
        return shop

    def test_is_overdue_true_when_due_date_passed_and_unpaid(self):
        shop = self._shop_with_balance(due_date=self.today - timedelta(days=3))
        self.assertTrue(shop.is_overdue)
        self.assertFalse(shop.is_due_soon)

    def test_is_due_soon_true_within_window_not_yet_overdue(self):
        shop = self._shop_with_balance(due_date=self.today + timedelta(days=3))
        self.assertFalse(shop.is_overdue)
        self.assertTrue(shop.is_due_soon)

    def test_is_due_soon_false_beyond_window(self):
        shop = self._shop_with_balance(due_date=self.today + timedelta(days=30))
        self.assertFalse(shop.is_overdue)
        self.assertFalse(shop.is_due_soon)

    def test_fully_paid_balance_never_shows_overdue_even_with_past_due_date(self):
        shop = self._shop_with_balance(
            due_date=self.today - timedelta(days=10), purchased=Decimal("200.00"), paid=Decimal("200.00")
        )
        self.assertFalse(shop.is_overdue)
        self.assertFalse(shop.is_due_soon)

    def test_no_due_date_never_flagged(self):
        shop = self._shop_with_balance(due_date=None)
        self.assertFalse(shop.is_overdue)
        self.assertFalse(shop.is_due_soon)
