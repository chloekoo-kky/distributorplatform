from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('order', '0010_salesinvoiceissuer_logo'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='company_name',
            field=models.CharField(
                blank=True,
                help_text='Bill-to company name (shown on sales invoices).',
                max_length=255,
                null=True,
            ),
        ),
    ]
