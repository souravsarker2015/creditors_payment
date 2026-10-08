"""Farms set up before Family income get its categories (salary, money from
abroad, crops…). New farms get them from seed.py. Only what's missing is
added, so a category someone already made by hand is left alone."""
from django.db import migrations

FAMILY_INCOME = [
    ("Job / salary", "চাকরি / বেতন"),
    ("Money from abroad", "প্রবাসী আয় (রেমিট্যান্স)"),
    ("Crops & farming", "ফসল ও কৃষি"),
    ("Cows, goats & poultry", "গরু-ছাগল ও হাঁস-মুরগি"),
    ("Rent received", "ভাড়া আয়"),
    ("Shop / other business", "দোকান / অন্য ব্যবসা"),
    ("Help from relatives", "আত্মীয়স্বজনের সাহায্য"),
    ("Other family income", "পরিবারের অন্যান্য আয়"),
]


def add_categories(apps, schema_editor):
    Category = apps.get_model("business_finance", "Category")
    seeded = Category.objects.values_list("business_id", flat=True).distinct()
    for business_id in seeded:
        mine = Category.objects.filter(business_id=business_id, type="income", scope="household", parent=None)
        order = max(mine.values_list("order", flat=True), default=0)
        for name, name_bn in FAMILY_INCOME:
            if mine.filter(name__iexact=name).exists():
                continue
            order += 1
            Category.objects.create(business_id=business_id, name=name, name_bn=name_bn, type="income",
                                    scope="household", order=order)


class Migration(migrations.Migration):

    dependencies = [
        ("business_finance", "0003_familymember_transaction_member_and_more"),
    ]

    operations = [
        migrations.RunPython(add_categories, migrations.RunPython.noop),
    ]
