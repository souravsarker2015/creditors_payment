"""An address someone else can put in a link (?next=, a form's next) only ever leads back to this site."""
from datetime import date
from decimal import Decimal as D

from django.test import RequestFactory, SimpleTestCase, TestCase
from django.urls import reverse

from apps.business.core.testing import make_farm
from apps.business.finance.models import Category, CategoryType, RecurringTransaction, Scope

from ..nav import back_to

BAD = ("https://evil.example/", "//evil.example/", "javascript:alert(1)", "/\\evil.example")


class BackToTests(SimpleTestCase):
    def test_only_this_site(self):
        request = RequestFactory().get("/")
        for url in BAD:
            self.assertEqual(back_to(request, url, "/home/"), "/home/", url)
        self.assertEqual(back_to(request, "/creditors/1/?tab=a", "/home/"), "/creditors/1/?tab=a")
        self.assertEqual(back_to(request, "", "/home/"), "/home/")


class ViewsTests(TestCase):
    def setUp(self):
        self.b, self.owner, self.staff = make_farm()
        self.client.force_login(self.owner)

    def test_preferences(self):
        for url in BAD:
            r = self.client.post(reverse("update_preferences"), {"language": "en", "next": url})
            self.assertEqual(r["Location"], reverse("home"), url)
        r = self.client.post(reverse("update_preferences"), {"language": "en"}, HTTP_REFERER="https://evil.example/")
        self.assertEqual(r["Location"], reverse("home"))
        r = self.client.post(reverse("update_preferences"), {"language": "en", "next": "/creditors/"})
        self.assertEqual(r["Location"], "/creditors/")

    def test_the_back_link_of_a_payment_and_an_advance(self):
        for name in ("business:payment_add", "business:advance_add"):
            page = self.client.get(reverse(name), {"next": "javascript:alert(1)"})
            self.assertEqual(page.status_code, 200)
            self.assertNotContains(page, "javascript:alert")

    def test_skipping_a_bill(self):
        category = Category.objects.create(business=self.b, name="Rent", type=CategoryType.EXPENSE, scope=Scope.BUSINESS)
        bill = RecurringTransaction.objects.create(business=self.b, name="Rent", category=category, amount=D("10"), start_date=date.today())
        r = self.client.post(reverse("business:recurring_skip", args=[bill.pk]), {"next": "https://evil.example/"})
        self.assertEqual(r["Location"], reverse("business:recurring"))

    def test_bulk_change_of_questions(self):
        r = self.client.post(reverse("work:questions"), {"bulk": "1", "next": "//evil.example/"})
        self.assertNotIn("evil", r.get("Location", ""))


class ChartTests(SimpleTestCase):
    def test_a_category_name_cant_end_the_script(self):
        from django.template import Context, Template

        out = Template('{{ labels|json_script:"x" }}').render(Context({"labels": ["</script><script>alert(1)</script>"]}))
        self.assertNotIn("<script>alert", out)
