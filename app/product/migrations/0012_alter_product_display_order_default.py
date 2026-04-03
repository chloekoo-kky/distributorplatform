from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("product", "0011_product_saved_base_cost_supplier"),
    ]

    operations = [
        migrations.AlterField(
            model_name="product",
            name="display_order",
            field=models.IntegerField(
                default=99,
                help_text="Order of display on the product list page (lowest number appears first). New products default to 99 until set.",
            ),
        ),
    ]
