# Generated manually

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0004_alter_quotationitem_quoted_price'),
        ('product', '0010_product_alias_name'),
    ]

    operations = [
        migrations.AddField(
            model_name='product',
            name='saved_base_cost_supplier',
            field=models.ForeignKey(
                blank=True,
                help_text="Supplier tied to saved_base_cost so cost stays in sync when that supplier's quotation changes.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='+',
                to='inventory.supplier',
            ),
        ),
    ]
