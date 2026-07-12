from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ar_receivable", "0010_alter_receipt_approved_by_alter_receipt_created_by_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="writeoff",
            name="receipt",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.deletion.PROTECT,
                related_name="write_offs",
                to="ar_receivable.receipt",
            ),
        ),
    ]
