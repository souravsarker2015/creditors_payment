"""The farm's "Download all records": every kind of farm record, and the farm's own settings, each a sheet
with every row — so a table added by a new feature is in it by itself."""
import csv
import io
import zipfile

from django.apps import apps
from django.test import TestCase

from apps.core.backup_testing import fill_every_table

from ..export import build_zip, farm_models
from ..testing import make_farm


class FarmDownloadTests(TestCase):
    def test_every_farm_table_with_every_row(self):
        b, owner, _staff = make_farm()
        self.assertEqual(fill_every_table(owner, b), [])
        data, made = build_zip(b)
        z = zipfile.ZipFile(io.BytesIO(data))
        sheets = dict(made)
        included = set(farm_models())
        left_out = sorted(m._meta.label_lower for m in apps.get_models()
                          if m.__module__.startswith("apps.business.") and m._meta.app_label != "business_core" and m not in included)
        self.assertEqual(left_out, [], "farm tables the download doesn't reach")
        for m in included:
            rows = m.objects.filter(business=b).count()
            name = f"{m._meta.app_label.replace('business_', '')}-{m._meta.model_name}.csv"
            if not rows:
                continue
            self.assertIn(name, sheets, m._meta.label_lower)
            lines = list(csv.reader(io.StringIO(z.read(name).decode("utf-8-sig"))))
            self.assertEqual(len(lines) - 1, rows, m._meta.label_lower)
        self.assertIn("ponds-pondalerts.csv", sheets)          # the farm's warning levels, its own settings
