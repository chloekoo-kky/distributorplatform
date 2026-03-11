# Manual order: transaction_date on Order; platform_price, actual_unit_price on OrderItem

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('order', '0003_manual_order_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='transaction_date',
            field=models.DateField(blank=True, help_text='Date of transaction (manual orders).', null=True),
        ),
        migrations.AddField(
            model_name='orderitem',
            name='platform_price',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text='Original price on platform (for record-keeping).',
                max_digits=10,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='orderitem',
            name='actual_unit_price',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text='Net amount received after platform fees; used for order total.',
                max_digits=10,
                null=True,
            ),
        ),
    ]
