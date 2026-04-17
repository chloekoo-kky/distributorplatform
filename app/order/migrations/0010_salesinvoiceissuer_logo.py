from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('order', '0009_salesinvoiceissuer'),
    ]

    operations = [
        migrations.AddField(
            model_name='salesinvoiceissuer',
            name='logo',
            field=models.ImageField(
                blank=True,
                help_text='Shown top-left on printed sales invoices (PNG, JPG, or WebP).',
                null=True,
                upload_to='invoice_issuers/logos/%Y/%m/',
            ),
        ),
    ]
