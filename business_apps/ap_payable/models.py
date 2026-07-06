from django.db import models
from business_apps.supplier.models import Supplier
from business_apps.purchase.models import PurchaseOrder, PurchaseReceipt
from core_apps.erp_auth.models import ERPDepartment, ERPUser
from core_apps.tenant.models import Tenant

class APAccount(models.Model):
    STATUS_CHOICES = (
        ('PENDING', '待付款'),
        ('PARTIAL', '部分付款'),
        ('PAID', '已付款'),
        ('OVERDUE', '已逾期'),
        ('CANCELLED', '已取消'),
    )
    SOURCE_TYPE_CHOICES = (
        ('PURCHASE_ORDER', '采购订单'),
        ('PURCHASE_RECEIPT', '采购入库单'),
        ('MANUAL', '手工创建'), # Although business rule says no manual, keep for flexibility
    )

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='ap_accounts', null=True, blank=True)
    ap_no = models.CharField(max_length=50, unique=True, verbose_name="应付单号")
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name='ap_accounts')
    
    source_type = models.CharField(max_length=50, choices=SOURCE_TYPE_CHOICES, default='PURCHASE_RECEIPT')
    source_id = models.IntegerField(null=True, blank=True, verbose_name="来源单据ID")
    source_document_no_snapshot = models.CharField(max_length=100, null=True, blank=True, verbose_name="来源单号快照")
    purchase_receipt = models.ForeignKey(PurchaseReceipt, on_delete=models.PROTECT, related_name='ap_accounts', null=True, blank=True, verbose_name="来源入库单")
    
    # Financial fields
    currency_code = models.CharField(max_length=10, default='CNY', verbose_name="币种")
    exchange_rate = models.DecimalField(max_digits=10, decimal_places=4, default=1.0)
    
    total_amount = models.DecimalField(max_digits=15, decimal_places=2, verbose_name="应付总额")
    paid_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0, verbose_name="已付金额")
    
    due_date = models.DateField(verbose_name="到期日")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    
    remark = models.TextField(null=True, blank=True)
    dept = models.ForeignKey(ERPDepartment, on_delete=models.SET_NULL, null=True, blank=True)
    created_by = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, related_name='created_ap_accounts')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    is_deleted = models.BooleanField(default=False)

    class Meta:
        verbose_name = "应付账款"
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['ap_no']),
            models.Index(fields=['supplier']),
            models.Index(fields=['status']),
            models.Index(fields=['due_date']),
            models.Index(fields=['purchase_receipt']),
        ]

    @property
    def balance_amount(self):
        return self.total_amount - self.paid_amount

class APPayment(models.Model):
    STATUS_CHOICES = (
        ('DRAFT', '草稿'),
        ('PENDING_APPROVAL', '待审核'),
        ('APPROVED', '已审核'),
        ('COMPLETED', '已支付'),
        ('CANCELLED', '已作废'),
    )
    PAYMENT_METHODS = (
        ('CASH', '现金'),
        ('BANK_TRANSFER', '银行转账'),
        ('CHECK', '支票'),
        ('WECHAT', '微信'),
        ('ALIPAY', '支付宝'),
        ('OTHER', '其他'),
    )

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='ap_payments', null=True, blank=True)
    payment_no = models.CharField(max_length=50, unique=True, verbose_name="付款单号")
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name='payments')
    
    payment_date = models.DateField(verbose_name="付款日期")
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHODS, default='BANK_TRANSFER')
    bank_account = models.CharField(max_length=100, null=True, blank=True, verbose_name="银行账号")
    cash_account = models.ForeignKey('finance.CashAccount', on_delete=models.PROTECT, null=True, blank=True, verbose_name="付款账户")
    
    currency_code = models.CharField(max_length=10, default='CNY')
    exchange_rate = models.DecimalField(max_digits=10, decimal_places=4, default=1.0)
    
    payment_amount = models.DecimalField(max_digits=15, decimal_places=2, verbose_name="付款金额")
    allocated_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0, verbose_name="已核销金额")
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='DRAFT')
    
    attachment_id = models.IntegerField(null=True, blank=True, verbose_name="附件ID")
    remark = models.TextField(null=True, blank=True)
    
    dept = models.ForeignKey(ERPDepartment, on_delete=models.SET_NULL, null=True, blank=True)
    created_by = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, related_name='created_ap_payments')
    submitted_by = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='submitted_ap_payments')
    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_ap_payments')
    approved_at = models.DateTimeField(null=True, blank=True)
    executed_at = models.DateTimeField(null=True, blank=True, verbose_name="执行时间")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "付款单"
        verbose_name_plural = verbose_name
        ordering = ['-payment_date', '-created_at']

    @property
    def unallocated_amount(self):
        return self.payment_amount - self.allocated_amount

class APAllocation(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='ap_allocations', null=True, blank=True)
    allocation_no = models.CharField(max_length=50, unique=True, verbose_name="核销编号")
    ap_account = models.ForeignKey(APAccount, on_delete=models.PROTECT, related_name='allocations')
    payment = models.ForeignKey(APPayment, on_delete=models.PROTECT, related_name='allocations')
    amount = models.DecimalField(max_digits=15, decimal_places=2, verbose_name="核销金额")
    allocation_date = models.DateField(auto_now_add=True, verbose_name="核销日期")
    
    created_by = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "付款核销"
        verbose_name_plural = verbose_name
        ordering = ['-created_at']


class SupplierCreditNote(models.Model):
    STATUS_CHOICES = (
        ('OPEN', '未使用'),
        ('PARTIAL_USED', '部分使用'),
        ('USED', '已使用'),
        ('CANCELLED', '已作废'),
    )

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='supplier_credit_notes', null=True, blank=True)
    credit_note_no = models.CharField(max_length=50, unique=True, verbose_name="供应商贷项单号")
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name='credit_notes')
    source_document_no_snapshot = models.CharField(max_length=100, verbose_name="来源单号快照")
    source_id = models.IntegerField(null=True, blank=True, verbose_name="来源单据ID")
    amount = models.DecimalField(max_digits=15, decimal_places=2, verbose_name="贷项金额")
    used_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0, verbose_name="已使用金额")
    note_date = models.DateField(verbose_name="贷项日期")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='OPEN')
    remark = models.TextField(null=True, blank=True)
    created_by = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, related_name='created_supplier_credit_notes')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "供应商贷项"
        verbose_name_plural = verbose_name
        ordering = ['-created_at']

    @property
    def remaining_amount(self):
        return self.amount - self.used_amount

class APOperationLog(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='ap_operation_logs', null=True, blank=True)
    ap_account = models.ForeignKey(APAccount, on_delete=models.CASCADE, null=True, blank=True, related_name='logs')
    payment = models.ForeignKey(APPayment, on_delete=models.CASCADE, null=True, blank=True, related_name='logs')
    
    action = models.CharField(max_length=100, verbose_name="操作内容")
    before_value = models.TextField(null=True, blank=True)
    after_value = models.TextField(null=True, blank=True)
    
    operator = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "应付操作日志"
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
