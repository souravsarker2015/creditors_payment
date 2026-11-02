"""A download must not run in Excel: text that looks like a formula stays text."""
import csv
import io
import zipfile

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from apps.business.core.export import build_zip as farm_zip
from apps.business.core.testing import make_farm
from apps.business.parties.models import Party
from apps.core.csvsafe import safe_cell, safe_writer
from apps.core.my_data import build_zip
from apps.creditors.models import Creditor


class SafeCellTests(SimpleTestCase):
    def test_formulas_become_text(self):
        for bad in ('=HYPERLINK("http://x")', "+1+cmd|' /C calc'!A0", "-2+3+cmd", "@SUM(A1)", "\t=1", "\r=1"):
            self.assertEqual(safe_cell(bad), "'" + bad)

    def test_ordinary_values_stay_as_they_are(self):
        for fine in ("Rahim", "", "+8801712345678", "-500.00", "2026-11-02", "1,50,000", 12, None):
            self.assertEqual(safe_cell(fine), fine)

    def test_the_writer_takes_rows(self):
        out = io.StringIO()
        w = safe_writer(out)
        w.writerow(["=1+1", "ok"])
        w.writerows([["@x"]])
        self.assertEqual(list(csv.reader(io.StringIO(out.getvalue()))), [["'=1+1", "ok"], ["'@x"]])


class DownloadTests(TestCase):
    def test_my_data(self):
        user = get_user_model().objects.create_user("u", password="x")
        Creditor.objects.create(user=user, name="=CMD()")
        data = build_zip(user)
        with zipfile.ZipFile(io.BytesIO(data[0] if isinstance(data, tuple) else data)) as z:
            text = z.read("creditors-creditor.csv").decode("utf-8-sig")
        self.assertIn("'=CMD()", text)

    def test_the_farm_download(self):
        business, _, _ = make_farm()
        Party.objects.create(business=business, name="=CMD()", is_buyer=True)
        data, _ = farm_zip(business)
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            self.assertIn("'=CMD()", z.read("parties-party.csv").decode("utf-8-sig"))
