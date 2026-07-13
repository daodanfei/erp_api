from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('ar_receivable', '0012_alter_receivable_status_customerrefund'),
        ('erp_auth', '0002_erpdepartment_erpuser_dept'),
    ]

    operations = [
        migrations.AddField(
            model_name='customerrefund',
            name='bank_account',
            field=models.CharField(blank=True, max_length=100, null=True, verbose_name='退款银行卡/账号'),
        ),
        migrations.AddField(
            model_name='customerrefund',
            name='submitted_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='customerrefund',
            name='submitted_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='submitted_customer_refunds', to='erp_auth.erpuser'),
        ),
        migrations.AlterField(
            model_name='customerrefund',
            name='status',
            field=models.CharField(choices=[('DRAFT', '草稿'), ('PENDING_APPROVAL', '待审核'), ('APPROVED', '已审核'), ('COMPLETED', '已退款'), ('CANCELLED', '已作废')], default='DRAFT', max_length=20),
        ),
    ]
