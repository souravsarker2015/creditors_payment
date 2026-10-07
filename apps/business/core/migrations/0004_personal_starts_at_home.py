"""The personal dashboard now opens on Home (money at a glance) instead of
the creditors overview."""
from django.db import migrations


def to_home(apps, schema_editor):
    apps.get_model("business_core", "Dashboard").objects.filter(code="personal", url_name="dashboard").update(url_name="home")


def to_creditors(apps, schema_editor):
    apps.get_model("business_core", "Dashboard").objects.filter(code="personal", url_name="home").update(url_name="dashboard")


class Migration(migrations.Migration):
    dependencies = [("business_core", "0003_membership_account_created")]
    operations = [migrations.RunPython(to_home, to_creditors)]
