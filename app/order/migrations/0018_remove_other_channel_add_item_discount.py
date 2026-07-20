from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('order', '0017_customer_company_name'),
    ]

    operations = [
        migrations.AlterField(
            model_name='order',
            name='sales_channel',
            field=models.CharField(
                blank=True,
                choices=[
                    ('WhatsApp', 'WhatsApp'),
                    ('Shopee', 'Shopee'),
                    ('Lazada', 'Lazada'),
                    ('Website', 'Website'),
                ],
                default='WhatsApp',
                max_length=50,
            ),
        ),
        migrations.AddField(
            model_name='orderitem',
            name='discount_amount',
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal('0.00'),
                help_text='Flat RM discount for this line (subtracted from qty × unit price).',
                max_digits=10,
            ),
        ),
        migrations.AlterField(
            model_name='orderitem',
            name='profit',
            field=models.DecimalField(
                decimal_places=2,
                editable=False,
                help_text='(effective_unit_price - landed_cost) * quantity - discount_amount',
                max_digits=10,
            ),
        ),
    ]
