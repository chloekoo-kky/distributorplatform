from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('product', '0015_product_alias_source_manual'),
    ]

    operations = [
        migrations.AddField(
            model_name='product',
            name='reference_price',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text='Internal reference price shown on product mapping. Not the customer selling price.',
                max_digits=10,
                null=True,
            ),
        ),
    ]
