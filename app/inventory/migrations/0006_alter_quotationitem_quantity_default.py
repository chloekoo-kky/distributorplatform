# Generated manually: default quantity 0 for pricing-only lines

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0005_quotationitem_line_product_label"),
    ]

    operations = [
        migrations.AlterField(
            model_name="quotationitem",
            name="quantity",
            field=models.PositiveIntegerField(
                default=0,
                help_text="Order quantity; 0 means the supplier lists this price but no order is placed on this quotation.",
            ),
        ),
    ]
