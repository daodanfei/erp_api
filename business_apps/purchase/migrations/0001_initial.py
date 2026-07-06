from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('auth', '0012_alter_user_first_name_max_length'),
        ('inventory', '0002_product_max_stock_product_min_stock_stocktake_and_more'),
        ('supplier', '0001_initial'),
        ('organization', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='PurchaseOrder',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('purchase_order_no', models.CharField(max_length=50, unique=True, verbose_name='采购单号')),
                ('supplier_name_snapshot', models.CharField(blank=True, max_length=255, null=True, verbose_name='供应商名称快照')),
                ('supplier_code_snapshot', models.CharField(blank=True, max_length=50, null=True, verbose_name='供应商编码快照')),
                ('status', models.CharField(choices=[('DRAFT', '草稿'), ('PENDING_APPROVAL', '待审核'), ('APPROVED', '审核通过'), ('REJECTED', '已驳回'), ('PARTIALLY_RECEIVED', '部分到货'), ('RECEIVED', '全部到货'), ('CANCELLED', '已取消')], default='DRAFT', max_length=20, verbose_name='状态')),
                ('order_date', models.DateField(auto_now_add=True, verbose_name='订单日期')),
                ('expected_arrival_date', models.DateField(blank=True, null=True, verbose_name='预计到货日期')),
                ('total_quantity', models.DecimalField(decimal_places=3, default=0, max_digits=15, verbose_name='总数量')),
                ('total_amount', models.DecimalField(decimal_places=2, default=0, max_digits=15, verbose_name='总金额')),
                ('remark', models.TextField(blank=True, null=True, verbose_name='备注')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='更新时间')),
                ('created_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_purchase_orders', to=settings.AUTH_USER_MODEL, verbose_name='创建人')),
                ('dept', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='organization.department', verbose_name='所属部门')),
                ('supplier', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='purchase_orders', to='supplier.supplier')),
            ],
            options={
                'verbose_name': '采购订单',
                'verbose_name_plural': '采购订单',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='purchaseorder',
            index=models.Index(fields=['purchase_order_no'], name='purchase_no_idx'),
        ),
        migrations.AddIndex(
            model_name='purchaseorder',
            index=models.Index(fields=['supplier'], name='purchase_supplier_idx'),
        ),
        migrations.AddIndex(
            model_name='purchaseorder',
            index=models.Index(fields=['status'], name='purchase_status_idx'),
        ),
        migrations.AddIndex(
            model_name='purchaseorder',
            index=models.Index(fields=['created_by'], name='purchase_created_idx'),
        ),
        migrations.AddIndex(
            model_name='purchaseorder',
            index=models.Index(fields=['order_date'], name='purchase_date_idx'),
        ),
        migrations.AddIndex(
            model_name='purchaseorder',
            index=models.Index(fields=['dept'], name='purchase_dept_idx'),
        ),
        migrations.CreateModel(
            name='PurchaseOrderItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('product_name_snapshot', models.CharField(blank=True, max_length=255, null=True, verbose_name='商品名称快照')),
                ('product_code_snapshot', models.CharField(blank=True, max_length=50, null=True, verbose_name='商品编码快照')),
                ('unit_price_snapshot', models.DecimalField(blank=True, decimal_places=2, max_digits=15, null=True, verbose_name='商品成本价快照')),
                ('quantity', models.DecimalField(decimal_places=3, max_digits=15, verbose_name='采购数量')),
                ('unit_price', models.DecimalField(decimal_places=2, max_digits=15, verbose_name='单价')),
                ('amount', models.DecimalField(decimal_places=2, max_digits=15, verbose_name='金额')),
                ('received_quantity', models.DecimalField(decimal_places=3, default=0, max_digits=15, verbose_name='已收货数量')),
                ('remark', models.TextField(blank=True, null=True, verbose_name='备注')),
                ('product', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='inventory.product', verbose_name='商品')),
                ('purchase_order', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='items', to='purchase.purchaseorder', verbose_name='采购订单')),
                ('warehouse', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to='inventory.warehouse', verbose_name='仓库')),
            ],
            options={
                'verbose_name': '采购订单明细',
                'verbose_name_plural': '采购订单明细',
            },
        ),
        migrations.AddIndex(
            model_name='purchaseorderitem',
            index=models.Index(fields=['purchase_order'], name='purchase_item_po_idx'),
        ),
        migrations.AddIndex(
            model_name='purchaseorderitem',
            index=models.Index(fields=['product'], name='purchase_item_prod_idx'),
        ),
        migrations.CreateModel(
            name='PurchaseReceipt',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('receipt_no', models.CharField(max_length=50, unique=True, verbose_name='入库单号')),
                ('status', models.CharField(choices=[('DRAFT', '草稿'), ('COMPLETED', '已完成'), ('CANCELLED', '已取消')], default='DRAFT', max_length=20, verbose_name='状态')),
                ('received_at', models.DateTimeField(blank=True, null=True, verbose_name='入库时间')),
                ('remark', models.TextField(blank=True, null=True, verbose_name='备注')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('created_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL, verbose_name='创建人')),
                ('purchase_order', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='receipts', to='purchase.purchaseorder', verbose_name='采购订单')),
                ('warehouse', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='inventory.warehouse', verbose_name='仓库')),
            ],
            options={
                'verbose_name': '采购入库单',
                'verbose_name_plural': '采购入库单',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='purchasereceipt',
            index=models.Index(fields=['receipt_no'], name='purchase_receipt_no_idx'),
        ),
        migrations.AddIndex(
            model_name='purchasereceipt',
            index=models.Index(fields=['purchase_order'], name='purchase_receipt_po_idx'),
        ),
        migrations.AddIndex(
            model_name='purchasereceipt',
            index=models.Index(fields=['status'], name='purchase_receipt_status_idx'),
        ),
        migrations.CreateModel(
            name='PurchaseReceiptItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('product_name_snapshot', models.CharField(blank=True, max_length=255, null=True, verbose_name='商品名称快照')),
                ('product_code_snapshot', models.CharField(blank=True, max_length=50, null=True, verbose_name='商品编码快照')),
                ('received_quantity', models.DecimalField(decimal_places=3, max_digits=15, verbose_name='入库数量')),
                ('remark', models.TextField(blank=True, null=True, verbose_name='备注')),
                ('product', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='inventory.product', verbose_name='商品')),
                ('purchase_order_item', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='purchase.purchaseorderitem', verbose_name='采购订单明细')),
                ('receipt', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='items', to='purchase.purchasereceipt', verbose_name='入库单')),
            ],
            options={
                'verbose_name': '采购入库明细',
                'verbose_name_plural': '采购入库明细',
            },
        ),
        migrations.AddIndex(
            model_name='purchasereceiptitem',
            index=models.Index(fields=['receipt'], name='purchase_ri_receipt_idx'),
        ),
        migrations.CreateModel(
            name='PurchaseApprovalLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('action', models.CharField(choices=[('APPROVE', '审核通过'), ('REJECT', '审核驳回')], max_length=50, verbose_name='审核动作')),
                ('comment', models.TextField(blank=True, null=True, verbose_name='审核意见')),
                ('approved_at', models.DateTimeField(auto_now_add=True, verbose_name='审核时间')),
                ('approved_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL, verbose_name='审核人')),
                ('purchase_order', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='approval_logs', to='purchase.purchaseorder', verbose_name='采购订单')),
            ],
            options={
                'verbose_name': '采购审批日志',
                'verbose_name_plural': '采购审批日志',
                'ordering': ['-approved_at'],
            },
        ),
        migrations.AddIndex(
            model_name='purchaseapprovallog',
            index=models.Index(fields=['purchase_order'], name='purchase_approval_po_idx'),
        ),
        migrations.CreateModel(
            name='PurchaseChangeLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('field_name', models.CharField(max_length=100, verbose_name='变更字段')),
                ('old_value', models.TextField(blank=True, null=True, verbose_name='变更前')),
                ('new_value', models.TextField(blank=True, null=True, verbose_name='变更后')),
                ('changed_at', models.DateTimeField(auto_now_add=True, verbose_name='变更时间')),
                ('changed_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL, verbose_name='变更人')),
                ('purchase_order', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='change_logs', to='purchase.purchaseorder', verbose_name='采购订单')),
            ],
            options={
                'verbose_name': '采购变更日志',
                'verbose_name_plural': '采购变更日志',
                'ordering': ['-changed_at'],
            },
        ),
        migrations.AddIndex(
            model_name='purchasechangelog',
            index=models.Index(fields=['purchase_order'], name='purchase_change_po_idx'),
        ),
        migrations.CreateModel(
            name='PurchaseAttachment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('file_name', models.CharField(max_length=255, verbose_name='文件名')),
                ('file_url', models.CharField(max_length=500, verbose_name='文件地址')),
                ('uploaded_at', models.DateTimeField(auto_now_add=True, verbose_name='上传时间')),
                ('purchase_order', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='attachments', to='purchase.purchaseorder', verbose_name='采购订单')),
                ('uploaded_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL, verbose_name='上传人')),
            ],
            options={
                'verbose_name': '采购附件',
                'verbose_name_plural': '采购附件',
                'ordering': ['-uploaded_at'],
            },
        ),
        migrations.AddIndex(
            model_name='purchaseattachment',
            index=models.Index(fields=['purchase_order'], name='purchase_attach_po_idx'),
        ),
    ]
