# Generated manually for input_currency / input_value on QuotationItem

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0002_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='quotationitem',
            name='input_currency',
            field=models.CharField(
                blank=True,
                choices=[('EUR', 'EUR'), ('USD', 'USD'), ('MYR', 'MYR')],
                help_text='Currency the user entered (EUR/USD/MYR). When rate changes, only MYR is recalculated.',
                max_length=3,
                null=True
            ),
        ),
        migrations.AddField(
            model_name='quotationitem',
            name='input_value',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text='Price in input_currency. Used to recompute quoted_price (MYR) when rate changes.',
                max_digits=10,
                null=True
            ),
        ),
    ]
