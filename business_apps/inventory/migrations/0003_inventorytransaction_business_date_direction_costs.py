import django.utils.timezone
from django.db import migrations, models


def populate_transaction_direction_and_business_date(apps, schema_editor):
    InventoryTransaction = apps.get_model('inventory', 'InventoryTransaction')
    for transaction in InventoryTransaction.objects.all().iterator():
        transaction.direction = 'IN' if transaction.quantity > 0 else 'OUT'
        transaction.business_date = transaction.created_at.date()
        transaction.save(update_fields=['direction', 'business_date'])


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0002_product_max_stock_product_min_stock_stocktake_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='inventorytransaction',
            name='business_date',
            field=models.DateField(default=django.utils.timezone.localdate, verbose_name='业务日期'),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='inventorytransaction',
            name='direction',
            field=models.CharField(choices=[('IN', '入'), ('OUT', '出')], default='IN', max_length=3, verbose_name='方向'),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='inventorytransaction',
            name='total_cost',
            field=models.DecimalField(blank=True, decimal_places=4, max_digits=15, null=True, verbose_name='成本金额'),
        ),
        migrations.AddField(
            model_name='inventorytransaction',
            name='unit_cost',
            field=models.DecimalField(blank=True, decimal_places=4, max_digits=15, null=True, verbose_name='单位成本'),
        ),
        migrations.RunPython(
            populate_transaction_direction_and_business_date,
            migrations.RunPython.noop,
        ),
    ]
