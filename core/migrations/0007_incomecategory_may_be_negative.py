"""Phase 11: category flag "may be negative" (a normal payment may be a loss).

Owner default: the capital-income categories and the private-sale category. The flag is set from the owner's own
mapping (SBK treatment capital, or tax income type capital / private_sale); nothing is guessed from names.
The reverse drops the column (payments already saved as losses would then violate the sign rule, so reverse only
before any loss is recorded)."""
from django.db import migrations, models


def flag_capital_categories(apps, schema_editor):
    Category = apps.get_model('core', 'IncomeCategory')
    Category.objects.filter(models.Q(sbk_treatment='capital') | models.Q(tax_income_type__in=['capital', 'private_sale'])
                            ).update(may_be_negative=True)


class Migration(migrations.Migration):

    dependencies = [('core', '0006_payment_withholding_tax_expenses')]

    operations = [
        migrations.AddField('incomecategory', 'may_be_negative', models.BooleanField(
            default=False, help_text='Tick if a normal payment in this category may be a loss (negative gross amount).')),
        migrations.RunPython(flag_capital_categories, migrations.RunPython.noop),
    ]
