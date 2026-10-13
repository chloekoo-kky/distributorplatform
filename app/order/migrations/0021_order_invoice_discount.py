from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('order', '0020_revenueadjustmententry_agent'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='invoice_discount',
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal('0.00'),
                help_text='Lump-sum discount printed on the sales invoice after Gross.',
                max_digits=12,
            ),
        ),
    ]
