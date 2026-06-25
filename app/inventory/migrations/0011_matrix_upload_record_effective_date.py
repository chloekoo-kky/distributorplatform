from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0010_matrix_conversion_rate'),
    ]

    operations = [
        migrations.AddField(
            model_name='supplierpricematrixuploadrecord',
            name='effective_date',
            field=models.DateField(
                blank=True,
                help_text='Business date for this price (e.g. invoice date from payable invoice import).',
                null=True,
            ),
        ),
        migrations.AlterModelOptions(
            name='supplierpricematrixuploadrecord',
            options={
                'ordering': ['-effective_date', '-uploaded_at'],
                'verbose_name': 'Supplier price matrix upload record',
                'verbose_name_plural': 'Supplier price matrix upload records',
            },
        ),
    ]
