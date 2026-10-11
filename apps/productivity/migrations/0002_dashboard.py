"""The Productivity dashboard. Like the farm, it's given on purpose: admins
can always open it, and an admin can allow anyone else (People & access)."""
from django.db import migrations

ROW = {"code": "productivity", "name": "Productivity", "name_bn": "প্রোডাক্টিভিটি",
       "description": "Time tracker, tasks, focus timer, notes, snippets and habits",
       "url_name": "work:today", "icon": "bolt", "order": 2, "grant_to_new_users": False, "is_active": True}


def seed(apps, schema_editor):
    apps.get_model("business_core", "Dashboard").objects.update_or_create(code=ROW["code"], defaults=ROW)


def unseed(apps, schema_editor):
    apps.get_model("business_core", "Dashboard").objects.filter(code=ROW["code"]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("productivity", "0001_initial"),
        ("business_core", "0004_personal_starts_at_home"),
    ]
    operations = [migrations.RunPython(seed, unseed)]
