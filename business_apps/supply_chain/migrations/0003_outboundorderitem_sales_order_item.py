from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0002_salesorder_customer_name_snapshot_and_more'),
        ('supply_chain', '0002_rename_supply_chai_warehous_u1v2w3_idx_supply_chai_warehou_fdaf82_idx_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='outboundorderitem',
            name='sales_order_item',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='outbound_items', to='sales.salesorderitem', verbose_name='销售订单明细'),
        ),
    ]
