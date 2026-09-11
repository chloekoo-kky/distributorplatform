from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('product', '0013_product_display_order_zero_to_ninety_nine'),
    ]

    operations = [
        migrations.CreateModel(
            name='ProductInvoiceNameAlias',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(help_text='Original invoice or merged product name.', max_length=200)),
                ('name_normalized', models.CharField(
                    db_index=True,
                    help_text='Lowercased, whitespace-collapsed name used for matching.',
                    max_length=200,
                    unique=True,
                )),
                ('source', models.CharField(
                    choices=[('merge', 'Product merge'), ('invoice', 'Invoice import')],
                    default='merge',
                    max_length=20,
                )),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('product', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='invoice_name_aliases',
                    to='product.product',
                )),
            ],
            options={
                'verbose_name': 'Invoice product name alias',
                'verbose_name_plural': 'Invoice product name aliases',
                'ordering': ['name'],
            },
        ),
    ]
