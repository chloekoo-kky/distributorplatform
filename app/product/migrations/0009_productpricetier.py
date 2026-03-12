# Price tier: min_quantity triggers lower selling price per unit

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('product', '0008_ignoredmergesuggestion'),
    ]

    operations = [
        migrations.CreateModel(
            name='ProductPriceTier',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('min_quantity', models.PositiveIntegerField(help_text="Minimum order quantity to get this price (e.g. 10 for '10+ units').")),
                ('price', models.DecimalField(decimal_places=2, help_text='Selling price per unit when order quantity meets min_quantity.', max_digits=10)),
                ('product', models.ForeignKey(on_delete=models.CASCADE, related_name='price_tiers', to='product.product')),
            ],
            options={
                'verbose_name': 'Price tier',
                'verbose_name_plural': 'Price tiers',
                'ordering': ['-min_quantity'],
                'unique_together': {('product', 'min_quantity')},
            },
        ),
    ]
