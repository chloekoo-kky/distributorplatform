# Generated manually for product alias_name (manual orders / copy summary)

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('product', '0009_productpricetier'),
    ]

    operations = [
        migrations.AddField(
            model_name='product',
            name='alias_name',
            field=models.CharField(
                blank=True,
                help_text='Optional short or alternate name for manual orders and internal copy (e.g. platform listing title). Searched alongside product name.',
                max_length=200,
            ),
        ),
    ]
