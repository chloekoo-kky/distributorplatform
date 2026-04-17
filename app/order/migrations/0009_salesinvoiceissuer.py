# Generated manually for SalesInvoiceIssuer

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('order', '0008_customeraddress'),
    ]

    operations = [
        migrations.CreateModel(
            name='SalesInvoiceIssuer',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('label', models.CharField(help_text='Short name shown in dropdowns (e.g. "HQ — ABC Sdn Bhd").', max_length=120)),
                ('legal_name', models.CharField(help_text='Full name as printed on the invoice.', max_length=255)),
                ('address', models.TextField(blank=True, help_text='Registered / mailing address.')),
                ('phone', models.CharField(blank=True, max_length=80)),
                ('email', models.EmailField(blank=True, max_length=254)),
                ('tax_id', models.CharField(blank=True, help_text='SST / VAT / tax registration number, if applicable.', max_length=80)),
                ('registration_no', models.CharField(blank=True, help_text='Company registration number, if applicable.', max_length=80)),
                ('bank_details', models.TextField(blank=True, help_text='Payment instructions (bank name, account no., reference).')),
                ('is_default', models.BooleanField(default=False, help_text='Pre-selected when opening the sales invoice dialog.')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'ordering': ['-is_default', 'label'],
            },
        ),
    ]
