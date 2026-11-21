"""Debtor categories become a list each person keeps (add with +, rename, hide, delete).

Nothing is lost: every user gets the twelve categories the fixed list had, and
each debtor is linked to the one it had (CLIENT -> that user's "Client").
Going back (migrate debtors 0008) puts the codes back the same way.

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
    ("FAMILY", "Family"), ("FRIEND", "Friend"), ("BUSINESS_PARTNER", "Business Partner"), ("CLIENT", "Client"),
    ("EMPLOYEE", "Employee"), ("TENANT", "Tenant"), ("SHOPKEEPER", "Shopkeeper"), ("SUPPLIER", "Supplier"),
    ("STUDENT", "Student"), ("MEDICAL", "Medical"), ("EDUCATION", "Education"), ("OTHER", "Other"),
)

# The same steps as the creditors' update (apps/creditors/migrations/0013_creditor_categories.py).
_steps = import_module("apps.creditors.migrations.0013_creditor_categories")
seed_and_link = partial(_steps.seed_and_link, app="debtors", person="Debtor", category="DebtorCategory", starters=STARTERS)
unlink = partial(_steps.unlink, app="debtors", person="Debtor", starters=STARTERS)


class Migration(migrations.Migration):

    dependencies = [
        ('debtors', '0008_transaction_receipt'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='DebtorCategory',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=80, verbose_name='Name')),
                ('code', models.CharField(blank=True, default='', editable=False, max_length=32)),
                ('is_active', models.BooleanField(default=True, verbose_name='In use')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='%(app_label)s_categories', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Debtor category',
                'verbose_name_plural': 'Debtor categories',
                'ordering': ['name'],
                'abstract': False,
            },
        ),
        migrations.AddConstraint(
            model_name='debtorcategory',
            constraint=models.UniqueConstraint(fields=('user', 'name'), name='debtor_category_unique_name'),
        ),
        migrations.AddField(
            model_name='debtor',
            name='category_ref',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='debtors.debtorcategory'),
        ),
        migrations.RunPython(seed_and_link, unlink),
        migrations.RemoveField(model_name='debtor', name='category'),
        migrations.RenameField(model_name='debtor', old_name='category_ref', new_name='category'),
        migrations.AlterField(
            model_name='debtor',
            name='category',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='debtors', to='debtors.debtorcategory', verbose_name='Category'),
        ),
    ]
