from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('supplier', '0002_supplier_currency_supplier_tax_rate_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='supplier',
            name='default_payment_method',
            field=models.CharField(
                choices=[
                    ('CASH', '现金'),
                    ('BANK_TRANSFER', '银行转账'),
                    ('CHECK', '支票'),
                    ('WECHAT', '微信'),
                    ('ALIPAY', '支付宝'),
                    ('OTHER', '其他'),
                ],
                default='BANK_TRANSFER',
                max_length=20,
                verbose_name='默认付款方式',
            ),
        ),
        migrations.AddField(
            model_name='supplier',
            name='settlement_cycle',
            field=models.CharField(
                choices=[
                    ('PER_RECEIPT', '逐单结算'),
                    ('WEEKLY', '周结'),
                    ('BIWEEKLY', '半月结'),
                    ('MONTHLY', '月结'),
                ],
                default='PER_RECEIPT',
                max_length=20,
                verbose_name='结算周期',
            ),
        ),
        migrations.AlterField(
            model_name='supplier',
            name='payment_term',
            field=models.CharField(
                choices=[('PREPAID', '预付'), ('NET_30', '30天账期'), ('NET_60', '60天账期'), ('NET_90', '90天账期')],
                default='NET_30',
                max_length=20,
                verbose_name='默认账期',
            ),
        ),
    ]
