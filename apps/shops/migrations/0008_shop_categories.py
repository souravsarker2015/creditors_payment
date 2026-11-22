"""Shop categories become a list each person keeps (add with +, rename, hide, delete).

Nothing is lost: every user gets the categories the fixed list had, and each
shop is linked to the one it had (PHARMACY -> that user's "Pharmacy").
Going back (migrate shops 0007_transaction_receipt) puts the codes back the same way.

A backup made before this update is brought up to date when it is restored
(apps.core.backup_upgrades), the same way as here.
"""
from functools import partial
from importlib import import_module

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

# The fixed list as it was (code, English name). Frozen here: the migration must not follow later code.
STARTERS = (
    ("GROCERY", "Grocery"), ("PHARMACY", "Pharmacy"), ("VEGETABLE", "Vegetable & Fruit"), ("BAKERY", "Bakery"),
    ("HARDWARE", "Hardware Store"), ("CLOTHING", "Clothing"), ("ELECTRONICS", "Electronics"), ("STATIONERY", "Stationery"),
    ("RESTAURANT", "Restaurant"), ("OTHER", "Other"),
)

# The same steps as the creditors' update (apps/creditors/migrations/0013_creditor_categories.py).
_steps = import_module("apps.creditors.migrations.0013_creditor_categories")
seed_and_link = partial(_steps.seed_and_link, app="shops", person="Shop", category="ShopCategory", starters=STARTERS)
unlink = partial(_steps.unlink, app="shops", person="Shop", starters=STARTERS)


class Migration(migrations.Migration):

    dependencies = [
        ('shops', '0007_transaction_receipt'),
        ('creditors', '0013_creditor_categories'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ShopCategory',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=80, verbose_name='Name')),
                ('code', models.CharField(blank=True, default='', editable=False, max_length=32)),
                ('is_active', models.BooleanField(default=True, verbose_name='In use')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='%(app_label)s_categories', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Shop category',
                'verbose_name_plural': 'Shop categories',
                'ordering': ['name'],
                'abstract': False,
            },
        ),
        migrations.AddConstraint(
            model_name='shopcategory',
            constraint=models.UniqueConstraint(fields=('user', 'name'), name='shop_category_unique_name'),
        ),
        migrations.AddField(
            model_name='shop',
            name='category_ref',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='shops.shopcategory'),
        ),
        migrations.RunPython(seed_and_link, unlink),
        migrations.RemoveField(model_name='shop', name='category'),
        migrations.RenameField(model_name='shop', old_name='category_ref', new_name='category'),
        migrations.AlterField(
            model_name='shop',
            name='category',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='shops', to='shops.shopcategory', verbose_name='Category'),
        ),
    ]
