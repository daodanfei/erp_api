from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ap_payable", "0006_appayment_executed_at_apaccount_source_document_no_snapshot_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="apallocation",
            name="allocation_date",
            field=models.DateField(auto_now_add=True, verbose_name="核销日期"),
        ),
    ]
