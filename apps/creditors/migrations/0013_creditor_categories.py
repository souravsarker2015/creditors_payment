"""Creditor categories become a list each person keeps (add with +, rename, hide, delete).

Nothing is lost: every user gets the twelve categories the fixed list had, and
each creditor is linked to the one it had (FAMILY -> that user's "Family").
Going back (migrate creditors 0012) puts the codes back the same way.

A backup made before this update is brought up to date when it is restored
(apps.core.backup_upgrades), the same way as here.
"""
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

# The fixed list as it was (code, English name). Frozen here: the migration must not follow later code.
STARTERS = (
    ("FAMILY", "Family"), ("FRIEND", "Friend"), ("BUSINESS_PARTNER", "Business Partner"), ("BANK", "Bank"),
    ("MICROFINANCE", "Microfinance"), ("MONEYLENDER", "Moneylender"), ("SUPPLIER", "Supplier"),
    ("LANDLORD", "Landlord"), ("UTILITY", "Utility"), ("MEDICAL", "Medical"), ("EDUCATION", "Education"),
    ("OTHER", "Other"),
)


def seed_and_link(apps, schema_editor, app="creditors", person="Creditor", category="CreditorCategory", starters=STARTERS):
    """Shared with the debtors' migration (it passes its own names and list)."""
    User = apps.get_model(*settings.AUTH_USER_MODEL.split("."))
    Person = apps.get_model(app, person)
    Category = apps.get_model(app, category)
    names = dict(starters)
    db = schema_editor.connection.alias
    Category.objects.using(db).bulk_create(
        [Category(user_id=uid, name=name, code=code) for uid in User.objects.using(db).values_list("pk", flat=True)
         for code, name in starters],
        ignore_conflicts=True, batch_size=500,
    )
    made = {(c.user_id, c.code): c.pk for c in Category.objects.using(db).all()}
    for row in Person.objects.using(db).values("user_id", "category").distinct():
        code = row["category"] or "OTHER"
        key = (row["user_id"], code)
        if key not in made:            # a value the fixed list never had: kept, as its own category
            name = names.get(code) or code.replace("_", " ").title()[:80]
            made[key] = Category.objects.using(db).create(user_id=row["user_id"], name=name, code=code).pk
        Person.objects.using(db).filter(user_id=row["user_id"], category=row["category"]).update(category_ref=made[key])


def unlink(apps, schema_editor, app="creditors", person="Creditor", starters=STARTERS):
    """Back to the fixed list: each person gets their category's code again ("OTHER" for one added since, or none)."""
    Person = apps.get_model(app, person)
    db = schema_editor.connection.alias
    for row in Person.objects.using(db).values("category_ref", "category_ref__code").distinct():
        Person.objects.using(db).filter(category_ref=row["category_ref"]).update(category=row["category_ref__code"] or "OTHER")


class Migration(migrations.Migration):

    dependencies = [
        ('creditors', '0012_transaction_receipt'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='CreditorCategory',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=80, verbose_name='Name')),
                ('code', models.CharField(blank=True, default='', editable=False, max_length=32)),
                ('is_active', models.BooleanField(default=True, verbose_name='In use')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='%(app_label)s_categories', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Creditor category',
                'verbose_name_plural': 'Creditor categories',
                'ordering': ['name'],
                'abstract': False,
            },
        ),
        migrations.AddConstraint(
            model_name='creditorcategory',
            constraint=models.UniqueConstraint(fields=('user', 'name'), name='creditor_category_unique_name'),
        ),
        # The new link sits beside the old code while the codes are turned into links…
        migrations.AddField(
            model_name='creditor',
            name='category_ref',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='creditors.creditorcategory'),
        ),
        migrations.RunPython(seed_and_link, unlink),
        # …then takes its place.
        migrations.RemoveField(model_name='creditor', name='category'),
        migrations.RenameField(model_name='creditor', old_name='category_ref', new_name='category'),
        migrations.AlterField(
            model_name='creditor',
            name='category',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='creditors', to='creditors.creditorcategory', verbose_name='Category'),
        ),
    ]
