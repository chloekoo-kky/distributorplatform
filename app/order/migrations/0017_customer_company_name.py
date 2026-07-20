from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('order', '0016_cashbankreceiptentry_collected_by'),
    ]

    operations = [
        migrations.AddField(
            model_name='customer',
            name='company_name',
            field=models.CharField(
                blank=True,
                help_text='Bill-to / trading company name (searchable in manual order entry).',
                max_length=255,
                null=True,
            ),
        ),
    ]
