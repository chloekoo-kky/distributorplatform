from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('order', '0012_cash_bank_receipt_entry'),
    ]

    operations = [
        migrations.CreateModel(
            name='AgentCommissionPaymentEntry',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('paid_to', models.CharField(help_text='Agent name or reference.', max_length=255)),
                ('payment_date', models.DateField()),
                ('amount', models.DecimalField(decimal_places=2, max_digits=12)),
                ('notes', models.CharField(blank=True, default='', max_length=500)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('recorded_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='agent_commission_payment_entries', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['payment_date', 'id'],
            },
        ),
    ]
