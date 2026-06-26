from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('order', '0015_finance_entry_transaction_id'),
    ]

    operations = [
        migrations.AddField(
            model_name='cashbankreceiptentry',
            name='collected_by',
            field=models.ForeignKey(
                blank=True,
                help_text='Agent who collected this receipt.',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='collected_cash_bank_receipts',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
