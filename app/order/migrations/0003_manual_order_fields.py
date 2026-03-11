# Generated manually for Manual Order Entry feature

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('order', '0002_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='created_by',
            field=models.ForeignKey(
                blank=True,
                help_text='Staff/salesperson who entered this order. When set, commission is skipped.',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='orders_created',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='order',
            name='sales_channel',
            field=models.CharField(
                blank=True,
                choices=[
                    ('WhatsApp', 'WhatsApp'),
                    ('Shopee', 'Shopee'),
                    ('Lazada', 'Lazada'),
                    ('Offline', 'Offline'),
                    ('Other', 'Other'),
                ],
                default='Other',
                max_length=50,
            ),
        ),
        migrations.AddField(
            model_name='order',
            name='customer_name',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name='order',
            name='customer_phone',
            field=models.CharField(blank=True, max_length=50, null=True),
        ),
        migrations.AddField(
            model_name='order',
            name='shipping_address',
            field=models.TextField(blank=True, null=True),
        ),
    ]
