from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('order', '0019_order_company_address'),
    ]

    operations = [
        migrations.AddField(
            model_name='revenueadjustmententry',
            name='agent',
            field=models.ForeignKey(
                blank=True,
                help_text='Agent this positive line revenue belongs to (Salesteam on exports).',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='agent_revenue_adjustment_entries',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
