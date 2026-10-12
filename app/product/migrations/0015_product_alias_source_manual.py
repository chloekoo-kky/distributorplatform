from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('product', '0014_productinvoicenamealias'),
    ]

    operations = [
        migrations.AlterField(
            model_name='productinvoicenamealias',
            name='source',
            field=models.CharField(
                choices=[
                    ('merge', 'Product merge'),
                    ('invoice', 'Invoice import'),
                    ('manual', 'Manual mapping'),
                ],
                default='merge',
                max_length=20,
            ),
        ),
    ]
