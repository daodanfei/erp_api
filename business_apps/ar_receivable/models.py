from django.db import models
from business_apps.crm.models import Customer
from business_apps.sales.models import SalesOrder
from business_apps.supply_chain.models import OutboundOrder
from core_apps.erp_auth.models import ERPDepartment, ERPUser
from core_apps.tenant.models import Tenant

class Receivable(models.Model):
    STATUS_CHOICES = (
        ('UNPAID', '未收款'),
        ('PARTIAL_PAID', '部分收款'),
        ('PAID', '已结清'),
        ('REFUND_PENDING', '待退款'),
        ('PARTIAL_REFUNDED', '部分退款'),
        ('REFUNDED', '已退款'),
        ('CANCELLED', '已取消'),
    )

    SOURCE_TYPE_CHOICES = (
        ('SALES_ORDER', '销售订单'),
        ('OUTBOUND_ORDER', '销售出库单'),
        ('SALES_RETURN', '销售退货单'),
        ('MANUAL', '手工创建'),
    )

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='receivables', null=True, blank=True)
    receivable_no = models.CharField(max_length=50, unique=True, verbose_name="应收单号")
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name='receivables')
    sales_order = models.ForeignKey(SalesOrder, on_delete=models.PROTECT, related_name='receivables', null=True, blank=True)
    outbound_order = models.ForeignKey(OutboundOrder, on_delete=models.PROTECT, related_name='receivables', null=True, blank=True)
    source_type = models.CharField(max_length=50, choices=SOURCE_TYPE_CHOICES, default='OUTBOUND_ORDER', verbose_name="来源类型")
    
    amount = models.DecimalField(max_digits=15, decimal_places=2, verbose_name="应收总额")
    written_off_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0, verbose_name="已核销金额")
    
    due_date = models.DateField(verbose_name="到期日")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='UNPAID', verbose_name="状态")
    
    remark = models.TextField(null=True, blank=True, verbose_name="备注")
    dept = models.ForeignKey(ERPDepartment, on_delete=models.SET_NULL, null=True, blank=True)
    created_by = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, related_name='created_receivables')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    is_deleted = models.BooleanField(default=False)

    class Meta:
        verbose_name = "应收账款"
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['outbound_order']),
        ]

    @property
    def balance(self):
        if self.amount >= 0:
            return self.amount - self.written_off_amount
        return abs(self.amount) - self.written_off_amount
        
    @property
    def is_overdue(self):
        from django.utils import timezone
        return self.amount > 0 and self.status not in ('PAID', 'CANCELLED') and self.due_date < timezone.now().date()
        
    @property
    def overdue_days(self):
        from django.utils import timezone
        if self.is_overdue:
            return (timezone.now().date() - self.due_date).days
        return 0


class CustomerRefund(models.Model):
    STATUS_CHOICES = (
        ('DRAFT', '草稿'),
        ('PENDING_APPROVAL', '待审核'),
        ('APPROVED', '已审核'),
        ('COMPLETED', '已退款'),
        ('CANCELLED', '已作废'),
    )
    PAYMENT_METHODS = (
        ('BANK_TRANSFER', '银行转账'),
        ('WECHAT', '微信支付'),
        ('ALIPAY', '支付宝'),
        ('CASH', '现金'),
        ('OTHER', '其他'),
    )

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='customer_refunds', null=True, blank=True)
    refund_no = models.CharField(max_length=50, unique=True, verbose_name="退款单号")
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name='refunds')
    receivable = models.ForeignKey(Receivable, on_delete=models.PROTECT, related_name='refunds', verbose_name="对应红字应收")
    refund_amount = models.DecimalField(max_digits=15, decimal_places=2, verbose_name="退款金额")
    refund_date = models.DateField(verbose_name="退款日期")
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHODS, default='BANK_TRANSFER')
    bank_account = models.CharField(max_length=100, null=True, blank=True, verbose_name="退款银行卡/账号")
    cash_account = models.ForeignKey('finance.CashAccount', on_delete=models.PROTECT, null=True, blank=True, verbose_name="退款账户")
    reference_no = models.CharField(max_length=100, null=True, blank=True, verbose_name="交易流水号/支票号")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='DRAFT')
    remark = models.TextField(null=True, blank=True)
    dept = models.ForeignKey(ERPDepartment, on_delete=models.SET_NULL, null=True, blank=True)
    created_by = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, related_name='created_customer_refunds')
    submitted_by = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='submitted_customer_refunds')
    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_customer_refunds')
    approved_at = models.DateTimeField(null=True, blank=True)
    executed_at = models.DateTimeField(null=True, blank=True, verbose_name="执行时间")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_deleted = models.BooleanField(default=False)

    class Meta:
        verbose_name = "客户退款单"
        verbose_name_plural = verbose_name
        ordering = ['-refund_date', '-created_at']

class Receipt(models.Model):
    STATUS_CHOICES = (
        ('DRAFT', '草稿'),
        ('UNWRITTEN', '未核销'),
        ('PARTIAL_WRITTEN', '部分核销'),
        ('WRITTEN', '已核销'),
        ('CANCELLED', '已作废'),
    )
    PAYMENT_METHODS = (
        ('BANK_TRANSFER', '银行转账'),
        ('WECHAT', '微信支付'),
        ('ALIPAY', '支付宝'),
        ('CASH', '现金'),
        ('OTHER', '其他'),
    )

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='receipts', null=True, blank=True)
    receipt_no = models.CharField(max_length=50, unique=True, verbose_name="收款单号")
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name='receipts')
    
    amount = models.DecimalField(max_digits=15, decimal_places=2, verbose_name="收款总额")
    unwritten_amount = models.DecimalField(max_digits=15, decimal_places=2, verbose_name="未核销金额")
    
    receipt_date = models.DateField(verbose_name="收款日期")
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHODS, default='BANK_TRANSFER')
    cash_account = models.ForeignKey('finance.CashAccount', on_delete=models.PROTECT, null=True, blank=True, verbose_name="收款账户")
    reference_no = models.CharField(max_length=100, null=True, blank=True, verbose_name="交易流水号/支票号")
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='DRAFT')
    
    remark = models.TextField(null=True, blank=True)
    dept = models.ForeignKey(ERPDepartment, on_delete=models.SET_NULL, null=True, blank=True)
    created_by = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, related_name='created_receipts')
    approved_by = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_receipts')
    approved_at = models.DateTimeField(null=True, blank=True)
    executed_at = models.DateTimeField(null=True, blank=True, verbose_name="执行时间")
    created_at = models.DateTimeField(auto_now_add=True)
    
    is_deleted = models.BooleanField(default=False)

    class Meta:
        verbose_name = "收款单"
        verbose_name_plural = verbose_name
        ordering = ['-receipt_date', '-created_at']

class WriteOff(models.Model):
    WRITE_OFF_TYPE_CHOICES = (
        ('RECEIPT', '收款核销'),
        ('RETURN_OFFSET', '退货冲减'),
    )

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='write_offs', null=True, blank=True)
    write_off_no = models.CharField(max_length=50, unique=True, verbose_name="核销单号")
    receivable = models.ForeignKey(Receivable, on_delete=models.PROTECT, related_name='write_offs')
    receipt = models.ForeignKey(Receipt, on_delete=models.PROTECT, related_name='write_offs', null=True, blank=True)
    amount = models.DecimalField(max_digits=15, decimal_places=2, verbose_name="核销金额")
    write_off_type = models.CharField(max_length=30, choices=WRITE_OFF_TYPE_CHOICES, default='RECEIPT', verbose_name="核销类型")
    
    write_off_date = models.DateField(auto_now_add=True)
    operator = models.ForeignKey(ERPUser, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "核销记录"
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
