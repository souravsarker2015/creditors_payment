from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import Contributor, ContributorCategory, Contribution


class ContributorCategoryTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="contribuser", password="secret123"
        )
        self.client.force_login(self.user)

        self.family_contributor = Contributor.objects.create(
            user=self.user,
            name="Family Contributor",
            category=ContributorCategory.FAMILY,
        )
        self.ngo_contributor = Contributor.objects.create(
            user=self.user,
            name="NGO Contributor",
            category=ContributorCategory.NGO,
        )

        Contribution.objects.create(
            contributor=self.family_contributor,
            amount=Decimal("1200.00"),
            date=date(2026, 4, 1),
        )
        Contribution.objects.create(
            contributor=self.ngo_contributor,
            amount=Decimal("800.00"),
            date=date(2026, 4, 2),
        )

    def test_contributor_default_category_is_other(self):
        contributor = Contributor.objects.create(user=self.user, name="Default Category")
        self.assertEqual(contributor.category, ContributorCategory.OTHER)

    def test_dashboard_with_include_category_filter(self):
        response = self.client.get(
            reverse("contributor_dashboard"),
            {"category": ContributorCategory.FAMILY, "filter_type": "include"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["filter_type"], "include")
        self.assertEqual(response.context["selected_categories"], [ContributorCategory.FAMILY])
        self.assertEqual(response.context["total_contributors"], 1)
        self.assertEqual(response.context["total_contribution_amount"], Decimal("1200.00"))
        self.assertEqual(response.context["avg_contribution"], Decimal("1200.00"))
        self.assertEqual(response.context["chart_labels"], ["Family Contributor"])

    def test_dashboard_with_exclude_category_filter(self):
        response = self.client.get(
            reverse("contributor_dashboard"),
            {"category": ContributorCategory.FAMILY, "filter_type": "exclude"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["filter_type"], "exclude")
        self.assertEqual(response.context["selected_categories"], [ContributorCategory.FAMILY])
        self.assertEqual(response.context["total_contributors"], 1)
        self.assertEqual(response.context["total_contribution_amount"], Decimal("800.00"))
        self.assertEqual(response.context["avg_contribution"], Decimal("800.00"))
        self.assertEqual(response.context["chart_labels"], ["NGO Contributor"])

    def test_list_with_include_category_filter(self):
        response = self.client.get(
            reverse("contributor_list"),
            {"category": ContributorCategory.NGO, "filter_type": "include"},
        )
        self.assertEqual(response.status_code, 200)
        contributors = list(response.context["contributors"])
        self.assertEqual(len(contributors), 1)
        self.assertEqual(contributors[0].name, "NGO Contributor")
        self.assertEqual(response.context["total_contributors"], 1)
        self.assertEqual(response.context["total_contribution_amount"], Decimal("800.00"))
        self.assertEqual(response.context["avg_contribution"], Decimal("800.00"))

    def test_list_with_multi_category_exclude(self):
        response = self.client.get(
            reverse("contributor_list"),
            [
                ("category", ContributorCategory.FAMILY),
                ("category", ContributorCategory.NGO),
                ("filter_type", "exclude"),
            ],
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_contributors"], 0)
        self.assertEqual(response.context["total_contribution_amount"], Decimal("0"))
        self.assertEqual(response.context["avg_contribution"], 0)
        self.assertEqual(list(response.context["contributors"]), [])
