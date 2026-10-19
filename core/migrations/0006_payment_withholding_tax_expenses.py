"""Phase 10: withholding tax and expenses on payments (ADR 0010).

Existing rows get 0 for both amounts; no breakdown is guessed. Converted rows get 0 EUR for both (0 x rate is
exactly 0); unconverted rows keep NULL EUR. Fully reversible: the reverse simply drops the four columns."""
from decimal import Decimal

from django.db import migrations, models


def zero_eur_for_converted(apps, schema_editor):
    Payment = apps.get_model('core', 'Payment')
    Payment.objects.filter(conversion_status='converted').update(
        withholding_tax_eur=Decimal(0), expenses_eur=Decimal(0))


class Migration(migrations.Migration):

    dependencies = [('core', '0005_assessment_mappings_and_inputs')]

    operations = [
        migrations.AddField('payment', 'withholding_tax', models.DecimalField(decimal_places=4, default=0, max_digits=16)),
        migrations.AddField('payment', 'expenses', models.DecimalField(decimal_places=4, default=0, max_digits=16)),
        migrations.AddField('payment', 'withholding_tax_eur', models.DecimalField(blank=True, decimal_places=6, max_digits=20, null=True)),
        migrations.AddField('payment', 'expenses_eur', models.DecimalField(blank=True, decimal_places=6, max_digits=20, null=True)),
        migrations.RunPython(zero_eur_for_converted, migrations.RunPython.noop),
    ]
