from django.db import models
from core_apps.erp_auth.compat import build_erp_user_fk_kwargs
from core_apps.erp_auth.models import ERPUser
from core_apps.tenant.models import Tenant

class CashAccount(models.Model):
    TYPE_CHOICES = (
        ('CASH', '现金'),
        ('BANK', '银行账户'),
        ('ALIPAY', '支付宝'),
        ('WECHAT', '微信'),
        ('OTHER', '其他'),
    )
    ACCOUNT_TYPE_CHOICES = TYPE_CHOICES

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='cash_accounts', null=True, blank=True)
    name = models.CharField(max_length=100, verbose_name="账户名称")
    type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='BANK')
    account_type = models.CharField(max_length=20, choices=ACCOUNT_TYPE_CHOICES, default='BANK', verbose_name="账户类型")
    account_no = models.CharField(max_length=100, null=True, blank=True, verbose_name="账号/卡号")
    bank_name = models.CharField(max_length=100, null=True, blank=True, verbose_name="开户行")
    currency = models.CharField(max_length=10, default='CNY')
    opening_balance_date = models.DateField(null=True, blank=True, verbose_name="期初余额日期")
    current_balance = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=0,
        verbose_name="当前余额",
        help_text="缓存字段，由资金流水或后续总账/凭证汇总回写",
    )
    status = models.BooleanField(default=True, verbose_name="是否启用")
    remark = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "现金账户"
        verbose_name_plural = verbose_name

    def __str__(self):
        return self.name


class CashAccountTransaction(models.Model):
    DIRECTION_CHOICES = (
        ('INFLOW', '流入'),
        ('OUTFLOW', '流出'),
    )
    SOURCE_TYPE_CHOICES = (
        ('OPENING_BALANCE', '期初余额'),
        ('AR_RECEIPT', '应收收款执行'),
        ('AP_PAYMENT', '应付付款执行'),
        ('MANUAL', '手工调整'),
    )

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='cash_account_transactions', null=True, blank=True)
    cash_account = models.ForeignKey(CashAccount, on_delete=models.CASCADE, related_name='transactions')
    transaction_date = models.DateField(verbose_name="资金日期")
    direction = models.CharField(max_length=20, choices=DIRECTION_CHOICES, verbose_name="资金方向")
    amount = models.DecimalField(max_digits=15, decimal_places=2, verbose_name="变动金额")
    balance_after = models.DecimalField(max_digits=15, decimal_places=2, verbose_name="变动后余额")
    source_type = models.CharField(max_length=30, choices=SOURCE_TYPE_CHOICES, verbose_name="来源类型")
    source_id = models.IntegerField(null=True, blank=True, verbose_name="来源单据ID")
    source_document_no_snapshot = models.CharField(max_length=100, null=True, blank=True, verbose_name="来源单号快照")
    remark = models.TextField(null=True, blank=True)
    operator = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "资金流水"
        verbose_name_plural = verbose_name
        ordering = ['-transaction_date', '-id']

    @classmethod
    def record_change(
        cls,
        *,
        cash_account,
        direction,
        amount,
        source_type,
        operator=None,
        source_id=None,
        source_document_no_snapshot=None,
        transaction_date=None,
        remark=None,
    ):
        from decimal import Decimal

        amount = Decimal(str(amount))
        transaction_date = transaction_date or timezone.now().date()
        signed_amount = amount if direction == 'INFLOW' else -amount
        cash_account.current_balance += signed_amount
        cash_account.save(update_fields=['current_balance'])
        return cls.objects.create(
            tenant=cash_account.tenant,
            cash_account=cash_account,
            transaction_date=transaction_date,
            direction=direction,
            amount=amount,
            balance_after=cash_account.current_balance,
            source_type=source_type,
            source_id=source_id,
            source_document_no_snapshot=source_document_no_snapshot,
            remark=remark,
            **build_erp_user_fk_kwargs(
                cls,
                user=operator,
                field_names=("operator",),
            ),
        )

class FinancialSnapshot(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='financial_snapshots', null=True, blank=True)
    snapshot_date = models.DateField(unique=True, verbose_name="快照日期")
    total_ar = models.DecimalField(max_digits=20, decimal_places=2, default=0, verbose_name="总应收")
    total_ap = models.DecimalField(max_digits=20, decimal_places=2, default=0, verbose_name="总应付")
    total_cash = models.DecimalField(max_digits=20, decimal_places=2, default=0, verbose_name="现金总余额")
    daily_revenue = models.DecimalField(max_digits=20, decimal_places=2, default=0, verbose_name="当日收款额")
    daily_expense = models.DecimalField(max_digits=20, decimal_places=2, default=0, verbose_name="当日付款额")
    
    class Meta:
        verbose_name = "财务统计快照"
        verbose_name_plural = verbose_name
        ordering = ['-snapshot_date']

class FinanceExportTask(models.Model):
    STATUS_CHOICES = (
        ('PENDING', '排队中'),
        ('PROCESSING', '处理中'),
        ('COMPLETED', '已完成'),
        ('FAILED', '失败'),
    )
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='finance_export_tasks', null=True, blank=True)
    task_type = models.CharField(max_length=50) # RECONCILIATION, AGING, etc.
    parameters = models.JSONField(default=dict)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    file_url = models.CharField(max_length=500, null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)
    created_by = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "财务导出任务"
        verbose_name_plural = verbose_name
