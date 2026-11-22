"""Contributor categories become a list each person keeps (add with +, rename, hide, delete).

Nothing is lost: every user gets the categories the fixed list had, and each
contributor is linked to the one it had (DONOR -> that user's "Donor").
Going back (migrate contributors 0006_alter_contribution_amount) puts the codes back the same way.

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
    ("FAMILY", "Family"), ("FRIEND", "Friend"), ("BUSINESS_PARTNER", "Business Partner"), ("ORGANIZATION", "Organization"),
    ("NGO", "NGO"), ("SPONSOR", "Sponsor"), ("DONOR", "Donor"), ("INVESTOR", "Investor"),
    ("ALUMNI", "Alumni"), ("COMMUNITY", "Community"), ("RELATIVE", "Relative"), ("OTHER", "Other"),
)

# The same steps as the creditors' update (apps/creditors/migrations/0013_creditor_categories.py).
_steps = import_module("apps.creditors.migrations.0013_creditor_categories")
seed_and_link = partial(_steps.seed_and_link, app="contributors", person="Contributor", category="ContributorCategory", starters=STARTERS)
unlink = partial(_steps.unlink, app="contributors", person="Contributor", starters=STARTERS)


class Migration(migrations.Migration):

    dependencies = [
        ('contributors', '0006_alter_contribution_amount'),
        ('creditors', '0013_creditor_categories'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ContributorCategory',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=80, verbose_name='Name')),
                ('code', models.CharField(blank=True, default='', editable=False, max_length=32)),
                ('is_active', models.BooleanField(default=True, verbose_name='In use')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='%(app_label)s_categories', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Contributor category',
                'verbose_name_plural': 'Contributor categories',
                'ordering': ['name'],
                'abstract': False,
            },
        ),
        migrations.AddConstraint(
            model_name='contributorcategory',
            constraint=models.UniqueConstraint(fields=('user', 'name'), name='contributor_category_unique_name'),
        ),
        migrations.AddField(
            model_name='contributor',
            name='category_ref',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='contributors.contributorcategory'),
        ),
        migrations.RunPython(seed_and_link, unlink),
        migrations.RemoveField(model_name='contributor', name='category'),
        migrations.RenameField(model_name='contributor', old_name='category_ref', new_name='category'),
        migrations.AlterField(
            model_name='contributor',
            name='category',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='contributors', to='contributors.contributorcategory', verbose_name='Category'),
        ),
    ]
