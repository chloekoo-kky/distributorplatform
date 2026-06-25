from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='invoiceitem',
            name='gross_source',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text='Line gross in original currency.',
                max_digits=12,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='invoiceitem',
            name='original_currency',
            field=models.CharField(
                blank=True,
                help_text='Original invoice currency code (e.g. USD) when imported from payable invoice detail.',
                max_length=3,
            ),
        ),
        migrations.AddField(
            model_name='invoiceitem',
            name='unit_price_source',
            field=models.DecimalField(
                blank=True,
                decimal_places=4,
                help_text='Unit price in original currency before MYR conversion.',
                max_digits=12,
                null=True,
            ),
        ),
    ]
