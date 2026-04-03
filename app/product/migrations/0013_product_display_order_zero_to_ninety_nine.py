from django.db import migrations


def forwards(apps, schema_editor):
    Product = apps.get_model("product", "Product")
    Product.objects.filter(display_order=0).update(display_order=99)


def backwards(apps, schema_editor):
    # Cannot know which rows were 0 before the forward migration.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("product", "0012_alter_product_display_order_default"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
