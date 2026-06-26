from django.db import migrations, models


def backfill_finance_transaction_ids(apps, schema_editor):
    prefixes = (
        ('CashBankReceiptEntry', 'CB'),
        ('AgentCommissionPaymentEntry', 'CP'),
        ('RevenueAdjustmentEntry', 'RA'),
    )
    for model_name, prefix in prefixes:
        Model = apps.get_model('order', model_name)
        for row in Model.objects.order_by('pk'):
            if row.transaction_id:
                continue
            row.transaction_id = f'{prefix}-{row.pk:07d}'
            row.save(update_fields=['transaction_id'])


class Migration(migrations.Migration):

    dependencies = [
        ('order', '0014_revenue_adjustment_and_loan_repayment'),
    ]

    operations = [
        migrations.AddField(
            model_name='cashbankreceiptentry',
            name='transaction_id',
            field=models.CharField(blank=True, default='', editable=False, max_length=20),
        ),
        migrations.AddField(
            model_name='agentcommissionpaymententry',
            name='transaction_id',
            field=models.CharField(blank=True, default='', editable=False, max_length=20),
        ),
        migrations.AddField(
            model_name='revenueadjustmententry',
            name='transaction_id',
            field=models.CharField(blank=True, default='', editable=False, max_length=20),
        ),
        migrations.RunPython(backfill_finance_transaction_ids, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='cashbankreceiptentry',
            name='transaction_id',
            field=models.CharField(blank=True, default='', editable=False, max_length=20, unique=True),
        ),
        migrations.AlterField(
            model_name='agentcommissionpaymententry',
            name='transaction_id',
            field=models.CharField(blank=True, default='', editable=False, max_length=20, unique=True),
        ),
        migrations.AlterField(
            model_name='revenueadjustmententry',
            name='transaction_id',
            field=models.CharField(blank=True, default='', editable=False, max_length=20, unique=True),
        ),
    ]
