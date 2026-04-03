# Generated manually for quotation line vs catalog naming on export/import

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0004_alter_quotationitem_quoted_price'),
    ]

    operations = [
        migrations.AddField(
            model_name='quotationitem',
            name='line_product_label',
            field=models.CharField(
                blank=True,
                max_length=255,
                help_text='Name as shown on the supplier quotation or import file; may differ from the mapped catalog product name.',
            ),
        ),
    ]
