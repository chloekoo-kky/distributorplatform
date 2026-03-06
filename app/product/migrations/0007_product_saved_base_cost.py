# Generated manually for saved_base_cost (remember selected base cost source in Set Product Pricing)

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('product', '0006_product_is_best_seller'),
    ]

    operations = [
        migrations.AddField(
            model_name='product',
            name='saved_base_cost',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text="User-selected base cost (from a specific supplier quote). Used for pricing; shown in Set Product Pricing modal.",
                max_digits=10,
                null=True
            ),
        ),
    ]
