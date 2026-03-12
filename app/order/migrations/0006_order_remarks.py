# Generated manually for Order.remarks (optional platform order ID)

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('order', '0005_alter_orderitem_profit_alter_orderitem_selling_price'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='remarks',
            field=models.CharField(
                max_length=255,
                blank=True,
                null=True,
                help_text='Optional remarks for this order (e.g. external platform order ID).',
            ),
        ),
    ]

