from django.db import migrations

SEED = ['Salary', 'Pension', 'Rental', 'Interest', 'Dividends', 'Capital gains', 'Other']


def seed(apps, schema_editor):
    Category = apps.get_model('core', 'IncomeCategory')
    for name in SEED:
        Category.objects.get_or_create(name__iexact=name, defaults={'name': name})


class Migration(migrations.Migration):
    dependencies = [('core', '0001_initial_models')]
    # Reverse is a no-op: categories may be referenced by payments.
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
