from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('order', '0018_remove_other_channel_add_item_discount'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='company_address',
            field=models.TextField(
                blank=True,
                help_text='Bill-to / company address (shown on sales invoices).',
                null=True,
            ),
        ),
    ]
