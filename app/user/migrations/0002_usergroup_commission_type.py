from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('user', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='usergroup',
            name='commission_type',
            field=models.CharField(
                choices=[
                    ('PROFIT_PCT', '% of profit'),
                    ('SELLING_PCT', '% of selling price (by quantity tier)'),
                ],
                default='PROFIT_PCT',
                help_text='How commission is calculated for agents in this group.',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='usergroup',
            name='tier_commission_rates',
            field=models.JSONField(
                blank=True,
                default=list,
                help_text=(
                    'For SELLING_PCT: list of {min_quantity, rate} objects defining commission rate '
                    'per quantity tier, e.g. [{"min_quantity": 1, "rate": 5.0}, {"min_quantity": 10, "rate": 4.0}].'
                ),
            ),
        ),
        migrations.AlterField(
            model_name='usergroup',
            name='commission_percentage',
            field=models.DecimalField(
                decimal_places=2,
                default=0.0,
                help_text='For PROFIT_PCT: percentage of profit per unit (e.g., 50.00 for 50%).',
                max_digits=5,
            ),
        ),
    ]
