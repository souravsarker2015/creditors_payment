"""Seed the two dashboards and keep every existing user exactly where they were:
each current user gets the personal dashboard as their default. The business
dashboard is given only on purpose (by an admin, or by being added to a team)."""
from django.conf import settings
from django.db import migrations

DASHBOARDS = [
    {"code": "personal", "name": "Personal & Home", "name_bn": "ব্যক্তিগত ও সংসার",
     "description": "Loans, dues, income, expenses, bazar, budgets and savings",
     "url_name": "dashboard", "icon": "wallet", "order": 0, "grant_to_new_users": True},
    {"code": "business", "name": "Fish Farm Business", "name_bn": "মাছের খামার ব্যবসা",
     "description": "Ponds, feed, sales, credit (baki) and farm accounts",
     "url_name": "business:home", "icon": "fish", "order": 1, "grant_to_new_users": False},
]


def seed(apps, schema_editor):
    Dashboard = apps.get_model("business_core", "Dashboard")
    Access = apps.get_model("business_core", "UserDashboardAccess")
    User = apps.get_model(*settings.AUTH_USER_MODEL.split("."))
    for row in DASHBOARDS:
        Dashboard.objects.update_or_create(code=row["code"], defaults=row)
    personal = Dashboard.objects.get(code="personal")
    Access.objects.bulk_create(
        [Access(user_id=uid, dashboard=personal, is_default=True) for uid in User.objects.values_list("pk", flat=True)],
        ignore_conflicts=True,
    )


def unseed(apps, schema_editor):
    apps.get_model("business_core", "Dashboard").objects.filter(code__in=[d["code"] for d in DASHBOARDS]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("business_core", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [migrations.RunPython(seed, unseed)]
