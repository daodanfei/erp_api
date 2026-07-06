from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('crm', '0002_customer_credit_limit_customer_current_balance'),
    ]

    operations = [
        migrations.AddField(
            model_name='customer',
            name='credit_control_mode',
            field=models.CharField(
                choices=[('NONE', '不控制'), ('WARN', '超额预警'), ('BLOCK', '超额阻断')],
                default='BLOCK',
                max_length=20,
                verbose_name='信用控制模式',
            ),
        ),
        migrations.AddField(
            model_name='customer',
            name='default_payment_method',
            field=models.CharField(
                choices=[
                    ('BANK_TRANSFER', '银行转账'),
                    ('WECHAT', '微信支付'),
                    ('ALIPAY', '支付宝'),
                    ('CASH', '现金'),
                    ('OTHER', '其他'),
                ],
                default='BANK_TRANSFER',
                max_length=20,
                verbose_name='默认收款方式',
            ),
        ),
        migrations.AddField(
            model_name='customer',
            name='payment_term',
            field=models.CharField(
                choices=[('PREPAID', '预付'), ('NET_30', '30天账期'), ('NET_60', '60天账期'), ('NET_90', '90天账期')],
                default='NET_30',
                max_length=20,
                verbose_name='默认账期',
            ),
        ),
        migrations.AlterField(
            model_name='customer',
            name='current_balance',
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                help_text='缓存字段，由过账或往来子账回写',
                max_digits=15,
                verbose_name='当前应收余额',
            ),
        ),
    ]
