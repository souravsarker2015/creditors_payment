import django.db.models.deletion
from django.db import migrations, models


def fill_base_quantity(apps, schema_editor):
    Treatment = apps.get_model("business_ponds", "Treatment")
    for t in Treatment.objects.filter(quantity__isnull=False, unit__isnull=False).select_related("unit"):
        t.base_quantity = t.quantity * t.unit.factor
        t.save(update_fields=["base_quantity"])


class Migration(migrations.Migration):

    dependencies = [
        ('business_ponds', '0005_lease_payment'),
        ('business_supplies', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='treatment',
            name='base_quantity',
            field=models.DecimalField(blank=True, decimal_places=3, editable=False, max_digits=18, null=True),
        ),
        migrations.AddField(
            model_name='treatment',
            name='item',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='uses', to='business_supplies.supplyitem', verbose_name='From your store'),
        ),
        migrations.RunPython(fill_base_quantity, migrations.RunPython.noop),
    ]
