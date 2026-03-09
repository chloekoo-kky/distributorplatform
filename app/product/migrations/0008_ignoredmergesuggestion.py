# Generated manually for Duplicate Checklist dismissal memory

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('product', '0007_product_saved_base_cost'),
    ]

    operations = [
        migrations.CreateModel(
            name='IgnoredMergeSuggestion',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('product_ids_signature', models.CharField(help_text="Sorted comma-separated product IDs, e.g. '12,34,56'. Used to match and exclude dismissed groups.", max_length=500, unique=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'verbose_name': 'Ignored merge suggestion',
                'verbose_name_plural': 'Ignored merge suggestions',
            },
        ),
    ]
